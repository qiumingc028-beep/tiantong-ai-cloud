from __future__ import annotations

import json
import uuid
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
    action_id = result.get("action_id") or f"{session.session_id}-{len(session.actions) + 1}"
    row = db.get(ComputerAction, action_id)
    if row is None:
        row = ComputerAction(
            action_id=action_id,
            session_id=session.session_id,
            sequence_number=len(session.actions) + 1,
        )
        db.add(row)
    elif row.session_id != session.session_id:
        raise ValueError("电脑动作不属于当前会话")
    row.action_type = payload.action_type
    row.target_application = payload.target_application
    row.target_window = payload.target_window
    row.target_description = payload.target_description
    row.input_summary = payload.text_input[:128] if payload.text_input else None
    row.coordinates_json = json.dumps(payload.coordinates, ensure_ascii=False) if payload.coordinates else None
    row.risk_level = result.get("risk_level", "低风险")
    row.approval_required = approval_required
    row.approval_status = approval_status
    row.screenshot_before = screenshot_before
    row.screenshot_after = screenshot_after
    row.result = result.get("result")
    row.error_code = error_code
    row.error_message = error_message
    row.started_at = result.get("started_at")
    row.finished_at = result.get("finished_at")
    row.duration_ms = result.get("duration_ms")
    row.trace_id = payload.trace_id
    db.flush()
    return row


def add_evidence_row(db: Session, *, session_id: str, action_id: str | None, evidence_type: str, reference: str, metadata: dict | None = None):
    evidence_identity = json.dumps(
        ["computer_evidence", session_id, action_id, evidence_type, reference],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    row = ComputerEvidence(
        evidence_id=str(uuid.uuid5(uuid.NAMESPACE_URL, evidence_identity)),
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
    event_identity = json.dumps(["computer_policy_event", session_id, action_id, event_code], ensure_ascii=False, separators=(",", ":"))
    row = ComputerPolicyEvent(
        event_id=str(uuid.uuid5(uuid.NAMESPACE_URL, event_identity)),
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
