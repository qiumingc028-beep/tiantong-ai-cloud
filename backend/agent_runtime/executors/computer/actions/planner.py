from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from .models import ComputerActionPlan, ComputerActionTarget
from .schemas import ComputerActionPlanCreatePayload


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_proposed_actions(payload: ComputerActionPlanCreatePayload) -> list[dict]:
    action_id = uuid.uuid4().hex
    return [
        {
            "action_id": action_id,
            "action_type": payload.action_type,
            "target_application": payload.target_application,
            "target_bundle_id": payload.target_bundle_id,
            "target_window": payload.target_window,
            "control_type": payload.control_type,
            "control_label": payload.control_label,
            "control_identifier": payload.control_identifier,
            "target_description": payload.target_description or payload.goal,
            "coordinates": payload.coordinates,
            "text_input": payload.text_input,
            "approval_mode": payload.approval_mode,
        }
    ]


def create_action_plan_row(db: Session, payload: ComputerActionPlanCreatePayload) -> tuple[ComputerActionPlan, ComputerActionTarget]:
    proposed_actions = build_proposed_actions(payload)
    plan_id = uuid.uuid4().hex
    action = proposed_actions[0]
    plan = ComputerActionPlan(
        plan_id=plan_id,
        session_id=payload.session_id,
        observation_id=payload.observation_id,
        task_id=payload.task_id,
        employee_id=payload.employee_id,
        skill_id=payload.skill_id,
        target_application=payload.target_application,
        target_bundle_id=payload.target_bundle_id,
        target_window=payload.target_window,
        goal=payload.goal,
        proposed_actions_json=json.dumps(proposed_actions, ensure_ascii=False),
        current_action_index=0,
        max_actions=max(1, int(payload.max_actions or 1)),
        risk_level=payload.risk_level,
        approval_mode=payload.approval_mode,
        status="草稿",
        expires_at=utcnow() + timedelta(minutes=30),
        trace_id=payload.trace_id,
    )
    target = ComputerActionTarget(
        target_id=uuid.uuid4().hex,
        plan_id=plan_id,
        action_id=action["action_id"],
        action_type=payload.action_type,
        control_type=payload.control_type,
        control_label=payload.control_label,
        control_identifier=payload.control_identifier,
        target_description=payload.target_description or payload.goal,
        expected_window=payload.target_window,
        expected_application=payload.target_application,
        coordinates_json=json.dumps(payload.coordinates, ensure_ascii=False) if payload.coordinates else None,
        input_text_summary=(payload.text_input[:80] if payload.text_input else None),
        status="待校验",
    )
    db.add(plan)
    db.add(target)
    db.flush()
    return plan, target
