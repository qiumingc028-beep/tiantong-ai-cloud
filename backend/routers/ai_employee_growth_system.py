from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..services.ai_employee_growth_system import (
    build_employee_growth_profile,
    build_employee_skill_suggestions,
    build_growth_system_overview,
    build_task_growth_impact,
    build_waiting_confirm_growth_items,
)


router = APIRouter(prefix="/api/ai-employee-growth-system")

ALLOWED_ROLES = {"owner", "admin", "boss"}


@router.get("/overview")
def get_growth_system_overview(request: Request, db: Session = Depends(get_db)):
    require_growth_system_user(request, db)
    return build_growth_system_overview(db)


@router.get("/employees/{employee_id}/profile")
def get_employee_growth_profile(employee_id: str, request: Request, db: Session = Depends(get_db)):
    require_growth_system_user(request, db)
    return build_employee_growth_profile(db, employee_id)


@router.get("/tasks/{task_id}/impact")
def get_task_growth_impact(task_id: int, request: Request, db: Session = Depends(get_db)):
    require_growth_system_user(request, db)
    impact = build_task_growth_impact(db, task_id)
    if impact is None:
        raise HTTPException(status_code=404, detail="task not found")
    return impact


@router.get("/waiting-confirm")
def get_waiting_confirm_growth_items(request: Request, db: Session = Depends(get_db)):
    require_growth_system_user(request, db)
    return build_waiting_confirm_growth_items(db)


@router.get("/employees/{employee_id}/skill-suggestions")
def get_employee_skill_suggestions(employee_id: str, request: Request, db: Session = Depends(get_db)):
    require_growth_system_user(request, db)
    return build_employee_skill_suggestions(db, employee_id)


def require_growth_system_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="no ai employee growth system permission")
    return user
