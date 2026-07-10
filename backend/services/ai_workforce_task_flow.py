from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import AiEmployee, TaskCenterAuditLog, TaskCenterTask


CREATED_STATUSES = {"created", "split"}
PROCESSING_STATUSES = {"assigned", "running", "in_progress"}
WAITING_CONFIRM_STATUSES = {"result_submitted", "review_pending"}
APPROVED_STATUSES = {"accepted", "audited"}
COMPLETED_STATUSES = {"summarized", "completed"}
REJECTED_STATUSES = {"rejected", "failed", "blocked"}
TASK_FLOW_STATUSES = [
    "created",
    "processing",
    "waiting_confirm",
    "approved",
    "completed",
    "rejected",
]


def build_employee_task_flow(db: Session, employee_id: str) -> dict:
    employee = (
        db.query(AiEmployee)
        .filter(AiEmployee.employee_code == employee_id)
        .filter(AiEmployee.is_legacy.is_(False))
        .first()
    )
    tasks = (
        db.query(TaskCenterTask)
        .filter(TaskCenterTask.assigned_ai_employee_code == employee_id)
        .order_by(TaskCenterTask.updated_at.desc(), TaskCenterTask.id.desc())
        .all()
    )
    audit_counts = audit_count_by_task(db, [task.id for task in tasks])
    task_items = [task_flow_item(task, audit_counts.get(task.id, 0)) for task in tasks]
    return {
        "mode": "readonly",
        "employee": employee_payload(employee, employee_id),
        "summary": task_flow_summary(task_items),
        "tasks": task_items,
        "manual_confirm": {
            "boss_confirm_required": any(item["boss_confirm_required"] for item in task_items),
            "security_audited_required": any(item["security_audited_required"] for item in task_items),
        },
        "security": security_payload(),
        "empty_state": {
            "no_tasks": len(task_items) == 0,
            "message": "暂无任务流数据" if len(task_items) == 0 else "",
        },
    }


def build_task_lifecycle(db: Session, task_id: int) -> dict | None:
    task = db.get(TaskCenterTask, task_id)
    if task is None:
        return None
    audit_logs = task_audit_logs(db, task_id)
    return {
        "mode": "readonly",
        "task": task_payload(task),
        "lifecycle": lifecycle_from_audit(task, audit_logs),
        "audit": [audit_log_payload(log) for log in audit_logs],
        "manual_confirm": manual_confirm_payload(task, len(audit_logs)),
        "security": security_payload(),
    }


def build_waiting_confirm_tasks(db: Session) -> dict:
    tasks = (
        db.query(TaskCenterTask)
        .filter(TaskCenterTask.status.in_(WAITING_CONFIRM_STATUSES))
        .order_by(TaskCenterTask.updated_at.desc(), TaskCenterTask.id.desc())
        .all()
    )
    audit_counts = audit_count_by_task(db, [task.id for task in tasks])
    items = [task_flow_item(task, audit_counts.get(task.id, 0)) for task in tasks]
    return {
        "mode": "readonly",
        "total": len(items),
        "tasks": items,
        "manual_confirm": {
            "boss_confirm_required": len(items) > 0,
            "security_audited_required": any(item["security_audited_required"] for item in items),
        },
        "security": security_payload(),
        "empty_state": {
            "no_waiting_confirm_tasks": len(items) == 0,
            "message": "暂无待 Boss 确认任务" if len(items) == 0 else "",
        },
    }


def map_task_lifecycle_status(task_center_status: str | None) -> str:
    status = (task_center_status or "").strip().lower()
    if status in CREATED_STATUSES:
        return "created"
    if status in PROCESSING_STATUSES:
        return "processing"
    if status in WAITING_CONFIRM_STATUSES:
        return "waiting_confirm"
    if status in APPROVED_STATUSES:
        return "approved"
    if status in COMPLETED_STATUSES:
        return "completed"
    if status in REJECTED_STATUSES:
        return "rejected"
    return "created"


def employee_payload(employee: AiEmployee | None, employee_id: str) -> dict:
    return {
        "employee_id": employee.employee_code if employee else employee_id,
        "employee_name": employee.employee_name if employee else employee_id,
        "department": employee.legion if employee and employee.legion else "未分配部门",
        "role": employee.duty if employee and employee.duty else "",
        "status": employee.status if employee else "unknown",
    }


