from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import ComputerWorkflow, ComputerWorkflowApproval, ComputerWorkflowCheckpoint


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def create_scope_approval(db: Session, workflow: ComputerWorkflow, *, approved_by: int | None = None, approval_scope: str | None = None, trace_id: str | None = None) -> ComputerWorkflowApproval:
    row = ComputerWorkflowApproval(
        approval_id=uuid.uuid4().hex,
        workflow_id=workflow.workflow_id,
        approval_scope=approval_scope,
        approved_by=approved_by,
        approval_status="等待审批",
        trace_id=trace_id or workflow.trace_id,
    )
    db.add(row)
    db.flush()
    return row


def approve_scope_approval(db: Session, approval: ComputerWorkflowApproval, *, approved_by: int | None = None, trace_id: str | None = None) -> ComputerWorkflowApproval:
    if approval.approval_status == "已批准":
        raise HTTPException(status_code=409, detail="工作流审批已存在")
    if approval.approval_status not in {"等待审批", "已拒绝"}:
        raise HTTPException(status_code=409, detail="工作流审批状态不允许")
    approval.approval_status = "已批准"
    approval.approved_by = approved_by
    approval.approved_at = utcnow()
    approval.trace_id = trace_id or approval.trace_id
    db.flush()
    return approval


def reject_scope_approval(db: Session, approval: ComputerWorkflowApproval, *, approved_by: int | None = None, reason: str | None = None, trace_id: str | None = None) -> ComputerWorkflowApproval:
    approval.approval_status = "已拒绝"
    approval.approved_by = approved_by
    approval.reject_reason = reason
    approval.trace_id = trace_id or approval.trace_id
    db.flush()
    return approval


def create_checkpoint_approval(db: Session, workflow: ComputerWorkflow, *, step_id: str | None, checkpoint_type: str, reason: str | None, risk_level: str, screenshot_reference: str | None = None, state_summary: str | None = None, trace_id: str | None = None) -> ComputerWorkflowCheckpoint:
    row = ComputerWorkflowCheckpoint(
        checkpoint_id=uuid.uuid4().hex,
        workflow_id=workflow.workflow_id,
        step_id=step_id,
        checkpoint_type=checkpoint_type,
        reason=reason,
        screenshot_reference=screenshot_reference,
        state_summary=state_summary,
        risk_level=risk_level,
        approval_status="等待审批",
        trace_id=trace_id or workflow.trace_id,
    )
    db.add(row)
    db.flush()
    workflow.checkpoint_count = (workflow.checkpoint_count or 0) + 1
    workflow.status = "等待关键节点确认"
    return row


def approve_checkpoint(db: Session, checkpoint: ComputerWorkflowCheckpoint, *, approved_by: int | None = None, trace_id: str | None = None) -> ComputerWorkflowCheckpoint:
    if checkpoint.approval_status == "已批准":
        raise HTTPException(status_code=409, detail="关键节点已批准")
    checkpoint.approval_status = "已批准"
    checkpoint.approved_by = approved_by
    checkpoint.approved_at = utcnow()
    checkpoint.trace_id = trace_id or checkpoint.trace_id
    db.flush()
    return checkpoint


def reject_checkpoint(db: Session, checkpoint: ComputerWorkflowCheckpoint, *, approved_by: int | None = None, reason: str | None = None, trace_id: str | None = None) -> ComputerWorkflowCheckpoint:
    checkpoint.approval_status = "已拒绝"
    checkpoint.approved_by = approved_by
    checkpoint.approved_at = utcnow()
    checkpoint.reason = reason or checkpoint.reason
    checkpoint.trace_id = trace_id or checkpoint.trace_id
    db.flush()
    return checkpoint
