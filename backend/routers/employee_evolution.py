from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..employee_evolution.evolution_engine import (
    EvolutionPayload,
    EvolutionSafetyError,
    analysis_to_dict,
    analyze_employee_evolution,
    growth_to_dict,
    risk_event_to_dict,
    skill_suggestion_to_dict,
)
from ..evolution_models import EmployeeGrowth, ReviewAnalysis, RiskEvent, SkillSuggestion
from ..models import TaskCenterTask, User


router = APIRouter(prefix="/api/employee-evolution")
PRIVILEGED_ROLES = {"owner", "admin"}
EMPLOYEE_ROLES = {"operator", "customer_service", "designer", "editor"}
AUDIT_ROLES = {"tianjian", "tianjian_audit", "security_auditor", "auditor"}


class AnalyzePayload(BaseModel):
    employee_code: str | None = None
    task_id: int | None = None
    boss_confirmed: bool = False
    security_audited: bool = False


@router.get("/profile/{code}")
def get_employee_profile(code: str, request: Request, db: Session = Depends(get_db)):
    user = require_evolution_user(request, db)
    ensure_employee_scope(user, code)
    growth = (
        db.query(EmployeeGrowth)
        .filter(EmployeeGrowth.employee_code == code)
        .order_by(EmployeeGrowth.id.desc())
        .first()
    )
    analyses = (
        db.query(ReviewAnalysis)
        .filter(ReviewAnalysis.employee_code == code)
        .order_by(ReviewAnalysis.id.desc())
        .limit(50)
        .all()
    )
    suggestions = (
        db.query(SkillSuggestion)
        .filter(SkillSuggestion.employee_code == code)
        .order_by(SkillSuggestion.id.desc())
        .limit(50)
        .all()
    )
    risks = (
        db.query(RiskEvent)
        .filter(RiskEvent.employee_code == code)
        .order_by(RiskEvent.id.desc())
        .limit(50)
        .all()
    )
    return {
        "employee_code": code,
        "employee_growth": growth_to_dict(growth) if growth else None,
        "review_analysis": [analysis_to_dict(row) for row in analyses],
        "skill_suggestions": [skill_suggestion_to_dict(row) for row in suggestions],
        "risk_events": [risk_event_to_dict(row) for row in risks],
    }


@router.get("/growth")
def list_employee_growth(request: Request, db: Session = Depends(get_db)):
    user = require_evolution_user(request, db)
    query = db.query(EmployeeGrowth).order_by(EmployeeGrowth.score.desc(), EmployeeGrowth.id.desc())
    if not can_view_all(user):
        query = query.filter(EmployeeGrowth.employee_code == user.username)
    rows = query.limit(200).all()
    return {"growth": [growth_to_dict(row) for row in rows]}


@router.post("/analyze")
def analyze_employee(payload: AnalyzePayload, request: Request, db: Session = Depends(get_db)):
    user = require_evolution_user(request, db)
    employee_code = resolve_employee_code(payload, db)
    if not employee_code:
        raise HTTPException(status_code=422, detail="employee_code or task_id is required")
    ensure_employee_scope(user, employee_code)
    if is_audit_user(user) and not can_view_all(user):
        raise HTTPException(status_code=403, detail="天监只查看风险审计数据，不触发成长分析")
    try:
        return analyze_employee_evolution(
            db,
            EvolutionPayload(
                employee_code=employee_code,
                task_id=payload.task_id,
                boss_confirmed=payload.boss_confirmed,
                security_audited=payload.security_audited,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EvolutionSafetyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/risk-events")
def list_risk_events(request: Request, db: Session = Depends(get_db)):
    user = require_evolution_user(request, db)
    query = db.query(RiskEvent).order_by(RiskEvent.id.desc())
    if not (can_view_all(user) or is_audit_user(user)):
        query = query.filter(RiskEvent.employee_code == user.username)
    rows = query.limit(200).all()
    return {"risk_events": [risk_event_to_dict(row) for row in rows]}


def resolve_employee_code(payload: AnalyzePayload, db: Session) -> str | None:
    if payload.employee_code:
        return payload.employee_code
    if payload.task_id:
        task = db.get(TaskCenterTask, payload.task_id)
        return task.assigned_ai_employee_code if task else None
    return None


def require_evolution_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role == "viewer":
        raise HTTPException(status_code=403, detail="无自学习进化中心访问权限")
    if role in PRIVILEGED_ROLES or role in EMPLOYEE_ROLES or role in AUDIT_ROLES:
        return user
    raise HTTPException(status_code=403, detail="无自学习进化中心访问权限")


def can_view_all(user: User) -> bool:
    return normalize_role(user.role) in PRIVILEGED_ROLES


def is_audit_user(user: User) -> bool:
    return normalize_role(user.role) in AUDIT_ROLES


def ensure_employee_scope(user: User, employee_code: str) -> None:
    if can_view_all(user) or is_audit_user(user):
        return
    if employee_code != user.username:
        raise HTTPException(status_code=403, detail="只能查看自己的成长数据")
