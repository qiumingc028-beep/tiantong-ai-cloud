from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..schemas import ComputerActionPayload, ComputerSessionCreatePayload
from ..runtime import ComputerRuntime
from ..session import add_policy_event, get_session
from ..evidence import utcnow
from ..policy import detect_sensitive_region
from .policy import (
    ensure_action_type_allowed,
    ensure_click_enabled,
    ensure_clipboard_disabled,
    ensure_coordinates_safe,
    ensure_file_transfer_disabled,
    ensure_move_enabled,
    ensure_per_action_approval_enabled,
    ensure_post_action_verification_enabled,
    ensure_safe_action_enabled,
    ensure_target_application_allowed,
    ensure_target_control_allowed,
    ensure_text_input_enabled,
    ensure_text_safe,
)
from .approval import _normalize_dt, approve_action_row, create_approval_row, ensure_action_approved, reject_action_row
from .constants import ACTION_APPROVAL_STATUSES, ACTION_PLAN_STATUSES, ACTION_VERIFICATION_STATUSES
from .models import ComputerActionApproval, ComputerActionPlan, ComputerActionTarget, ComputerActionVerification
from .schemas import ComputerActionPlanCreatePayload
from .planner import build_proposed_actions, create_action_plan_row
from .preview import preview_payload
from .rollback import cancel_plan
from .target_resolver import resolve_target
from .verifier import verify_action_result


def _plan_to_dict(plan: ComputerActionPlan) -> dict:
    return {
        "plan_id": plan.plan_id,
        "session_id": plan.session_id,
        "observation_id": plan.observation_id,
        "task_id": plan.task_id,
        "employee_id": plan.employee_id,
        "skill_id": plan.skill_id,
        "target_application": plan.target_application,
        "target_bundle_id": plan.target_bundle_id,
        "target_window": plan.target_window,
        "goal": plan.goal,
        "proposed_actions": json.loads(plan.proposed_actions_json or "[]"),
        "current_action_index": plan.current_action_index,
        "max_actions": plan.max_actions,
        "risk_level": plan.risk_level,
        "approval_mode": plan.approval_mode,
        "status": plan.status,
        "expires_at": plan.expires_at.isoformat() if plan.expires_at else None,
        "trace_id": plan.trace_id,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }


def _target_to_dict(target: ComputerActionTarget) -> dict:
    return {
        "target_id": target.target_id,
        "plan_id": target.plan_id,
        "action_id": target.action_id,
        "action_type": target.action_type,
        "control_type": target.control_type,
        "control_label": target.control_label,
        "control_identifier": target.control_identifier,
        "target_description": target.target_description,
        "expected_window": target.expected_window,
        "expected_application": target.expected_application,
        "coordinates": json.loads(target.coordinates_json) if target.coordinates_json else None,
        "input_text_summary": target.input_text_summary,
        "screenshot_before_reference": target.screenshot_before_reference,
        "screenshot_before_hash": target.screenshot_before_hash,
        "status": target.status,
        "created_at": target.created_at.isoformat() if target.created_at else None,
        "updated_at": target.updated_at.isoformat() if target.updated_at else None,
    }


def _approval_to_dict(approval: ComputerActionApproval) -> dict:
    return {
        "approval_id": approval.approval_id,
        "plan_id": approval.plan_id,
        "action_id": approval.action_id,
        "approved_by": approval.approved_by,
        "approval_status": approval.approval_status,
        "approval_scope": approval.approval_scope,
        "before_screenshot_hash": approval.before_screenshot_hash,
        "approved_at": approval.approved_at.isoformat() if approval.approved_at else None,
        "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
        "reject_reason": approval.reject_reason,
        "trace_id": approval.trace_id,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
        "updated_at": approval.updated_at.isoformat() if approval.updated_at else None,
    }


