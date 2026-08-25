from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def summarize_workflow_audit(workflow, steps, approvals, checkpoints, verifications, recoveries) -> list[dict]:
    events = [
        {"event": "WORKFLOW_PLAN_CREATED", "workflow_id": workflow.workflow_id, "step_count": len(steps)},
    ]
    if approvals:
        for approval in approvals:
            events.append({"event": f"WORKFLOW_SCOPE_{approval.approval_status}", "workflow_id": workflow.workflow_id, "approval_id": approval.approval_id})
    for checkpoint in checkpoints:
        events.append({"event": f"WORKFLOW_CHECKPOINT_{checkpoint.approval_status}", "workflow_id": workflow.workflow_id, "checkpoint_id": checkpoint.checkpoint_id})
    for step in steps:
        if step.status == "已完成":
            events.append({"event": "WORKFLOW_STEP_COMPLETED", "workflow_id": workflow.workflow_id, "step_id": step.step_id})
        elif step.status == "已失败":
            events.append({"event": "WORKFLOW_STEP_FAILED", "workflow_id": workflow.workflow_id, "step_id": step.step_id})
    for recovery in recoveries:
        events.append({"event": f"WORKFLOW_RECOVERY_{recovery.status}", "workflow_id": workflow.workflow_id, "recovery_id": recovery.recovery_id})
    events.append({"event": f"WORKFLOW_{workflow.status}", "workflow_id": workflow.workflow_id})
    return events
