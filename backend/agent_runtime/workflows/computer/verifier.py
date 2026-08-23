from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.agent_runtime.executors.computer.actions.models import ComputerActionPlan, ComputerActionTarget
from backend.agent_runtime.executors.computer.models import ComputerAction
from backend.task_center_ownership import SESSION_USER_KEY, owned_task_or_none

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
    plan_id: str,
    action_id: str,
    trace_id: str | None = None,
) -> ComputerWorkflowVerification:
    attempt_trace_id = trace_id or workflow.trace_id
    owner = db.info.get(SESSION_USER_KEY)
    if workflow.task_id is None or owner is None or owned_task_or_none(db, task_id=workflow.task_id, user=owner) is None:
        raise HTTPException(status_code=404, detail="工作流步骤验证不存在")
    plan = db.get(ComputerActionPlan, plan_id)
    action = db.get(ComputerAction, action_id)
    target = (
        db.query(ComputerActionTarget)
        .filter(
            ComputerActionTarget.plan_id == plan_id,
            ComputerActionTarget.action_id == action_id,
        )
        .one_or_none()
    )
    if not (
        plan is not None
        and action is not None
        and target is not None
        and step.workflow_id == workflow.workflow_id
        and step.action_id == action_id
        and workflow.session_id == plan.session_id == action.session_id
        and workflow.task_id == plan.task_id
        and plan.trace_id == attempt_trace_id
    ):
        raise HTTPException(status_code=409, detail="工作流步骤验证身份冲突")
    existing = (
        db.query(ComputerWorkflowVerification)
        .filter(
            ComputerWorkflowVerification.workflow_id == workflow.workflow_id,
            ComputerWorkflowVerification.step_id == step.step_id,
        )
        .one_or_none()
    )
    if existing is not None:
        if (
            step.verification_id == existing.verification_id
            and existing.verification_status == verification_status
            and existing.before_screenshot_reference == before_screenshot_reference
            and existing.after_screenshot_reference == after_screenshot_reference
            and existing.state_summary == state_summary
            and existing.result_summary == result_summary
            and existing.trace_id == attempt_trace_id
        ):
            return existing
        raise HTTPException(status_code=409, detail="工作流步骤验证身份冲突")
    row = ComputerWorkflowVerification(
        verification_id=uuid.uuid4().hex,
        workflow_id=workflow.workflow_id,
        step_id=step.step_id,
        verification_status=verification_status,
        before_screenshot_reference=before_screenshot_reference,
        after_screenshot_reference=after_screenshot_reference,
        state_summary=state_summary,
        result_summary=result_summary,
        trace_id=attempt_trace_id,
    )
    db.add(row)
    db.flush()
    step.verification_id = row.verification_id
    step.status = "已完成" if verification_status == "结果符合预期" else "已失败"
    step.finished_at = utcnow()
    return row
