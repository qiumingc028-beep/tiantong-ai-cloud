from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .constants import ACTION_APPROVAL_STATUSES
from .models import ComputerActionApproval, ComputerActionPlan, ComputerActionTarget


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def create_approval_row(db: Session, plan: ComputerActionPlan, target: ComputerActionTarget, *, approved_by: int | None, approval_scope: str | None, trace_id: str | None):
    approval = ComputerActionApproval(
        approval_id=uuid4().hex,
        plan_id=plan.plan_id,
        action_id=target.action_id,
        approved_by=approved_by,
        approval_status="等待审批",
        approval_scope=approval_scope,
        before_screenshot_hash=target.screenshot_before_hash,
        approved_at=None,
        expires_at=utcnow() + timedelta(minutes=10),
        reject_reason=None,
        trace_id=trace_id,
    )
    db.add(approval)
    db.flush()
    return approval


def approve_action_row(db: Session, approval: ComputerActionApproval, *, approved_by: int | None, trace_id: str | None):
    if approval.approval_status == "已批准":
        raise HTTPException(status_code=409, detail="审批已使用，不能重复批准")
    if _normalize_dt(approval.expires_at) and _normalize_dt(approval.expires_at) < utcnow():
        approval.approval_status = "已过期"
        db.commit()
        raise HTTPException(status_code=409, detail="审批已过期")
    approval.approval_status = "已批准"
    approval.approved_by = approved_by
    approval.approved_at = utcnow()
    approval.trace_id = trace_id or approval.trace_id
    db.commit()
    db.refresh(approval)
    return approval


def reject_action_row(db: Session, approval: ComputerActionApproval, *, approved_by: int | None, reason: str | None, trace_id: str | None):
    approval.approval_status = "已拒绝"
    approval.approved_by = approved_by
    approval.reject_reason = reason
    approval.approved_at = utcnow()
    approval.trace_id = trace_id or approval.trace_id
    db.commit()
    db.refresh(approval)
    return approval


def ensure_action_approved(approval: ComputerActionApproval, *, current_window_hash: str | None = None):
    if approval.approval_status != "已批准":
        raise HTTPException(status_code=403, detail="动作尚未批准")
    if _normalize_dt(approval.expires_at) and _normalize_dt(approval.expires_at) < utcnow():
        approval.approval_status = "已过期"
        raise HTTPException(status_code=409, detail="审批已过期")
    if current_window_hash and approval.before_screenshot_hash and current_window_hash != approval.before_screenshot_hash:
        approval.approval_status = "已过期"
        raise HTTPException(status_code=409, detail="窗口已变化，审批失效")
    return True
