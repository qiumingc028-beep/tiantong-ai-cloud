from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..tool_center.gateway import clean_text
from .executor import latest_approval
from .models import BrainExecutionContext, BrainExecutionRecovery, BrainExecutionRun, BrainTaskNode, BrainWorkerStatus
from .planner import approval_decision, get_task_chain, write_execution_log
from .queue import dequeue_execution, requeue_execution, update_queue_status
from .state_machine import ExecutionState, normalize_state, transition_run


class BrainExecutionTimeout(RuntimeError):
    pass


def process_next_execution(db: Session, timeout: int = 1, worker_id: str = "brain-worker") -> dict:
    update_worker_status(db, worker_id, "idle")
    item = dequeue_execution(timeout=timeout)
    if not item:
        return {"processed": False, "reason": "empty_queue"}
    return process_execution_item(db, item, worker_id=worker_id)


def process_execution_item(db: Session, item: dict, worker_id: str = "brain-worker") -> dict:
    execution_id = int(item["execution_id"])
    run = db.get(BrainExecutionRun, execution_id)
    if not run:
        update_queue_status(item, "failed", "execution not found")
        return {"processed": False, "status": "failed", "reason": "execution_not_found"}

    if normalize_state(run.status) != ExecutionState.QUEUED:
        update_queue_status(item, "failed", f"execution is not approved: {run.status}")
        write_execution_log(db, run, action="worker_blocked", status="blocked", output_data={"reason": "execution_not_approved"})
        db.commit()
        return {"processed": False, "status": "blocked", "execution_id": execution_id}

    approval = latest_approval(db, execution_id)
    decision = approval_decision(
        run.risk_level,
        boss_confirm=bool(approval and approval.boss_confirmed),
        security_audited=bool(approval and approval.security_audited),
    )
    if decision["blocked"]:
        run.status = ExecutionState.WAIT_APPROVAL.value
        update_queue_status(item, "failed", decision["reason"])
        write_execution_log(db, run, action="worker_security_blocked", status="blocked", output_data={"approval": decision})
        db.commit()
        return {"processed": False, "status": "blocked", "execution_id": execution_id, "approval": decision}

    update_worker_status(db, worker_id, "running", execution_id=run.id, current_task=run.goal)
    update_queue_status(item, "running", "worker claimed execution")
    try:
        result = execute_approved_nodes(db, run, item, worker_id=worker_id)
    except BrainExecutionTimeout as exc:
        return handle_failure(db, run, item, str(exc), timeout=True, worker_id=worker_id)
    except Exception as exc:
        return handle_failure(db, run, item, str(exc), timeout=False, worker_id=worker_id)

    update_queue_status(item, "success", "execution completed")
    update_worker_status(db, worker_id, "idle", success_delta=1, processed_delta=1)
    return result


def execute_approved_nodes(db: Session, run: BrainExecutionRun, item: dict, worker_id: str) -> dict:
    payload = item.get("payload") or {}
    transition_run(db, run, ExecutionState.RUNNING, event_type="worker_started", event_data={"queue": "brain_execution_queue"})
    run.worker_id = worker_id
    run.started_at = datetime.now(timezone.utc)
    if payload.get("simulate_timeout"):
        raise BrainExecutionTimeout("brain execution worker timeout")
    if payload.get("simulate_failure"):
        raise RuntimeError("brain execution worker simulated failure")

    nodes = (
        db.query(BrainTaskNode)
        .filter(BrainTaskNode.execution_id == run.id)
        .order_by(BrainTaskNode.sequence_order.asc(), BrainTaskNode.id.asc())
        .all()
    )
    completed = []
    for node in nodes:
        run.current_node = node.node_id
        update_worker_status(db, worker_id, "running", execution_id=run.id, node_id=node.node_id, current_task=node.task_goal)
        create_execution_context(db, run, node)
        node.status = ExecutionState.RUNNING.value
        write_execution_log(
            db,
            run,
            action="worker_node_started",
            status=ExecutionState.RUNNING.value,
            node_id=node.node_id,
            employee_code=node.employee_code,
            input_data={"task_goal": node.task_goal, "tool_name": node.tool_name},
            output_data={"mode": "approved_tool", "simulation": True},
        )
        node.status = ExecutionState.SUCCESS.value
        write_execution_log(
            db,
            run,
            action="worker_node_completed",
            status=ExecutionState.SUCCESS.value,
            node_id=node.node_id,
            employee_code=node.employee_code,
            output_data={"result": f"{clean_text(node.node_name)} approved safe task completed", "simulation": True},
        )
        completed.append(node.node_id)

    run.current_node = None
    run.finished_at = datetime.now(timezone.utc)
    transition_run(db, run, ExecutionState.SUCCESS, event_data={"completed_nodes": completed})
    write_execution_log(db, run, action="worker_execution_completed", status=ExecutionState.SUCCESS.value, output_data={"completed_nodes": completed})
    db.commit()
    return get_task_chain(db, run.id) or {"processed": True, "execution_id": run.id, "status": run.status}


