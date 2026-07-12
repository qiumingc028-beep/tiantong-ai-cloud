from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from .evidence import utcnow
from .models import ComputerAction, ComputerEvidence, ComputerPolicyEvent, ComputerSession, ComputerTakeover


def list_sessions(db: Session, limit: int = 100):
    return db.query(ComputerSession).order_by(ComputerSession.created_at.desc()).limit(limit).all()


def get_session(db: Session, session_id: str) -> ComputerSession | None:
    return db.get(ComputerSession, session_id)


def create_session_row(db: Session, *, session_id: str, payload):
    row = ComputerSession(
        session_id=session_id,
        execution_id=payload.execution_id,
        task_id=payload.task_id,
        employee_id=payload.employee_id,
        skill_id=payload.skill_id,
        executor_type=payload.executor_type,
        environment_type=payload.environment_type,
        status="已创建",
        risk_level=payload.risk_level,
        approval_status=payload.approval_status,
        allowed_applications_json=json.dumps(payload.allowed_applications, ensure_ascii=False),
        allowed_windows_json=json.dumps(payload.allowed_windows, ensure_ascii=False),
        started_at=utcnow(),
        expires_at=utcnow() + timedelta(minutes=30),
        takeover_status="未接管",
        trace_id=payload.trace_id,
    )
    db.add(row)
    db.flush()
    return row


def update_session_status(db: Session, session: ComputerSession, *, status: str | None = None, takeover_status: str | None = None, ended: bool = False):
    if status:
        session.status = status
    if takeover_status:
        session.takeover_status = takeover_status
    if ended:
        session.ended_at = utcnow()
    db.commit()
    db.refresh(session)
    return session


def add_action_row(db: Session, *, session: ComputerSession, payload, result: dict, screenshot_before: str | None = None, screenshot_after: str | None = None, approval_required: bool = False, approval_status: str = "无需审批", error_code: str | None = None, error_message: str | None = None):
    seq = len(session.actions) + 1
    row = ComputerAction(
        action_id=result.get("action_id") or f"{session.session_id}-{seq}",
        session_id=session.session_id,
        sequence_number=seq,
        action_type=payload.action_type,
        target_application=payload.target_application,
        target_window=payload.target_window,
        target_description=payload.target_description,
        input_summary=(payload.text_input[:128] if payload.text_input else None),
        coordinates_json=json.dumps(payload.coordinates, ensure_ascii=False) if payload.coordinates else None,
        risk_level=result.get("risk_level", "低风险"),
        approval_required=approval_required,
        approval_status=approval_status,
        screenshot_before=screenshot_before,
        screenshot_after=screenshot_after,
        result=result.get("result"),
        error_code=error_code,
        error_message=error_message,
        started_at=result.get("started_at"),
        finished_at=result.get("finished_at"),
        duration_ms=result.get("duration_ms"),
        trace_id=payload.trace_id,
    )
    db.add(row)
    db.flush()
    return row


def add_evidence_row(db: Session, *, session_id: str, action_id: str | None, evidence_type: str, reference: str, metadata: dict | None = None):
    row = ComputerEvidence(
        evidence_id=f"{session_id}-{action_id or 'session'}-{evidence_type}",
        session_id=session_id,
        action_id=action_id,
        evidence_type=evidence_type,
        reference=reference,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        created_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def add_policy_event(db: Session, *, session_id: str | None, action_id: str | None, event_code: str, event_message: str | None, risk_level: str, sensitive_data_involved: bool = False, trace_id: str | None = None):
    row = ComputerPolicyEvent(
        event_id=f"{session_id or 'global'}-{action_id or 'policy'}-{event_code}",
        session_id=session_id,
        action_id=action_id,
        event_code=event_code,
        event_message=event_message,
        risk_level=risk_level,
        sensitive_data_involved=sensitive_data_involved,
        trace_id=trace_id,
        created_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def request_takeover(db: Session, session: ComputerSession, *, requested_by: str | None, reason: str | None):
    takeover = ComputerTakeover(
        takeover_id=f"{session.session_id}-takeover",
        session_id=session.session_id,
        requested_by=requested_by,
        requested_reason=reason,
        approval_status="等待审批",
        status="等待接管",
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.takeover_status = "等待人工接管"
    db.add(takeover)
    db.commit()
    db.refresh(session)
    return takeover
