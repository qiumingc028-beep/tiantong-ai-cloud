from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..models import User
from ..services.ai_employee_ecosystem_overview import build_ai_employee_ecosystem_overview


router = APIRouter(prefix="/api/ai-employee-ecosystem")

ALLOWED_ROLES = {"owner", "admin", "viewer"}


@router.get("/overview")
def get_ai_employee_ecosystem_overview(request: Request, db: Session = Depends(get_db)):
    user = require_ai_employee_ecosystem_user(request, db)
    return build_ai_employee_ecosystem_overview(db, user)


def require_ai_employee_ecosystem_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if normalize_role(user.role) not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="no ai employee ecosystem permission")
    return user