def _verification_to_dict(verification: ComputerActionVerification) -> dict:
    return {
        "verification_id": verification.verification_id,
        "plan_id": verification.plan_id,
        "action_id": verification.action_id,
        "verification_status": verification.verification_status,
        "expected_window": verification.expected_window,
        "expected_application": verification.expected_application,
        "before_screenshot_reference": verification.before_screenshot_reference,
        "after_screenshot_reference": verification.after_screenshot_reference,
        "before_screenshot_hash": verification.before_screenshot_hash,
        "after_screenshot_hash": verification.after_screenshot_hash,
        "result_summary": verification.result_summary,
        "trace_id": verification.trace_id,
        "created_at": verification.created_at.isoformat() if verification.created_at else None,
    }


def _current_screenshot_hash(payload: dict | None) -> str | None:
    if not payload:
        return None
    return payload.get("current_screenshot_hash")


def create_action_plan(db: Session, payload: ComputerActionPlanCreatePayload):
    session = get_session(db, payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="电脑会话不存在")
    ensure_safe_action_enabled()
    ensure_per_action_approval_enabled()
    ensure_post_action_verification_enabled()
    ensure_clipboard_disabled()
    ensure_file_transfer_disabled()
    ensure_action_type_allowed(payload.action_type)
    ensure_target_application_allowed(payload.target_application)
    ensure_target_control_allowed(payload.control_type, payload.control_label, payload.control_identifier, payload.target_description)
    ensure_coordinates_safe(payload.coordinates)
    if payload.action_type == "移动鼠标":
        ensure_move_enabled()
    elif payload.action_type == "单击":
        ensure_click_enabled()
    elif payload.action_type == "输入普通文本":
        ensure_text_input_enabled()
        ensure_text_safe(payload.text_input)
    elif payload.action_type == "按允许的快捷键":
        ensure_shortcut_safe(payload.text_input)
    resolved = resolve_target(
        type("TargetPayload", (), {
            "target_application": payload.target_application,
            "target_bundle_id": payload.target_bundle_id,
            "target_window": payload.target_window,
            "control_type": payload.control_type,
            "control_label": payload.control_label,
            "control_identifier": payload.control_identifier,
            "target_description": payload.target_description,
            "coordinates": payload.coordinates,
            "text_input": payload.text_input,
        })()
    )
    plan_payload = ComputerActionPlanCreatePayload(
        session_id=session.session_id,
        observation_id=payload.observation_id,
        task_id=payload.task_id or session.task_id,
        employee_id=payload.employee_id or session.employee_id,
        skill_id=payload.skill_id or session.skill_id,
        target_application=payload.target_application,
        target_bundle_id=payload.target_bundle_id,
        target_window=payload.target_window,
        goal=payload.goal,
        action_type=payload.action_type,
        control_type=payload.control_type,
        control_label=payload.control_label,
        control_identifier=payload.control_identifier,
        target_description=payload.target_description,
        coordinates=payload.coordinates,
        text_input=payload.text_input,
        approval_mode=payload.approval_mode,
        risk_level=payload.risk_level,
        max_actions=payload.max_actions,
        trace_id=payload.trace_id or session.trace_id,
        allow_coordinate_fallback=payload.allow_coordinate_fallback,
    )
    plan, target = create_action_plan_row(db, plan_payload)
    approval = create_approval_row(
        db,
        plan,
        target,
        approved_by=None,
        approval_scope=json.dumps({"session_id": session.session_id, "target_window": target.expected_window}, ensure_ascii=False),
        trace_id=payload.trace_id or session.trace_id,
    )
    plan.status = "等待批准"
    target.status = "待校验"
    add_policy_event(
        db,
        session_id=session.session_id,
        action_id=target.action_id,
        event_code="ACTION_PREVIEW_CREATED",
        event_message="已生成单步动作预览",
        risk_level=plan.risk_level,
        sensitive_data_involved=detect_sensitive_region(target.expected_window, target.expected_application, payload.text_input),
        trace_id=payload.trace_id or session.trace_id,
    )
    db.commit()
    db.refresh(plan)
    db.refresh(target)
    db.refresh(approval)
    return {
        "plan": _plan_to_dict(plan),
        "target": _target_to_dict(target),
        "approval": _approval_to_dict(approval),
        "preview": preview_payload(plan, target, session),
    }


