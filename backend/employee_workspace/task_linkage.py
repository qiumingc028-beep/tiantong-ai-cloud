from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.models import TaskCenterAuditLog, TaskCenterTask


PENDING_STATUSES = {"created", "pending", "assigned"}
RUNNING_STATUSES = {"in_progress", "running"}
COMPLETED_STATUSES = {"accepted", "audited", "completed", "summarized"}
FAILED_STATUSES = {"rejected", "failed", "blocked"}


def build_task_linkage(db: Session, employee_code: str) -> dict[str, Any]:
    tasks = (
        db.query(TaskCenterTask)
        .filter(TaskCenterTask.assigned_ai_employee_code == employee_code)
        .order_by(TaskCenterTask.id.desc())
        .limit(100)
        .all()
    )
    rows = [task_to_row(db, task) for task in tasks]
    return {
        "pending_tasks": [row for row in rows if row["status"] in PENDING_STATUSES],
        "running_tasks": [row for row in rows if row["status"] in RUNNING_STATUSES],
        "completed_tasks": [row for row in rows if row["status"] in COMPLETED_STATUSES],
        "failed_tasks": [row for row in rows if row["status"] in FAILED_STATUSES],
        "history_completed_count": sum(1 for row in rows if row["status"] in COMPLETED_STATUSES),
        "current_task": next((row for row in rows if row["status"] in PENDING_STATUSES | RUNNING_STATUSES), None),
    }


def task_to_row(db: Session, task: TaskCenterTask) -> dict[str, Any]:
    latest_log = (
        db.query(TaskCenterAuditLog)
        .filter(TaskCenterAuditLog.task_id == task.id)
        .order_by(TaskCenterAuditLog.id.desc())
        .first()
    )
    return {
        "task_id": task.id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "source": task.source,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "failure_reason": failure_reason(task, latest_log),
        "can_execute_without_approval": can_execute_without_approval(task),
        "requires_tian_shen": requires_tian_shen(task),
    }


def failure_reason(task: TaskCenterTask, latest_log: TaskCenterAuditLog | None) -> str:
    if task.status == "rejected":
        return latest_log.detail if latest_log and latest_log.detail else "任务被驳回"
    if task.status == "failed":
        return latest_log.detail if latest_log and latest_log.detail else "任务失败"
    if task.status == "blocked":
        return latest_log.detail if latest_log and latest_log.detail else "任务阻塞"
    return ""


def requires_tian_shen(task: TaskCenterTask) -> bool:
    text = f"{task.title} {task.description or ''}".lower()
    return any(keyword in text for keyword in ["deploy", "部署", "git push", "权限", "花钱", "预算", "广告"])


def can_execute_without_approval(task: TaskCenterTask) -> bool:
    return task.status in PENDING_STATUSES and not requires_tian_shen(task)
