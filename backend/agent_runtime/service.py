from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from ..auth import current_user
from ..models import AiEmployee, TaskCenterTask, User
from .audit import employee_actor, execution_actor, payload_summary, redact_text, sanitize_payload, write_audit_event
from .constants import APPROVAL_STATUS_LABELS, AUDIT_EVENT_LABELS, CAPABILITY_TYPES, EXECUTION_STATUS_LABELS, EXECUTOR_TYPES, RISK_LEVELS
from .exceptions import (
    ApprovalRequiredError,
    CapabilityNotFoundError,
    ExecutionNotFoundError,
    ExecutorUnavailableError,
    InputValidationError,
    PermissionDeniedError,
)
from .executor import get_executor
from .executor_types import ExecutorContext
from .models import AgentCapability, AgentExecution, AgentExecutionAudit
from .permission import ensure_agent_runtime_enabled, evaluate_permission
from .registry import capability_to_dict, list_capabilities as registry_list_capabilities, resolve_capability
from ..research_runtime.service import persist_research_result


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def serialize_payload(payload_json: str | None) -> dict[str, Any] | None:
    if not payload_json:
        return None
    try:
        parsed = json.loads(payload_json)
    except Exception:
        return {"value": payload_json}
    return sanitize_payload(parsed)


def serialize_capability(capability: AgentCapability) -> dict[str, Any]:
    return capability_to_dict(capability)


def serialize_execution(execution: AgentExecution, db: Session) -> dict[str, Any]:
    employee = db.get(AiEmployee, execution.employee_id) if execution.employee_id else None
    capability = db.get(AgentCapability, execution.capability_id)
    return {
        "execution_id": execution.execution_id,
        "task_id": execution.task_id,
        "employee_id": execution.employee_id,
        "employee_code": employee.employee_code if employee else None,
        "employee_name": employee.employee_name if employee else None,
        "capability_id": execution.capability_id,
        "capability_name": capability.capability_name if capability else None,
        "capability_type": capability.capability_type if capability else None,
        "status": execution.status,
        "status_label": EXECUTION_STATUS_LABELS.get(execution.status, execution.status),
        "risk_level": execution.risk_level,
        "approval_status": execution.approval_status,
        "approval_status_label": APPROVAL_STATUS_LABELS.get(execution.approval_status, execution.approval_status),
        "executor_type": execution.executor_type,
        "input_payload": serialize_payload(execution.input_payload),
        "output_payload": serialize_payload(execution.output_payload),
        "error_code": execution.error_code,
        "error_message": execution.error_message,
        "retry_count": execution.retry_count,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "finished_at": execution.finished_at.isoformat() if execution.finished_at else None,
        "duration_ms": execution.duration_ms,
        "trace_id": execution.trace_id,
        "created_by_id": execution.created_by_id,
        "created_at": execution.created_at.isoformat() if execution.created_at else None,
        "updated_at": execution.updated_at.isoformat() if execution.updated_at else None,
    }


def list_capabilities(db: Session) -> list[dict[str, Any]]:
    ensure_agent_runtime_enabled()
    rows = registry_list_capabilities(db)
    return [serialize_capability(row) for row in rows]


def get_capability(db: Session, capability_id: str) -> dict[str, Any]:
    ensure_agent_runtime_enabled()
    row = resolve_capability(db, capability_id)
    if not row:
        raise CapabilityNotFoundError("能力不存在")
    return serialize_capability(row)


