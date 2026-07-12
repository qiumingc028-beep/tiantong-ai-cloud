from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..database import get_db
from ..skills_engine.permissions import require_feature_enabled, require_skills_manage_user, require_skills_user
from ..agent_runtime.executors.computer.models import ComputerAction, ComputerEvidence, ComputerSession, ComputerTakeover
from ..agent_runtime.executors.computer.actions.models import ComputerActionApproval, ComputerActionPlan, ComputerActionTarget
from ..agent_runtime.executors.computer.runtime import ComputerRuntime
from ..agent_runtime.executors.computer.schemas import ComputerActionPayload, ComputerSessionCreatePayload
from ..agent_runtime.executors.computer.actions.schemas import ComputerActionPlanCreatePayload
from ..agent_runtime.executors.computer.actions.service import (
    approve_action,
    cancel_action,
    create_action_plan,
    get_action_plan,
    get_action_verification,
    preview_action_plan,
    reject_action,
    execute_action as execute_planned_action,
    health_check as safe_action_health_check,
)
from ..config import get_settings


router = APIRouter(prefix="/api/v2/computer")
health_router = APIRouter(prefix="/api/v2/computer-executor")


def _session_to_dict(session: ComputerSession) -> dict:
    return {
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


def _action_to_dict(action: ComputerAction) -> dict:
    return {
        "action_id": action.action_id,
        "session_id": action.session_id,
        "sequence_number": action.sequence_number,
        "action_type": action.action_type,
        "target_application": action.target_application,
        "target_window": action.target_window,
        "target_description": action.target_description,
        "input_summary": action.input_summary,
        "coordinates": json.loads(action.coordinates_json or "null"),
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
    }


def _evidence_to_dict(evidence: ComputerEvidence) -> dict:
    return {
        "evidence_id": evidence.evidence_id,
        "session_id": evidence.session_id,
        "action_id": evidence.action_id,
        "evidence_type": evidence.evidence_type,
        "reference": evidence.reference,
        "metadata": json.loads(evidence.metadata_json or "{}"),
        "created_at": evidence.created_at.isoformat() if evidence.created_at else None,
    }


@router.get("/sessions")
def list_sessions(request: Request, limit: int = 100, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_user(request, db)
    sessions = ComputerRuntime.list_sessions(db, limit=limit)
    summary = {
        "total": len(sessions),
        "running": sum(1 for row in sessions if row.status == "执行中"),
        "paused": sum(1 for row in sessions if row.status == "已暂停"),
        "handoff": sum(1 for row in sessions if row.takeover_status == "等待人工接管"),
        "completed": sum(1 for row in sessions if row.status == "已完成"),
        "failed": sum(1 for row in sessions if row.status == "已失败"),
    }
    return {"readonly": True, "summary": summary, "items": [_session_to_dict(row) for row in sessions]}


@router.post("/sessions")
def create_session(payload: ComputerSessionCreatePayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_manage_user(request, db)
    session = ComputerRuntime.create_session(db, payload)
    return {"ok": True, "session": _session_to_dict(session)}


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_user(request, db)
    session = ComputerRuntime.get_session(db, session_id)
    return {"readonly": True, "session": _session_to_dict(session)}


@router.post("/sessions/{session_id}/actions")
def execute_action(session_id: str, payload: ComputerActionPayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_manage_user(request, db)
    session = ComputerRuntime.get_session(db, session_id)
    return ComputerRuntime.execute_action(db, session, payload)


@router.post("/sessions/{session_id}/pause")
def pause_session(session_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_manage_user(request, db)
    session = ComputerRuntime.get_session(db, session_id)
    return {"ok": True, "session": _session_to_dict(ComputerRuntime.pause(db, session))}


@router.post("/sessions/{session_id}/resume")
def resume_session(session_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_manage_user(request, db)
    session = ComputerRuntime.get_session(db, session_id)
    return {"ok": True, "session": _session_to_dict(ComputerRuntime.resume(db, session))}


@router.post("/sessions/{session_id}/cancel")
def cancel_session(session_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_manage_user(request, db)
    session = ComputerRuntime.get_session(db, session_id)
    return {"ok": True, "session": _session_to_dict(ComputerRuntime.cancel(db, session))}


@router.post("/sessions/{session_id}/handoff")
def handoff_session(session_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    user = require_skills_manage_user(request, db)
    session = ComputerRuntime.get_session(db, session_id)
    body = request.query_params.get("reason") or None
    return {"ok": True, "session": _session_to_dict(ComputerRuntime.handoff_to_human(db, session, requested_by=user.username, reason=body))}


@router.post("/sessions/{session_id}/close")
def close_session(session_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_manage_user(request, db)
    session = ComputerRuntime.get_session(db, session_id)
    return {"ok": True, "session": _session_to_dict(ComputerRuntime.close_session(db, session))}


@router.get("/sessions/{session_id}/actions")
def list_actions(session_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_user(request, db)
    session = ComputerRuntime.get_session(db, session_id)
    return {"readonly": True, "session_id": session.session_id, "items": [_action_to_dict(row) for row in session.actions]}


@router.get("/sessions/{session_id}/window-state")
def get_window_state(session_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_user(request, db)
    session = ComputerRuntime.get_session(db, session_id)
    return {"readonly": True, "session_id": session.session_id, "window_state": ComputerRuntime.get_window_state(db, session)}


@router.post("/sessions/{session_id}/capture")
def capture_screen(session_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_manage_user(request, db)
    session = ComputerRuntime.get_session(db, session_id)
    evidence = ComputerRuntime.capture_screen(db, session)
    return {"ok": True, "evidence": _evidence_to_dict(evidence)}


@router.post("/action-plans")
def create_plan(payload: ComputerActionPlanCreatePayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_ACTION_ENABLED")
    require_skills_manage_user(request, db)
    result = create_action_plan(db, payload)
    return {"ok": True, **result}


@router.get("/action-plans/{plan_id}")
def get_plan(plan_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_user(request, db)
    return {"readonly": True, **get_action_plan(db, plan_id)}


@router.post("/action-plans/{plan_id}/preview")
def preview_plan(plan_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_manage_user(request, db)
    current_hash = request.query_params.get("current_screenshot_hash")
    return {"readonly": True, **preview_action_plan(db, plan_id, current_screenshot_hash=current_hash)}


@router.post("/actions/{action_id}/approve")
def approve_plan_action(action_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("PER_ACTION_APPROVAL_ENABLED")
    user = require_skills_manage_user(request, db)
    target = db.query(ComputerActionTarget).filter(ComputerActionTarget.action_id == action_id).one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="动作不存在")
    return {"ok": True, **approve_action(db, plan_id=target.plan_id, approved_by=user.id, approval_scope=request.query_params.get("scope"), trace_id=request.query_params.get("trace_id"), current_screenshot_hash=request.query_params.get("current_screenshot_hash"))}


@router.post("/actions/{action_id}/reject")
def reject_plan_action(action_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    user = require_skills_manage_user(request, db)
    target = db.query(ComputerActionTarget).filter(ComputerActionTarget.action_id == action_id).one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="动作不存在")
    return {"ok": True, **reject_action(db, plan_id=target.plan_id, approved_by=user.id, reason=request.query_params.get("reason"), trace_id=request.query_params.get("trace_id"))}


@router.post("/actions/{action_id}/execute")
def execute_plan_action(action_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_ACTION_ENABLED")
    user = require_skills_manage_user(request, db)
    target = db.query(ComputerActionTarget).filter(ComputerActionTarget.action_id == action_id).one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="动作不存在")
    return {"ok": True, **execute_planned_action(
        db,
        plan_id=target.plan_id,
        current_application=request.query_params.get("current_application"),
        current_window=request.query_params.get("current_window"),
        current_screenshot_hash=request.query_params.get("current_screenshot_hash"),
        trace_id=request.query_params.get("trace_id"),
    )}


@router.post("/actions/{action_id}/cancel")
def cancel_plan_action(action_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    user = require_skills_manage_user(request, db)
    target = db.query(ComputerActionTarget).filter(ComputerActionTarget.action_id == action_id).one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="动作不存在")
    return {"ok": True, **cancel_action(db, plan_id=target.plan_id, reason=request.query_params.get("reason"), trace_id=request.query_params.get("trace_id"))}


@router.get("/actions/{action_id}/verification")
def get_plan_action_verification(action_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_user(request, db)
    target = db.query(ComputerActionTarget).filter(ComputerActionTarget.action_id == action_id).one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="动作不存在")
    return {"readonly": True, **get_action_verification(db, target.plan_id)}



@router.get("/sessions/{session_id}/evidence")
def list_evidence(session_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_skills_user(request, db)
    rows = db.query(ComputerEvidence).filter(ComputerEvidence.session_id == session_id).order_by(ComputerEvidence.created_at.asc()).all()
    return {"readonly": True, "session_id": session_id, "items": [_evidence_to_dict(row) for row in rows]}


@health_router.get("/health")
@router.get("/health")
def health(request: Request, db: Session = Depends(get_db)):
    require_skills_user(request, db)
    settings = get_settings()
    payload = {
        "status": "healthy",
        "feature_flags": {
            "OPENCLAW_ADAPTER_ENABLED": settings.OPENCLAW_ADAPTER_ENABLED,
            "COMPUTER_EXECUTOR_ENABLED": settings.COMPUTER_EXECUTOR_ENABLED,
            "ISOLATED_DESKTOP_ENABLED": settings.ISOLATED_DESKTOP_ENABLED,
            "SCREEN_CAPTURE_ENABLED": settings.SCREEN_CAPTURE_ENABLED,
            "HUMAN_TAKEOVER_ENABLED": settings.HUMAN_TAKEOVER_ENABLED,
            "COMPUTER_TEXT_INPUT_ENABLED": settings.COMPUTER_TEXT_INPUT_ENABLED,
            "COMPUTER_MOUSE_INPUT_ENABLED": settings.COMPUTER_MOUSE_INPUT_ENABLED,
            "COMPUTER_CONTROL_ENABLED": settings.COMPUTER_CONTROL_ENABLED,
            "SHELL_EXECUTION_ENABLED": settings.SHELL_EXECUTION_ENABLED,
            "MAC_SAFE_ACTION_ENABLED": settings.MAC_SAFE_ACTION_ENABLED,
            "MAC_SAFE_MOUSE_MOVE_ENABLED": settings.MAC_SAFE_MOUSE_MOVE_ENABLED,
            "MAC_SAFE_CLICK_ENABLED": settings.MAC_SAFE_CLICK_ENABLED,
            "MAC_SAFE_TEXT_INPUT_ENABLED": settings.MAC_SAFE_TEXT_INPUT_ENABLED,
            "PER_ACTION_APPROVAL_ENABLED": settings.PER_ACTION_APPROVAL_ENABLED,
            "POST_ACTION_VERIFICATION_ENABLED": settings.POST_ACTION_VERIFICATION_ENABLED,
            "CLIPBOARD_READ_ENABLED": settings.CLIPBOARD_READ_ENABLED,
            "CLIPBOARD_WRITE_ENABLED": settings.CLIPBOARD_WRITE_ENABLED,
            "FILE_UPLOAD_ENABLED": settings.FILE_UPLOAD_ENABLED,
            "FILE_DOWNLOAD_ENABLED": settings.FILE_DOWNLOAD_ENABLED,
        },
        "summary": {
            "sessions": db.query(ComputerSession).count(),
            "actions": db.query(ComputerAction).count(),
            "evidence": db.query(ComputerEvidence).count(),
        },
    }
    payload["safe_action"] = safe_action_health_check(db)
    return payload


@router.get("/action-policy/health")
def action_policy_health(request: Request, db: Session = Depends(get_db)):
    require_skills_user(request, db)
    return safe_action_health_check(db)
