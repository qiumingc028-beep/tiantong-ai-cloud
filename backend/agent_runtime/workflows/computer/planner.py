from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import Session

from .constants import DEFAULT_MAX_STEPS
from .models import ComputerWorkflow, ComputerWorkflowStep
from .schemas import ComputerWorkflowCreatePayload
from .validator import validate_workflow_plan


def build_workflow_plan(db: Session, payload: ComputerWorkflowCreatePayload) -> tuple[ComputerWorkflow, list[ComputerWorkflowStep]]:
    steps_payload = [step.model_dump() for step in payload.steps]
    validate_workflow_plan(steps_payload)
    total_steps = payload.total_steps or len(steps_payload)
    if total_steps != len(steps_payload):
        total_steps = len(steps_payload)
    workflow = ComputerWorkflow(
        workflow_id=uuid.uuid4().hex,
        task_id=payload.task_id,
        employee_id=payload.employee_id,
        skill_id=payload.skill_id,
        device_id=payload.device_id,
        session_id=payload.session_id,
        goal=payload.goal,
        status="等待批准",
        risk_level=payload.risk_level,
        approval_status="等待审批",
        total_steps=total_steps,
        current_step=0,
        max_steps=min(max(payload.max_steps, 2), DEFAULT_MAX_STEPS),
        checkpoint_count=0,
        execution_budget_json=json.dumps(payload.execution_budget or {}, ensure_ascii=False),
        trace_id=payload.trace_id,
    )
    db.add(workflow)
    db.flush()
    steps: list[ComputerWorkflowStep] = []
    for index, step_payload in enumerate(steps_payload, start=1):
        step = ComputerWorkflowStep(
            step_id=uuid.uuid4().hex,
            workflow_id=workflow.workflow_id,
            sequence_number=index,
            action_type=step_payload["action_type"],
            target_application=step_payload.get("target_application"),
            target_bundle_id=step_payload.get("target_bundle_id"),
            target_window=step_payload.get("target_window"),
            target_control=step_payload.get("target_control"),
            input_summary=step_payload.get("input_summary"),
            expected_result=step_payload.get("expected_result"),
            risk_level=step_payload.get("risk_level") or workflow.risk_level,
            approval_required=bool(step_payload.get("approval_required")),
            checkpoint_required=bool(step_payload.get("checkpoint_required")),
            status="待执行",
            trace_id=step_payload.get("trace_id") or workflow.trace_id,
        )
        db.add(step)
        steps.append(step)
    db.flush()
    return workflow, steps
