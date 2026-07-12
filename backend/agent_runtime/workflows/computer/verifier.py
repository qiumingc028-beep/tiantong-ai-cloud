from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import ComputerWorkflow, ComputerWorkflowStep, ComputerWorkflowVerification


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def verify_step_result(
    db: Session,
    workflow: ComputerWorkflow,
    step: ComputerWorkflowStep,
    *,
    before_screenshot_reference: str | None,
    after_screenshot_reference: str | None,
    state_summary: str | None,
    result_summary: str | None,
    verification_status: str,
    trace_id: str | None = None,
) -> ComputerWorkflowVerification:
    row = ComputerWorkflowVerification(
        verification_id=uuid.uuid4().hex,
        workflow_id=workflow.workflow_id,
        step_id=step.step_id,
        verification_status=verification_status,
        before_screenshot_reference=before_screenshot_reference,
        after_screenshot_reference=after_screenshot_reference,
        state_summary=state_summary,
        result_summary=result_summary,
        trace_id=trace_id or workflow.trace_id,
    )
    db.add(row)
    db.flush()
    step.verification_id = row.verification_id
    step.status = "已完成" if verification_status == "结果符合预期" else "已失败"
    step.finished_at = utcnow()
    return row
