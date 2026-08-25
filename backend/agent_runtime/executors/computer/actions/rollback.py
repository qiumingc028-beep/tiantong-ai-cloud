from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import ComputerActionPlan, ComputerActionApproval


def cancel_plan(db: Session, plan: ComputerActionPlan, *, reason: str | None = None):
    plan.status = "已取消"
    for approval in plan.approvals:
        approval.approval_status = "已拒绝"
        approval.reject_reason = reason or "已取消"
    db.commit()
    db.refresh(plan)
    return plan


def expire_if_window_changed(approval: ComputerActionApproval, *, current_window_hash: str | None):
    if approval.before_screenshot_hash and current_window_hash and current_window_hash != approval.before_screenshot_hash:
        approval.approval_status = "已过期"
        raise HTTPException(status_code=409, detail="窗口变化导致审批失效")
    return approval
