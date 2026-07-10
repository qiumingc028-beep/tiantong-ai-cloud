from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..services.ai_employee_growth import (
    build_employee_growth_detail,
    build_employee_growth_timeline,
    build_growth_overview,
)


router = APIRouter(prefix="/api/ai-employee-growth")

ALLOWED_ROLES = {"owner", "admin", "boss"}


@router.get("/overview")
def get_ai_employee_growth_overview(request: Request, db: Session = Depends(get_db)):
    require_growth_user(request, db)
    return build_growth_overview(db)


@router.get("/employees/{employee_id}")
def get_ai_employee_growth_detail(employee_id: str, request: Request, db: Session = Depends(get_db)):
    require_growth_user(request, db)
    return build_employee_growth_detail(db, employee_id)


@router.get("/employees/{employee_id}/timeline")
def get_ai_employee_growth_timeline(employee_id: str, request: Request, db: Session = Depends(get_db)):
    require_growth_user(request, db)
    return build_employee_growth_timeline(db, employee_id)


def require_growth_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in ALLOWED_ROLES:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="no ai employee growth permission")
    return user