def get_action_plan(db: Session, plan_id: str) -> dict:
    plan = db.get(ComputerActionPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="动作计划不存在")
    session = get_session(db, plan.session_id)
    target = db.query(ComputerActionTarget).filter(ComputerActionTarget.plan_id == plan.plan_id).order_by(ComputerActionTarget.created_at.asc()).first()
    approval = db.query(ComputerActionApproval).filter(ComputerActionApproval.plan_id == plan.plan_id).order_by(ComputerActionApproval.created_at.desc()).first()
    return {
        "plan": _plan_to_dict(plan),
        "target": _target_to_dict(target) if target else None,
        "approval": _approval_to_dict(approval) if approval else None,
        "preview": preview_payload(plan, target, session) if target and session else None,
    }


def preview_action_plan(db: Session, plan_id: str, *, current_screenshot_hash: str | None = None) -> dict:
    plan = db.get(ComputerActionPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="动作计划不存在")
    target = db.query(ComputerActionTarget).filter(ComputerActionTarget.plan_id == plan.plan_id).order_by(ComputerActionTarget.created_at.asc()).first()
    if not target:
        raise HTTPException(status_code=404, detail="动作目标不存在")
    session = get_session(db, plan.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="电脑会话不存在")
    approval = db.query(ComputerActionApproval).filter(ComputerActionApproval.plan_id == plan.plan_id, ComputerActionApproval.action_id == target.action_id).order_by(ComputerActionApproval.created_at.desc()).first()
    if approval and current_screenshot_hash and approval.before_screenshot_hash and approval.before_screenshot_hash != current_screenshot_hash:
        raise HTTPException(status_code=409, detail="窗口已变化，审批失效")
    return {
        "plan": _plan_to_dict(plan),
        "target": _target_to_dict(target),
        "approval": _approval_to_dict(approval) if approval else None,
        "preview": preview_payload(plan, target, session),
    }


def approve_action(db: Session, *, plan_id: str, approved_by: int | None, approval_scope: str | None, trace_id: str | None, current_screenshot_hash: str | None = None):
    plan = db.get(ComputerActionPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="动作计划不存在")
    target = db.query(ComputerActionTarget).filter(ComputerActionTarget.plan_id == plan.plan_id).order_by(ComputerActionTarget.created_at.asc()).first()
    if not target:
        raise HTTPException(status_code=404, detail="动作目标不存在")
    approval = db.query(ComputerActionApproval).filter(ComputerActionApproval.plan_id == plan.plan_id, ComputerActionApproval.action_id == target.action_id).order_by(ComputerActionApproval.created_at.desc()).first()
    if not approval:
        approval = create_approval_row(db, plan, target, approved_by=approved_by, approval_scope=approval_scope, trace_id=trace_id)
    if current_screenshot_hash and approval.before_screenshot_hash and approval.before_screenshot_hash != current_screenshot_hash:
        raise HTTPException(status_code=409, detail="窗口已变化，审批失效")
    approval = approve_action_row(db, approval, approved_by=approved_by, trace_id=trace_id)
    plan.status = "已批准"
    target.status = "已批准"
    db.commit()
    db.refresh(plan)
    db.refresh(target)
    db.refresh(approval)
    add_policy_event(
        db,
        session_id=plan.session_id,
        action_id=target.action_id,
        event_code="ACTION_APPROVAL_GRANTED",
        event_message="单步动作已批准",
        risk_level=plan.risk_level,
        trace_id=trace_id,
    )
    return {"plan": _plan_to_dict(plan), "target": _target_to_dict(target), "approval": _approval_to_dict(approval)}