def task_payload(task: TaskCenterTask) -> dict:
    lifecycle_status = map_task_lifecycle_status(task.status)
    return {
        "task_id": task.id,
        "title": task.title,
        "description": task.description,
        "employee_id": task.assigned_ai_employee_code,
        "employee_name": task.assigned_ai_employee_name,
        "current_status": lifecycle_status,
        "task_center_status": task.status,
        "priority": task.priority,
        "source": task.source,
        "created_at": isoformat(task.created_at),
        "updated_at": isoformat(task.updated_at),
    }


def task_flow_item(task: TaskCenterTask, audit_count: int) -> dict:
    lifecycle_status = map_task_lifecycle_status(task.status)
    confirm = manual_confirm_payload(task, audit_count)
    return {
        **task_payload(task),
        "lifecycle_status": lifecycle_status,
        "risk_level": risk_level_for_task(task),
        "audit_count": audit_count,
        "boss_confirm_required": confirm["boss_confirm_required"],
        "security_audited_required": confirm["security_audited_required"],
        "manual_confirm_required": confirm["manual_confirm_required"],
        "action_available": False,
    }


def task_flow_summary(task_items: list[dict]) -> dict:
    summary = {"total": len(task_items)}
    for status in TASK_FLOW_STATUSES:
        summary[status] = sum(1 for item in task_items if item["lifecycle_status"] == status)
    return summary


def lifecycle_from_audit(task: TaskCenterTask, audit_logs: list[TaskCenterAuditLog]) -> list[dict]:
    lifecycle = []
    for log in audit_logs:
        lifecycle.append(
            {
                "status": map_task_lifecycle_status(log.to_status or log.from_status),
                "task_center_status": log.to_status or log.from_status,
                "time": isoformat(log.created_at),
                "source": "Task Center",
                "action": log.action,
            }
        )
    if not lifecycle:
        lifecycle.append(
            {
                "status": map_task_lifecycle_status(task.status),
                "task_center_status": task.status,
                "time": isoformat(task.updated_at or task.created_at),
                "source": "Task Center",
                "action": "current_status",
            }
        )
    return lifecycle


def manual_confirm_payload(task: TaskCenterTask, audit_count: int) -> dict:
    lifecycle_status = map_task_lifecycle_status(task.status)
    risk_level = risk_level_for_task(task)
    return {
        "boss_confirm_required": lifecycle_status == "waiting_confirm" or risk_level == "high",
        "security_audited_required": risk_level == "high",
        "manual_confirm_required": lifecycle_status == "waiting_confirm",
        "audit_record_available": audit_count > 0,
        "auto_execute": False,
        "action_available": False,
    }


def risk_level_for_task(task: TaskCenterTask) -> str:
    lifecycle_status = map_task_lifecycle_status(task.status)
    if lifecycle_status == "rejected" or task.priority == "urgent":
        return "high"
    if lifecycle_status in {"waiting_confirm", "approved"}:
        return "medium"
    return "low"


def audit_count_by_task(db: Session, task_ids: list[int]) -> dict[int, int]:
    if not task_ids:
        return {}
    rows = (
        db.query(TaskCenterAuditLog.task_id, TaskCenterAuditLog.id)
        .filter(TaskCenterAuditLog.task_id.in_(task_ids))
        .all()
    )
    counts: dict[int, int] = {}
    for task_id, _ in rows:
        counts[task_id] = counts.get(task_id, 0) + 1
    return counts


def task_audit_logs(db: Session, task_id: int) -> list[TaskCenterAuditLog]:
    return (
        db.query(TaskCenterAuditLog)
        .filter(TaskCenterAuditLog.task_id == task_id)
        .order_by(TaskCenterAuditLog.id.asc())
        .all()
    )


def audit_log_payload(log: TaskCenterAuditLog) -> dict:
    return {
        "id": log.id,
        "task_id": log.task_id,
        "action": log.action,
        "from_status": log.from_status,
        "to_status": log.to_status,
        "lifecycle_status": map_task_lifecycle_status(log.to_status or log.from_status),
        "detail": log.detail,
        "actor_role": log.actor_role,
        "created_at": isoformat(log.created_at),
    }


def security_payload() -> dict:
    return {
        "readonly": True,
        "manual_confirm_required": True,
        "execution_engine_called": False,
        "openclaw_connected": False,
        "n8n_connected": False,
        "auto_execute": False,
    }


def isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
