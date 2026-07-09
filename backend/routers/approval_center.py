from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..models import TaskCenterTask


router = APIRouter(prefix="/api/approval-center")

APPROVAL_STATUSES = ("created", "split", "assigned", "result_submitted", "accepted", "rejected")
HIGH_RISK_PRIORITIES = {"high", "critical", "urgent"}


@router.get("/pending")
def get_pending_approvals(request: Request, db: Session = Depends(get_db)):
    require_approval_center_user(request, db)
    items = build_pending_approval_items(db)
    return {
        "readonly": True,
        "pending_count": len(items),
        "items": items,
    }


def require_approval_center_user(request: Request, db: Session):
    user = current_user(request, db)
    role_code = normalize_role(user.role)
    if role_code not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="no boss approval center permission")
    return user


def build_pending_approval_items(db: Session) -> list[dict]:
    rows = (
        db.query(TaskCenterTask)
        .filter(TaskCenterTask.status.in_(APPROVAL_STATUSES))
        .order_by(TaskCenterTask.updated_at.desc(), TaskCenterTask.id.desc())
        .limit(50)
        .all()
    )
    return [approval_item(row) for row in rows]


def approval_item(task: TaskCenterTask) -> dict:
    return {
        "id": task.id,
        "source_ai_employee": task.assigned_ai_employee_name or task.assigned_ai_employee_code or "天统AI系统",
        "title": task.title,
        "description": task.description or task.split_plan or "",
        "risk_level": approval_risk_level(task),
        "recommendation": approval_recommendation(task),
        "created_at": iso(task.created_at),
        "status": approval_status(task.status),
    }


def approval_risk_level(task: TaskCenterTask) -> str:
    priority = (task.priority or "").strip().lower()
    if priority in HIGH_RISK_PRIORITIES:
        return "high"
    if task.status == "rejected":
        return "high"
    if task.status in {"result_submitted", "accepted"}:
        return "medium"
    return "normal"


def approval_recommendation(task: TaskCenterTask) -> str:
    if task.status == "created":
        return "建议老板确认目标是否需要拆解。"
    if task.status == "split":
        return "建议确认任务拆分后分配合适AI员工。"
    if task.status == "assigned":
        return "建议确认执行范围和风险边界后再进入执行。"
    if task.status == "result_submitted":
        return "建议交由天检验收执行结果。"
    if task.status == "accepted":
        return "建议交由天监完成安全审计。"
    if task.status == "rejected":
        return "建议老板确认返工方案和责任员工。"
    return "建议保持人工确认，不自动执行。"


def approval_status(status: str) -> str:
    mapping = {
        "created": "waiting_goal_confirm",
        "split": "waiting_dispatch_confirm",
        "assigned": "waiting_execution_confirm",
        "result_submitted": "waiting_acceptance",
        "accepted": "waiting_security_audit",
        "rejected": "waiting_rework_confirm",
    }
    return mapping.get(status, "waiting_boss_confirm")


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
