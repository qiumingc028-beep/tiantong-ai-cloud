from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..brain_tool_router.intent_engine import analyze_request, build_plan, check_approval, list_brain_logs, write_brain_log
from ..brain_tool_router.schemas import AnalyzePayload, ApprovalCheckPayload, PlanPayload
from ..database import get_db
from ..models import User


router = APIRouter(prefix="/api/brain-tool-router")
PRIVILEGED_ROLES = {"owner", "admin"}
EMPLOYEE_ROLES = {"operator", "customer_service", "designer", "editor", "finance"}


@router.post("/analyze")
def analyze(payload: AnalyzePayload, request: Request, db: Session = Depends(get_db)):
    user = require_brain_tool_router_user(request, db)
    result = analyze_request(payload.request_text)
    ensure_employee_scope(user, result["recommended_employee"]["employee_code"])
    write_brain_log(
        db,
        payload.request_text,
        result,
        result["recommended_employee"]["employee_code"],
        {"required_tools": result["required_tools"]},
        "analysis_only",
        "analyzed_dry_run",
    )
    return result


@router.post("/plan")
def plan(payload: PlanPayload, request: Request, db: Session = Depends(get_db)):
    user = require_brain_tool_router_user(request, db)
    analysis = analyze_request(payload.request_text)
    selected_employee = payload.employee_code or analysis["recommended_employee"]["employee_code"]
    ensure_employee_scope(user, selected_employee)
    return build_plan(
        db,
        payload.request_text,
        task_id=payload.task_id,
        employee_code=selected_employee,
        boss_confirmed=payload.boss_confirmed,
        security_audited=payload.security_audited,
    )


@router.post("/approval-check")
def approval_check(payload: ApprovalCheckPayload, request: Request, db: Session = Depends(get_db)):
    user = require_brain_tool_router_user(request, db)
    if payload.employee_code:
        ensure_employee_scope(user, payload.employee_code)
    result = check_approval(
        payload.risk_level,
        boss_confirmed=payload.boss_confirmed,
        security_audited=payload.security_audited,
    )
    write_brain_log(
        db,
        payload.task_id or "approval-check",
        {"risk_level": result["risk_level"], "required_confirmations": result["required_confirmations"]},
        payload.employee_code,
        {"dry_run": True},
        result["approval_status"],
        result["reason"],
    )
    if not result["allowed"]:
        raise HTTPException(status_code=403, detail=result)
    return result


@router.get("/logs")
def logs(request: Request, db: Session = Depends(get_db)):
    user = require_brain_tool_router_user(request, db)
    rows = list_brain_logs(db)
    if not can_view_all(user):
        rows = [row for row in rows if row["recommended_employee"] == user.username]
    return {"logs": rows}


def require_brain_tool_router_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role == "viewer":
        raise HTTPException(status_code=403, detail="无 Brain Tool Router 访问权限")
    if role in PRIVILEGED_ROLES or role in EMPLOYEE_ROLES:
        return user
    raise HTTPException(status_code=403, detail="无 Brain Tool Router 访问权限")


def can_view_all(user: User) -> bool:
    return normalize_role(user.role) in PRIVILEGED_ROLES


def ensure_employee_scope(user: User, employee_code: str) -> None:
    if can_view_all(user):
        return
    if employee_code != user.username:
        raise HTTPException(status_code=403, detail="只能分析或规划自己的工具任务")