def reject_action(db: Session, *, plan_id: str, approved_by: int | None, reason: str | None, trace_id: str | None):
    plan = db.get(ComputerActionPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="动作计划不存在")
    target = db.query(ComputerActionTarget).filter(ComputerActionTarget.plan_id == plan.plan_id).order_by(ComputerActionTarget.created_at.asc()).first()
    if not target:
        raise HTTPException(status_code=404, detail="动作目标不存在")
    approval = db.query(ComputerActionApproval).filter(ComputerActionApproval.plan_id == plan.plan_id, ComputerActionApproval.action_id == target.action_id).order_by(ComputerActionApproval.created_at.desc()).first()
    if not approval:
        approval = create_approval_row(db, plan, target, approved_by=approved_by, approval_scope=None, trace_id=trace_id)
    approval = reject_action_row(db, approval, approved_by=approved_by, reason=reason, trace_id=trace_id)
    plan.status = "已拒绝"
    target.status = "已拒绝"
    db.commit()
    db.refresh(plan)
    db.refresh(target)
    db.refresh(approval)
    add_policy_event(
        db,
        session_id=plan.session_id,
        action_id=target.action_id,
        event_code="ACTION_APPROVAL_REJECTED",
        event_message=reason or "单步动作被拒绝",
        risk_level=plan.risk_level,
        trace_id=trace_id,
    )
    return {"plan": _plan_to_dict(plan), "target": _target_to_dict(target), "approval": _approval_to_dict(approval)}


def execute_action(db: Session, *, plan_id: str, current_application: str | None, current_window: str | None, current_screenshot_hash: str | None, trace_id: str | None):
    from ..runtime import ComputerRuntime

    plan = db.get(ComputerActionPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="动作计划不存在")
    session = get_session(db, plan.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="电脑会话不存在")
    target = db.query(ComputerActionTarget).filter(ComputerActionTarget.plan_id == plan.plan_id).order_by(ComputerActionTarget.created_at.asc()).first()
    if not target:
        raise HTTPException(status_code=404, detail="动作目标不存在")
    approval = db.query(ComputerActionApproval).filter(ComputerActionApproval.plan_id == plan.plan_id, ComputerActionApproval.action_id == target.action_id).order_by(ComputerActionApproval.created_at.desc()).first()
    if not approval:
        raise HTTPException(status_code=403, detail="动作尚未批准")
    if approval.approval_status != "已批准":
        raise HTTPException(status_code=403, detail="动作尚未批准")
    if _normalize_dt(approval.expires_at) and _normalize_dt(approval.expires_at) < utcnow():
        approval.approval_status = "已过期"
        db.commit()
        raise HTTPException(status_code=409, detail="审批已过期")
    if current_screenshot_hash and approval.before_screenshot_hash and approval.before_screenshot_hash != current_screenshot_hash:
        approval.approval_status = "已过期"
        db.commit()
        raise HTTPException(status_code=409, detail="窗口已变化，审批失效")
    payload = ComputerActionPayload(
        action_type=target.action_type,
        target_application=target.expected_application,
        target_window=target.expected_window,
        target_description=target.target_description,
        coordinates=json.loads(target.coordinates_json) if target.coordinates_json else None,
        text_input=target.input_text_summary,
        timeout=30,
        trace_id=trace_id or plan.trace_id,
        approval_context={"plan_id": plan.plan_id, "action_id": target.action_id, "approval_id": approval.approval_id},
    )
    result = ComputerRuntime.execute_action(db, session, payload)
    verification = verify_action_result(
        db,
        plan=plan,
        approval=approval,
        action_result=result["action"],
        before_screenshot_reference=target.screenshot_before_reference,
        after_screenshot_reference=result["action"].get("screenshot_after") or result["action"].get("screenshot_before"),
        current_application=current_application,
        current_window=current_window,
        trace_id=trace_id or plan.trace_id,
    )
    plan.current_action_index = min(plan.max_actions, plan.current_action_index + 1)
    plan.status = "已暂停"
    target.status = "已完成" if verification.verification_status == "结果符合预期" else "已失败"
    session.status = "已暂停"
    session.approval_status = "已批准"
    add_policy_event(
        db,
        session_id=plan.session_id,
        action_id=target.action_id,
        event_code="ACTION_EXECUTION_SUCCEEDED" if result["action"].get("error_code") is None else "ACTION_EXECUTION_FAILED",
        event_message=result["action"].get("result") or result["action"].get("error_message") or "单步动作已执行",
        risk_level=plan.risk_level,
        trace_id=trace_id or plan.trace_id,
    )
    db.commit()
    db.refresh(plan)
    db.refresh(target)
    db.refresh(session)
    db.refresh(verification)
    result["session"]["status"] = session.status
    result["session"]["approval_status"] = session.approval_status
    return {
        "plan": _plan_to_dict(plan),
        "session": {
            "session_id": session.session_id,
            "status": session.status,
            "takeover_status": session.takeover_status,
            "last_screenshot_at": session.last_screenshot_at.isoformat() if session.last_screenshot_at else None,
        },
        "target": _target_to_dict(target),
        "approval": _approval_to_dict(approval),
        "verification": _verification_to_dict(verification),
        "result": result,
    }


