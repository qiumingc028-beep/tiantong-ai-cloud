from __future__ import annotations

from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from ..tool_center.gateway import clean_text
from .models import BrainExecutionEvent, BrainExecutionRun


class ExecutionState(str, Enum):
    CREATED = "CREATED"
    ANALYZED = "ANALYZED"
    PLANNED = "PLANNED"
    WAIT_APPROVAL = "WAIT_APPROVAL"
    APPROVED = "APPROVED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REVIEWED = "REVIEWED"


ALLOWED_TRANSITIONS: dict[ExecutionState, set[ExecutionState]] = {
    ExecutionState.CREATED: {ExecutionState.ANALYZED, ExecutionState.FAILED},
    ExecutionState.ANALYZED: {ExecutionState.PLANNED, ExecutionState.WAIT_APPROVAL, ExecutionState.FAILED},
    ExecutionState.PLANNED: {ExecutionState.WAIT_APPROVAL, ExecutionState.APPROVED, ExecutionState.RUNNING, ExecutionState.FAILED},
    ExecutionState.WAIT_APPROVAL: {ExecutionState.PLANNED, ExecutionState.APPROVED, ExecutionState.FAILED},
    ExecutionState.APPROVED: {ExecutionState.RUNNING, ExecutionState.FAILED},
    ExecutionState.RUNNING: {ExecutionState.SUCCESS, ExecutionState.FAILED},
    ExecutionState.SUCCESS: {ExecutionState.REVIEWED},
    ExecutionState.FAILED: {ExecutionState.REVIEWED},
    ExecutionState.REVIEWED: set(),
}


def normalize_state(value: str | None) -> ExecutionState:
    clean = clean_text(value or ExecutionState.CREATED.value).upper()
    legacy = {
        "PLANNED": ExecutionState.PLANNED,
        "BLOCKED": ExecutionState.WAIT_APPROVAL,
        "APPROVED": ExecutionState.APPROVED,
        "RUNNING": ExecutionState.RUNNING,
        "COMPLETED": ExecutionState.SUCCESS,
    }
    if clean in legacy:
        return legacy[clean]
    try:
        return ExecutionState(clean)
    except ValueError:
        return ExecutionState.CREATED


def transition_run(
    db: Session,
    run: BrainExecutionRun,
    target: ExecutionState,
    *,
    event_type: str | None = None,
    event_data: dict[str, Any] | None = None,
) -> BrainExecutionEvent:
    current = normalize_state(run.status)
    if target != current and target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid brain execution transition: {current.value} -> {target.value}")
    run.status = target.value
    event = BrainExecutionEvent(
        execution_id=run.id,
        event_type=event_type or f"state_{target.value.lower()}",
        event_data=event_data_to_json(event_data or {"from": current.value, "to": target.value}),
    )
    db.add(event)
    return event


def event_data_to_json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)[:8000]
