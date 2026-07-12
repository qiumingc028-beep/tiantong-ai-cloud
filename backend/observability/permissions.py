from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..config import get_settings


def get_flag(name: str) -> bool:
    settings = get_settings()
    return bool(getattr(settings, name, False))


def require_feature_enabled(name: str) -> None:
    if not get_flag(name):
        raise HTTPException(status_code=403, detail="安全运营功能当前未开启")


def require_observability_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="没有安全运营中心访问权限")
    return user


def require_observability_manage_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="没有安全运营中心管理权限")
    return user

