from __future__ import annotations

import json
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ....config import get_settings
from ....models import AiEmployee
from ...runtime import invoke_agent_runtime
from .action_validator import validate_action_payload
from .base import ComputerExecutorOutcome
from .evidence import json_text, make_evidence_reference, make_screenshot_reference, utcnow
from .mock_executor import MockComputerExecutor
from .openclaw_adapter import OpenClawAdapter
from .policy import ensure_executor_enabled, ensure_screen_capture_enabled, ensure_human_takeover_enabled, detect_sensitive_region
from .schemas import ComputerActionPayload, ComputerSessionCreatePayload
from .session import add_action_row, add_evidence_row, add_policy_event, create_session_row, get_session, list_sessions, request_takeover, update_session_status
from .models import ComputerSession


def _executor_for_settings():
    settings = get_settings()
    if settings.OPENCLAW_ADAPTER_ENABLED:
        return OpenClawAdapter()
    return MockComputerExecutor()


class ComputerRuntime:
    @staticmethod
    def create_session(db: Session, payload: ComputerSessionCreatePayload):
        ensure_executor_enabled()
        session_id = uuid.uuid4().hex
        session = create_session_row(db, session_id=session_id, payload=payload)
        db.commit()
        db.refresh(session)
        return session

    @staticmethod
    def list_sessions(db: Session, limit: int = 100):
        return list_sessions(db, limit=limit)

    @staticmethod
    def get_session(db: Session, session_id: str) -> ComputerSession:
        session = get_session(db, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="电脑会话不存在")
        return session

    @staticmethod
    def execute_action(db: Session, session: ComputerSession, payload: ComputerActionPayload):
        ensure_executor_enabled()
        ensure_screen_capture_enabled()
        validate_action_payload(payload)
        executor = _executor_for_settings()
        context = type("Context", (), {
            "session_id": session.session_id,
            "trace_id": payload.trace_id or session.trace_id,
            "action_type": payload.action_type,
            "target_application": payload.target_application,
            "target_window": payload.target_window,
            "text_input": payload.text_input,
            "coordinates": payload.coordinates,
        })()
        started = utcnow()
        response = executor.execute_action(context)
        finished = utcnow()
        action = add_action_row(
            db,
            session=session,
            payload=payload,
            result={
                "action_id": uuid.uuid4().hex,
                "result": json_text(response.action_result if isinstance(response, ComputerExecutorOutcome) else response),
                "risk_level": session.risk_level,
                "started_at": started,
                "finished_at": finished,
                "duration_ms": response.duration_ms if isinstance(response, ComputerExecutorOutcome) else 0,
            },
            screenshot_before=make_screenshot_reference(session.session_id, f"before-{payload.trace_id or 'action'}"),
            screenshot_after=response.screenshot_reference if isinstance(response, ComputerExecutorOutcome) else None,
            approval_required=session.approval_status == "等待审批",
            approval_status=session.approval_status,
        )
        evidence = add_evidence_row(
            db,
            session_id=session.session_id,
            action_id=action.action_id,
            evidence_type="screenshot",
            reference=make_evidence_reference(session.session_id, action.action_id, "action_screenshot"),
            metadata={"action_type": payload.action_type, "target_application": payload.target_application, "target_window": payload.target_window},
        )
        add_policy_event(
            db,
            session_id=session.session_id,
            action_id=action.action_id,
            event_code="ACTION_EXECUTED",
            event_message="电脑动作已执行",
            risk_level=session.risk_level,
            sensitive_data_involved=detect_sensitive_region(payload.target_window, payload.target_application, payload.text_input),
            trace_id=payload.trace_id,
        )
        session.status = "执行中"
        session.last_screenshot_at = finished
        db.commit()
        db.refresh(session)
        session_dict = {
            "session_id": session.session_id,
            "execution_id": session.execution_id,
            "task_id": session.task_id,
            "employee_id": session.employee_id,
            "skill_id": session.skill_id,
            "executor_type": session.executor_type,
            "environment_type": session.environment_type,
            "status": session.status,
            "risk_level": session.risk_level,
            "approval_status": session.approval_status,
            "allowed_applications": json.loads(session.allowed_applications_json or "[]"),
            "allowed_windows": json.loads(session.allowed_windows_json or "[]"),
            "started_at": session.started_at.isoformat() if session.started_at else None,
            "expires_at": session.expires_at.isoformat() if session.expires_at else None,
            "ended_at": session.ended_at.isoformat() if session.ended_at else None,
            "takeover_status": session.takeover_status,
            "last_screenshot_at": session.last_screenshot_at.isoformat() if session.last_screenshot_at else None,
            "trace_id": session.trace_id,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        }
        return {
            "session": session_dict,
            "action": {
                "action_id": action.action_id,
                "session_id": session.session_id,
                "sequence_number": action.sequence_number,
                "action_type": action.action_type,
                "target_application": action.target_application,
                "target_window": action.target_window,
                "target_description": action.target_description,
                "input_summary": action.input_summary,
                "coordinates": json.loads(action.coordinates_json) if action.coordinates_json else None,
                "risk_level": action.risk_level,
                "approval_required": action.approval_required,
                "approval_status": action.approval_status,
                "screenshot_before": action.screenshot_before,
                "screenshot_after": action.screenshot_after,
                "result": action.result,
                "error_code": action.error_code,
                "error_message": action.error_message,
                "started_at": action.started_at.isoformat() if action.started_at else None,
                "finished_at": action.finished_at.isoformat() if action.finished_at else None,
                "duration_ms": action.duration_ms,
                "trace_id": action.trace_id,
            },
            "evidence": {"evidence_id": evidence.evidence_id, "reference": evidence.reference},
        }

    @staticmethod
    def capture_screen(db: Session, session: ComputerSession):
        ensure_executor_enabled()
        ensure_screen_capture_enabled()
        executor = _executor_for_settings()
        context = type("Context", (), {"session_id": session.session_id, "trace_id": session.trace_id})()
        payload = executor.capture_screen(context)
        ref = payload["screenshot_reference"]
        evidence = add_evidence_row(db, session_id=session.session_id, action_id=None, evidence_type="screenshot", reference=ref, metadata={"kind": "screen"})
        session.last_screenshot_at = utcnow()
        db.commit()
        return evidence

    @staticmethod
    def get_window_state(db: Session, session: ComputerSession):
        executor = _executor_for_settings()
        context = type("Context", (), {"session_id": session.session_id, "trace_id": session.trace_id, "target_application": None, "target_window": None})()
        return executor.get_window_state(context)

    @staticmethod
    def pause(db: Session, session: ComputerSession):
        session.status = "已暂停"
        db.commit()
        return session

    @staticmethod
    def resume(db: Session, session: ComputerSession):
        session.status = "执行中"
        db.commit()
        return session

    @staticmethod
    def cancel(db: Session, session: ComputerSession):
        session.status = "已取消"
        session.ended_at = utcnow()
        db.commit()
        return session

    @staticmethod
    def handoff_to_human(db: Session, session: ComputerSession, requested_by: str | None = None, reason: str | None = None):
        ensure_human_takeover_enabled()
        request_takeover(db, session, requested_by=requested_by, reason=reason)
        db.refresh(session)
        return session

    @staticmethod
    def close_session(db: Session, session: ComputerSession):
        session.status = "已关闭"
        session.ended_at = utcnow()
        db.commit()
        return session
