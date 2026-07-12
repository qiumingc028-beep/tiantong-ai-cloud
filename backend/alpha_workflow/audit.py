from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from .constants import ALPHA_WORKFLOW_EVENT_CODES
from .models import AlphaWorkflowEvent, AlphaWorkflowRun


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
) -> AlphaWorkflowEvent:
    event = AlphaWorkflowEvent(
        event_id=str(uuid4()),
        run_id=run.run_id,
        event_code=event_code if event_code in ALPHA_WORKFLOW_EVENT_CODES else event_code,
        stage=stage,
        status=status,
        message=message,
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
        trace_id=run.trace_id,
    )
    db.add(event)
    return event
