from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..tool_center.gateway import clean_text
from .executor import latest_approval
from .models import BrainExecutionRun, BrainTaskNode
from .planner import approval_decision, get_task_chain, write_execution_log
from .queue import dequeue_execution, requeue_execution, update_queue_status
from .state_machine import ExecutionState, normalize_state, transition_run


class BrainExecutionTimeout(RuntimeError):
    pass


def process_next_execution(db: Session, timeout: int = 1) -> dict:
    item = dequeue_execution(timeout=timeout)
    if not item:
        return {"processed": False, "reason": "empty_queue"}
    return process_execution_item(db, item)


def process_execution_item(db: Session, item: dict) -> dict:
    execution_id = int(item["execution_id"])
    run = db.get(BrainExecutionRun, execution_id)
    if not run:
        update_queue_status(item, "failed", "execution not found")
        return {"processed": False, "status": "failed", "reason": "execution_not_found"}

    if normalize_state(run.status) != ExecutionState.APPROVED:
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

    update_queue_status(item, "running", "worker claimed execution")
    try:
        result = execute_approved_nodes(db, run, item)
    except BrainExecutionTimeout as exc:
        return handle_failure(db, run, item, str(exc), timeout=True)
    except Exception as exc:
        return handle_failure(db, run, item, str(exc), timeout=False)

    update_queue_status(item, "success", "execution completed")
    return result


def execute_approved_nodes(db: Session, run: BrainExecutionRun, item: dict) -> dict:
    payload = item.get("payload") or {}
    if payload.get("simulate_timeout"):
        raise BrainExecutionTimeout("brain execution worker timeout")
    if payload.get("simulate_failure"):
        raise RuntimeError("brain execution worker simulated failure")

    transition_run(db, run, ExecutionState.RUNNING, event_type="worker_started", event_data={"queue": "brain_execution_queue"})
    run.started_at = datetime.now(timezone.utc)
    nodes = (
        db.query(BrainTaskNode)
        .filter(BrainTaskNode.execution_id == run.id)
        .order_by(BrainTaskNode.sequence_order.asc(), BrainTaskNode.id.asc())
        .all()
    )
    completed = []
    for node in nodes:
        run.current_node = node.node_id
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


def handle_failure(db: Session, run: BrainExecutionRun, item: dict, message: str, *, timeout: bool) -> dict:
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
        run.status = ExecutionState.APPROVED.value
        db.commit()
        requeue_execution(item, message)
        return {"processed": False, "status": "retrying", "execution_id": run.id, "message": message}

    run.status = ExecutionState.FAILED.value
    run.error_message = clean_text(message)
    run.finished_at = datetime.now(timezone.utc)
    update_queue_status(item, status, message)
    db.commit()
    return {"processed": True, "status": status, "execution_id": run.id, "message": message}