def cancel_action(db: Session, *, plan_id: str, reason: str | None = None, trace_id: str | None = None):
    plan = db.get(ComputerActionPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="动作计划不存在")
    session = get_session(db, plan.session_id)
    cancel_plan(db, plan, reason=reason)
    target = db.query(ComputerActionTarget).filter(ComputerActionTarget.plan_id == plan.plan_id).order_by(ComputerActionTarget.created_at.asc()).first()
    if target:
        target.status = "已取消"
        db.commit()
    if session:
        session.status = "已取消"
        session.ended_at = utcnow()
        db.commit()
    if target:
        add_policy_event(
            db,
            session_id=plan.session_id,
            action_id=target.action_id,
            event_code="LOCAL_EMERGENCY_STOP_TRIGGERED" if reason and "停止" in reason else "ACTION_EXECUTION_FAILED",
            event_message=reason or "动作计划已取消",
            risk_level=plan.risk_level,
            trace_id=trace_id or plan.trace_id,
        )
    return {"plan": _plan_to_dict(plan), "target": _target_to_dict(target) if target else None}


def get_action_verification(db: Session, plan_id: str) -> dict:
    verification = db.query(ComputerActionVerification).filter(ComputerActionVerification.plan_id == plan_id).order_by(ComputerActionVerification.created_at.desc()).first()
    if not verification:
        raise HTTPException(status_code=404, detail="动作验证不存在")
    return {"verification": _verification_to_dict(verification)}


def health_check(db: Session) -> dict:
    from backend.config import get_settings

    settings = get_settings()
    return {
        "service": "computer-safe-action",
        "ok": True,
        "status": "running",
        "flags": {
            "MAC_SAFE_ACTION_ENABLED": settings.MAC_SAFE_ACTION_ENABLED,
            "MAC_SAFE_MOUSE_MOVE_ENABLED": settings.MAC_SAFE_MOUSE_MOVE_ENABLED,
            "MAC_SAFE_CLICK_ENABLED": settings.MAC_SAFE_CLICK_ENABLED,
            "MAC_SAFE_TEXT_INPUT_ENABLED": settings.MAC_SAFE_TEXT_INPUT_ENABLED,
            "PER_ACTION_APPROVAL_ENABLED": settings.PER_ACTION_APPROVAL_ENABLED,
            "POST_ACTION_VERIFICATION_ENABLED": settings.POST_ACTION_VERIFICATION_ENABLED,
        },
        "stats": {
            "plans": db.query(ComputerActionPlan).count(),
            "approvals": db.query(ComputerActionApproval).count(),
            "verifications": db.query(ComputerActionVerification).count(),
        },
        "time": utcnow().isoformat(),
    }
