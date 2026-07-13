from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from .constants import ALPHA_WORKFLOW_EVENT_CODES
from .models import AlphaWorkflowEvent, AlphaWorkflowRun


_PARENT_UNSET = object()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def append_event(
    db: Session,
    run: AlphaWorkflowRun,
    *,
    event_code: str,
    stage: str,
    status: str,
    message: str | None = None,
    payload: dict | None = None,
    span_id: str | None = None,
    parent_span_id: str | None | object = _PARENT_UNSET,
    span_kind: str = "child",
) -> AlphaWorkflowEvent:
    resolved_parent_span_id = (
        run.root_span_id or run.trace_id
        if parent_span_id is _PARENT_UNSET
        else parent_span_id
    )
    event = AlphaWorkflowEvent(
        event_id=str(uuid4()),
        run_id=run.run_id,
        event_code=event_code if event_code in ALPHA_WORKFLOW_EVENT_CODES else event_code,
        stage=stage,
        status=status,
        message=message,
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
        span_id=span_id or f"{run.trace_id}:{stage}:{uuid4().hex[:8]}",
        parent_span_id=resolved_parent_span_id,
        span_kind=span_kind,
        trace_id=run.trace_id,
    )
    db.add(event)
    return event
