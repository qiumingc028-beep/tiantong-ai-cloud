from __future__ import annotations

from sqlalchemy.orm import Session

from .models import BrainApprovalRecord, BrainExecutionRun
from .planner import approval_decision, write_execution_log
from .queue import enqueue_execution
from .state_machine import ExecutionState


def enqueue_approved_execution(db: Session, execution_id: int) -> dict:
    run = db.get(BrainExecutionRun, execution_id)
    if not run:
        return {"error": "execution_not_found"}

    approval = latest_approval(db, run.id)
    decision = approval_decision(
        run.risk_level,
        boss_confirm=bool(approval and approval.boss_confirmed),
        security_audited=bool(approval and approval.security_audited),
    )
    if decision["blocked"]:
        run.status = ExecutionState.WAIT_APPROVAL.value
        write_execution_log(db, run, action="queue_blocked", status="blocked", output_data={"approval": decision})
        db.commit()
        return {"execution_id": run.id, "status": "blocked", "queued": False, "approval": decision}

    item = enqueue_execution(run.id, task_id=run.task_id or f"brain-{run.id}", priority="normal")
    write_execution_log(db, run, action="queued_for_worker", status=ExecutionState.APPROVED.value, output_data={"queue_item": item})
    db.commit()
    return {"execution_id": run.id, "status": run.status, "queued": True, "queue_item": item}


def latest_approval(db: Session, execution_id: int) -> BrainApprovalRecord | None:
    return (
        db.query(BrainApprovalRecord)
        .filter(BrainApprovalRecord.execution_id == execution_id)
        .order_by(BrainApprovalRecord.id.desc())
        .first()
    )
