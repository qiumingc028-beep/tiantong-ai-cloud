from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..config import get_settings
from ..models import User


OWNER_ROLES = {"owner", "admin"}


def require_alpha_workflow_enabled() -> None:
    if not get_settings().ALPHA_WORKFLOW_ENABLED:
        raise HTTPException(status_code=403, detail="Alpha 工作流未启用")


def require_alpha_workflow_dashboard_enabled() -> None:
    if not get_settings().ALPHA_WORKFLOW_DASHBOARD_ENABLED:
        raise HTTPException(status_code=403, detail="Alpha 工作流页面未启用")


def require_alpha_workflow_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role not in OWNER_ROLES and user.username != "boss":
        raise HTTPException(status_code=403, detail="无 Alpha 工作流访问权限")
    return user