def handle_failure(db: Session, run: BrainExecutionRun, item: dict, message: str, *, timeout: bool, worker_id: str) -> dict:
    attempt = int(item.get("attempt", 0))
    max_retry = int(item.get("max_retry", 3))
    status = "timeout" if timeout else "failed"
    write_execution_log(
        db,
        run,
        action="worker_timeout" if timeout else "worker_failed",
        status=status,
        output_data={"attempt": attempt, "max_retry": max_retry},
        error_message=message,
    )
    if attempt < max_retry:
        run.retry_count = attempt + 1
        run.last_error = clean_text(message)
        transition_run(db, run, ExecutionState.QUEUED, event_type="worker_retry", event_data={"attempt": attempt + 1, "max_retry": max_retry, "timeout": timeout})
        create_recovery_record(db, run, status, message, attempt + 1, max_retry, "requeued")
        db.commit()
        requeue_execution(item, message)
        update_worker_status(db, worker_id, "idle")
        return {"processed": False, "status": "retrying", "execution_id": run.id, "message": message}

    transition_run(db, run, ExecutionState.TIMEOUT if timeout else ExecutionState.FAILED, event_type="worker_timeout" if timeout else "worker_failed")
    run.error_message = clean_text(message)
    run.last_error = clean_text(message)
    run.finished_at = datetime.now(timezone.utc)
    create_recovery_record(db, run, status, message, attempt, max_retry, "manual_review_required")
    update_queue_status(item, status, message)
    db.commit()
    update_worker_status(db, worker_id, "idle", failed_delta=0 if timeout else 1, timeout_delta=1 if timeout else 0, processed_delta=1)
    return {"processed": True, "status": status, "execution_id": run.id, "message": message}


def create_execution_context(db: Session, run: BrainExecutionRun, node: BrainTaskNode) -> BrainExecutionContext:
    context = BrainExecutionContext(
        execution_id=run.id,
        node_id=node.node_id,
        employee_code=node.employee_code,
        current_task=node.task_goal,
        input_data=json.dumps({"goal": run.goal, "node": node.node_id}, ensure_ascii=False),
        tool_permissions=json.dumps({"tool_name": node.tool_name, "approved": True, "mode": "simulation"}, ensure_ascii=False),
        risk_level=node.risk_level,
        historical_execution=json.dumps({"summary": "no external lookup; internal execution history placeholder"}, ensure_ascii=False),
        approval_status=run.status,
        context_data=json.dumps({"employee_name": node.employee_name, "priority": run.priority}, ensure_ascii=False),
    )
    db.add(context)
    run.employee_id = node.employee_code
    run.context = context.context_data
    return context


def create_recovery_record(
    db: Session,
    run: BrainExecutionRun,
    failure_type: str,
    message: str,
    retry_count: int,
    max_retry: int,
    recovery_status: str,
) -> BrainExecutionRecovery:
    record = BrainExecutionRecovery(
        execution_id=run.id,
        node_id=run.current_node,
        failure_type=failure_type,
        error_message=clean_text(message),
        retry_count=retry_count,
        max_retry=max_retry,
        recovery_action="retry" if recovery_status == "requeued" else "manual_review",
        recovery_status=recovery_status,
    )
    db.add(record)
    return record


def update_worker_status(
    db: Session,
    worker_id: str,
    status: str,
    *,
    execution_id: int | None = None,
    node_id: str | None = None,
    current_task: str | None = None,
    processed_delta: int = 0,
    success_delta: int = 0,
    failed_delta: int = 0,
    timeout_delta: int = 0,
) -> BrainWorkerStatus:
    now = datetime.now(timezone.utc)
    row = db.query(BrainWorkerStatus).filter(BrainWorkerStatus.worker_id == worker_id).one_or_none()
    if row is None:
        row = BrainWorkerStatus(worker_id=worker_id, created_at=now)
        db.add(row)
    row.status = status
    row.current_execution_id = execution_id
    row.current_node_id = node_id
    row.current_task = current_task
    row.heartbeat_at = now
    row.updated_at = now
    row.processed_count = int(row.processed_count or 0) + processed_delta
    row.success_count = int(row.success_count or 0) + success_delta
    row.failed_count = int(row.failed_count or 0) + failed_delta
    row.timeout_count = int(row.timeout_count or 0) + timeout_delta
    db.commit()
    return row