def create_capability(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_agent_runtime_enabled()
    capability_id = str(payload.get("capability_id") or "").strip()
    if not capability_id:
        raise InputValidationError("能力标识不能为空")
    capability = db.get(AgentCapability, capability_id) or AgentCapability(capability_id=capability_id)
    capability.capability_name = str(payload.get("capability_name") or "").strip()
    capability.capability_type = str(payload.get("capability_type") or "").strip()
    if not capability.capability_name or not capability.capability_type:
        raise InputValidationError("能力名称和类型不能为空")
    if capability.capability_type not in CAPABILITY_TYPES:
        raise InputValidationError("能力类型不受支持")
    capability.description = payload.get("description")
    capability.executor_type = str(payload.get("executor_type") or "mock").strip() or "mock"
    capability.risk_level = str(payload.get("risk_level") or "low").strip() or "low"
    if capability.executor_type not in EXECUTOR_TYPES:
        raise InputValidationError("执行器类型不受支持")
    if capability.risk_level not in RISK_LEVELS:
        raise InputValidationError("风险等级不受支持")
    capability.enabled = bool(payload.get("enabled", True))
    capability.readonly = bool(payload.get("readonly", True))
    capability.requires_boss_approval = bool(payload.get("requires_boss_approval", False))
    capability.requires_security_audit = bool(payload.get("requires_security_audit", False))
    capability.timeout_seconds = int(payload.get("timeout_seconds") or 30)
    capability.max_retries = int(payload.get("max_retries") or 0)
    capability.input_schema_json = payload.get("input_schema_json")
    capability.output_schema_json = payload.get("output_schema_json")
    capability.allowed_employee_codes_json = json.dumps(payload.get("allowed_employee_codes") or [], ensure_ascii=False)
    capability.version = str(payload.get("version") or "1.0.0")
    db.add(capability)
    db.commit()
    db.refresh(capability)
    return serialize_capability(capability)


def update_capability(db: Session, capability_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_agent_runtime_enabled()
    capability = resolve_capability(db, capability_id)
    if not capability:
        raise CapabilityNotFoundError("能力不存在")
    for field in (
        "capability_name",
        "capability_type",
        "description",
        "executor_type",
        "risk_level",
        "input_schema_json",
        "output_schema_json",
        "version",
    ):
        if payload.get(field) is not None:
            setattr(capability, field, payload.get(field))
    if capability.capability_type not in CAPABILITY_TYPES:
        raise InputValidationError("能力类型不受支持")
    if capability.executor_type not in EXECUTOR_TYPES:
        raise InputValidationError("执行器类型不受支持")
    if capability.risk_level not in RISK_LEVELS:
        raise InputValidationError("风险等级不受支持")
    for field in ("enabled", "readonly", "requires_boss_approval", "requires_security_audit"):
        if payload.get(field) is not None:
            setattr(capability, field, bool(payload.get(field)))
    if payload.get("timeout_seconds") is not None:
        capability.timeout_seconds = int(payload.get("timeout_seconds"))
    if payload.get("max_retries") is not None:
        capability.max_retries = int(payload.get("max_retries"))
    if payload.get("allowed_employee_codes") is not None:
        capability.allowed_employee_codes_json = json.dumps(payload.get("allowed_employee_codes") or [], ensure_ascii=False)
    db.commit()
    db.refresh(capability)
    return serialize_capability(capability)


def enable_capability(db: Session, capability_id: str, enabled: bool = True) -> dict[str, Any]:
    capability = resolve_capability(db, capability_id)
    if not capability:
        raise CapabilityNotFoundError("能力不存在")
    capability.enabled = enabled
    db.commit()
    db.refresh(capability)
    return serialize_capability(capability)


def list_executions(db: Session, task_id: int | None = None, employee_id: int | None = None) -> list[dict[str, Any]]:
    ensure_agent_runtime_enabled()
    query = db.query(AgentExecution).options(joinedload(AgentExecution.capability)).order_by(AgentExecution.created_at.desc())
    if task_id is not None:
        query = query.filter(AgentExecution.task_id == task_id)
    if employee_id is not None:
        query = query.filter(AgentExecution.employee_id == employee_id)
    rows = query.all()
    return [serialize_execution(row, db) for row in rows]


def get_execution(db: Session, execution_id: str) -> dict[str, Any]:
    ensure_agent_runtime_enabled()
    execution = db.get(AgentExecution, execution_id)
    if not execution:
        raise ExecutionNotFoundError("执行记录不存在")
    return serialize_execution(execution, db)


def _ensure_task_link(db: Session, task_id: int | None) -> TaskCenterTask | None:
    if task_id is None:
        return None
    task = db.get(TaskCenterTask, task_id)
    if not task:
        raise InputValidationError("任务不存在")
    return task


def _ensure_employee(db: Session, employee_id: int) -> AiEmployee:
    employee = db.get(AiEmployee, employee_id)
    if not employee:
        raise InputValidationError("AI 员工不存在")
    return employee


def create_execution(user: User, db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_agent_runtime_enabled()
    task = _ensure_task_link(db, payload.get("task_id"))
    employee = _ensure_employee(db, int(payload.get("employee_id")))
    capability_id = str(payload.get("capability_id") or "").strip()
    if not capability_id:
        raise InputValidationError("能力标识不能为空")
    capability = resolve_capability(db, capability_id)
    if not capability:
        raise CapabilityNotFoundError("能力不存在")

    permission = evaluate_permission(
        db,
        user=user,
        employee=employee,
        capability_id=capability_id,
        input_payload=payload.get("input_payload") or {},
        executor_type=payload.get("executor_type"),
    )
    trace_id = str(payload.get("trace_id") or uuid.uuid4())
    stored_input_payload = sanitize_payload(payload.get("input_payload") or {})
    execution = AgentExecution(
        execution_id=str(uuid.uuid4()),
        task_id=task.id if task else None,
        employee_id=employee.id,
        capability_id=capability.capability_id,
        status="waiting_approval" if permission.approval_required else "waiting_execution",
        risk_level=permission.risk_level,
        approval_status="pending" if permission.approval_required else "not_required",
        executor_type=permission.executor_type,
        input_payload=json.dumps(stored_input_payload, ensure_ascii=False),
        retry_count=0,
        trace_id=trace_id,
        created_by_id=user.id,
    )
    db.add(execution)
    db.flush()
    write_audit_event(
        db,
        execution,
        event_type="execution_created",
        actor_type="user",
        actor_id=execution_actor(user),
        approval_status=execution.approval_status,
        risk_level=execution.risk_level,
        input_summary=stored_input_payload,
        executor_name=permission.executor_type,
        source_ip=None,
        sensitive_data_involved=contains_sensitive(payload.get("input_payload")),
    )
    if permission.approval_required:
        db.commit()
        db.refresh(execution)
        return serialize_execution(execution, db)
    result = run_execution_flow(db, execution, user=user, task=task, approval_bypass=True)
    return result


def approve_execution(db: Session, execution_id: str, user: User, boss_confirmed: bool = True, security_audited: bool = True) -> dict[str, Any]:
    ensure_agent_runtime_enabled()
    execution = db.get(AgentExecution, execution_id)
    if not execution:
        raise ExecutionNotFoundError("执行记录不存在")
    if execution.status not in {"waiting_approval", "pending_validation"}:
        raise InputValidationError("当前状态不允许审批")
    execution.approval_status = "approved"
    execution.status = "waiting_execution"
    db.flush()
    write_audit_event(
        db,
        execution,
        event_type="execution_approved",
        actor_type="user",
        actor_id=execution_actor(user),
        approval_status=execution.approval_status,
        approval_decision="approved",
        risk_level=execution.risk_level,
        executor_name=execution.executor_type,
    )
    db.commit()
    db.refresh(execution)
    task = db.get(TaskCenterTask, execution.task_id) if execution.task_id else None
    return run_execution_flow(db, execution, user=user, task=task, approval_bypass=True, approve_after=True)


def reject_execution(db: Session, execution_id: str, user: User, reason: str | None = None) -> dict[str, Any]:
    ensure_agent_runtime_enabled()
    execution = db.get(AgentExecution, execution_id)
    if not execution:
        raise ExecutionNotFoundError("执行记录不存在")
    execution.approval_status = "rejected"
    execution.status = "rejected"
    execution.error_code = "APPROVAL_REJECTED"
    execution.error_message = reason or "老板拒绝执行"
    execution.finished_at = now_utc()
    execution.duration_ms = 0
    write_audit_event(
        db,
        execution,
        event_type="execution_rejected",
        actor_type="user",
        actor_id=execution_actor(user),
        approval_status=execution.approval_status,
        approval_decision="rejected",
        risk_level=execution.risk_level,
        error_summary=reason or "老板拒绝执行",
        executor_name=execution.executor_type,
    )
    db.commit()
    db.refresh(execution)
    return serialize_execution(execution, db)


def cancel_execution(db: Session, execution_id: str, user: User, reason: str | None = None) -> dict[str, Any]:
    ensure_agent_runtime_enabled()
    execution = db.get(AgentExecution, execution_id)
    if not execution:
        raise ExecutionNotFoundError("执行记录不存在")
    if execution.status in {"success", "failed", "cancelled", "timeout"}:
        raise InputValidationError("已结束的执行无法取消")
    execution.status = "cancelled"
    execution.approval_status = execution.approval_status if execution.approval_status != "pending" else "rejected"
    execution.error_code = "EXECUTION_CANCELLED"
    execution.error_message = reason or "执行已取消"
    execution.finished_at = now_utc()
    execution.duration_ms = execution.duration_ms or 0
    write_audit_event(
        db,
        execution,
        event_type="execution_cancelled",
        actor_type="user",
        actor_id=execution_actor(user),
        approval_status=execution.approval_status,
        approval_decision="cancelled",
        risk_level=execution.risk_level,
        error_summary=reason or "执行已取消",
        executor_name=execution.executor_type,
    )
    db.commit()
    db.refresh(execution)
    return serialize_execution(execution, db)


def get_execution_audit(db: Session, execution_id: str) -> list[dict[str, Any]]:
    ensure_agent_runtime_enabled()
    execution = db.get(AgentExecution, execution_id)
    if not execution:
        raise ExecutionNotFoundError("执行记录不存在")
    audits = db.query(AgentExecutionAudit).filter(AgentExecutionAudit.execution_id == execution_id).order_by(AgentExecutionAudit.created_at.asc(), AgentExecutionAudit.id.asc()).all()
    return [
        {
            "id": row.id,
            "execution_id": row.execution_id,
            "event_type": row.event_type,
            "event_label": AUDIT_EVENT_LABELS.get(row.event_type, row.event_type),
            "actor_type": row.actor_type,
            "actor_id": row.actor_id,
            "approval_status": row.approval_status,
            "approval_decision": row.approval_decision,
            "risk_level": row.risk_level,
            "input_summary": row.input_summary,
            "output_summary": row.output_summary,
            "error_summary": row.error_summary,
            "executor_name": row.executor_name,
            "source_ip": row.source_ip,
            "sensitive_data_involved": row.sensitive_data_involved,
            "trace_id": row.trace_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in audits
    ]


def run_execution_flow(
    db: Session,
    execution: AgentExecution,
    user: User,
    task: TaskCenterTask | None = None,
    approval_bypass: bool = False,
    approve_after: bool = False,
) -> dict[str, Any]:
    capability = db.get(AgentCapability, execution.capability_id)
    if not capability:
        raise CapabilityNotFoundError("能力不存在")
    if execution.status not in {"waiting_execution", "running"}:
        raise InputValidationError("当前状态不允许执行")
    executor = get_executor(execution.executor_type)
    employee = db.get(AiEmployee, execution.employee_id) if execution.employee_id else None
    context = ExecutorContext(
        execution_id=execution.execution_id,
        trace_id=execution.trace_id,
        capability_id=capability.capability_id,
        capability_name=capability.capability_name,
        capability_type=capability.capability_type,
        executor_type=execution.executor_type,
        employee_id=execution.employee_id,
        employee_code=employee.employee_code if employee else None,
        employee_name=employee.employee_name if employee else None,
        task_id=execution.task_id,
        retry_count=execution.retry_count,
        timeout_seconds=capability.timeout_seconds,
        input_payload=serialize_payload(execution.input_payload) or {},
    )
    execution.status = "running"
    execution.started_at = execution.started_at or now_utc()
    db.flush()
    write_audit_event(
        db,
        execution,
        event_type="execution_started",
        actor_type="user",
        actor_id=execution_actor(user),
        approval_status=execution.approval_status,
        risk_level=execution.risk_level,
        input_summary=payload_summary(context.input_payload),
        executor_name=executor.get_metadata().get("name", "MockExecutor"),
    )
    result = executor.execute(context)
    execution.started_at = execution.started_at or result.started_at
    execution.finished_at = result.finished_at
    execution.duration_ms = result.duration_ms
    execution.output_payload = json.dumps(sanitize_payload(result.output), ensure_ascii=False)
    execution.error_code = result.error_code
    execution.error_message = redact_text(result.error_message)
    if result.success:
        execution.status = "success"
        write_audit_event(
            db,
            execution,
            event_type="execution_succeeded",
            actor_type="executor",
            actor_id=executor.get_metadata().get("name", "MockExecutor"),
            approval_status=execution.approval_status,
            risk_level=execution.risk_level,
            output_summary=payload_summary(result.output),
            executor_name=executor.get_metadata().get("name", "MockExecutor"),
        )
        if task and execution.task_id and payload_should_write_back(context.input_payload):
            note = f"[V2 Agent Runtime] {capability.capability_name}: {json.dumps(result.output, ensure_ascii=False)}"
            task.summary = ((task.summary or "") + ("\n" if task.summary else "") + note).strip()
        if capability.capability_id == "research.public.multi_source":
            persist_research_result(db, execution, context.input_payload, result.output)
    elif result.error_code == "MOCK_TIMEOUT":
        execution.status = "timeout"
        write_audit_event(
            db,
            execution,
            event_type="execution_timeout",
            actor_type="executor",
            actor_id=executor.get_metadata().get("name", "MockExecutor"),
            approval_status=execution.approval_status,
            risk_level=execution.risk_level,
            error_summary=result.error_message,
            executor_name=executor.get_metadata().get("name", "MockExecutor"),
        )
    elif result.retryable and execution.retry_count < capability.max_retries:
        execution.retry_count += 1
        write_audit_event(
            db,
            execution,
            event_type="execution_retry",
            actor_type="executor",
            actor_id=executor.get_metadata().get("name", "MockExecutor"),
            approval_status=execution.approval_status,
            risk_level=execution.risk_level,
            error_summary=result.error_message,
            executor_name=executor.get_metadata().get("name", "MockExecutor"),
        )
        db.commit()
        db.refresh(execution)
        return run_execution_flow(db, execution, user=user, task=task, approval_bypass=approval_bypass, approve_after=approve_after)
    else:
        execution.status = "failed"
        write_audit_event(
            db,
            execution,
            event_type="execution_failed",
            actor_type="executor",
            actor_id=executor.get_metadata().get("name", "MockExecutor"),
            approval_status=execution.approval_status,
            risk_level=execution.risk_level,
            error_summary=result.error_message,
            executor_name=executor.get_metadata().get("name", "MockExecutor"),
        )
    db.commit()
    db.refresh(execution)
    return serialize_execution(execution, db)


def payload_should_write_back(payload: dict[str, Any]) -> bool:
    value = payload.get("link_task_result")
    return bool(value)


def contains_sensitive(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    text = json.dumps(payload, ensure_ascii=False).lower()
    return any(marker in text for marker in ("password", "secret", "token", "cookie", "private_key", "api key"))
