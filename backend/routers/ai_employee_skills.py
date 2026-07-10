from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..models import User
from ..services.ai_employee_skills import (
    build_employee_skill_list,
    build_employee_skill_relations,
    build_skill_detail,
)


router = APIRouter(prefix="/api/ai-employee-skills")

ALLOWED_ROLES = {"owner", "admin", "boss"}


@router.get("/skills")
def get_employee_skills(
    request: Request,
    employee_id: str | None = None,
    department: str | None = None,
    risk_level: str | None = None,
    skill_version: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    user = require_ai_employee_skills_user(request, db)
    return build_employee_skill_list(
        db,
        user,
        {
            "employee_id": employee_id,
            "department": department,
            "risk_level": risk_level,
            "skill_version": skill_version,
            "q": q,
        },
    )


@router.get("/skills/{skill_id}")
def get_employee_skill_detail(skill_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_ai_employee_skills_user(request, db)
    return build_skill_detail(db, user, skill_id)


@router.get("/employees/{employee_id}/skills")
def get_employee_skill_relations(employee_id: str, request: Request, db: Session = Depends(get_db)):
    user = require_ai_employee_skills_user(request, db)
    return build_employee_skill_relations(db, user, employee_id)


def require_ai_employee_skills_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if normalize_role(user.role) not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="no ai employee skills permission")
    return user
