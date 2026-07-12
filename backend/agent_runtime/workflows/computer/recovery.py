from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import ComputerWorkflow, ComputerWorkflowRecovery


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_recovery(db: Session, workflow: ComputerWorkflow, *, step_id: str | None = None, recovery_type: str = "测试页面恢复", reason: str | None = None, result_summary: str | None = None, trace_id: str | None = None) -> ComputerWorkflowRecovery:
    row = ComputerWorkflowRecovery(
        recovery_id=uuid.uuid4().hex,
        workflow_id=workflow.workflow_id,
        step_id=step_id,
        recovery_type=recovery_type,
        status="已完成",
        reason=reason,
        result_summary=result_summary,
        trace_id=trace_id or workflow.trace_id,
        finished_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row
