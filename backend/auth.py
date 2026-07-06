from __future__ import annotations

from typing import Optional
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .auth_data import MENU_ITEMS, ROLE_LABELS, normalize_role
from .config import get_settings
from .database import get_db, get_redis
from .models import Permission, Role, User


settings = get_settings()
SESSION_TTL = settings.SESSION_TTL_SECONDS


def hash_password(password: str, salt: str = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000)
    return f"pbkdf2_sha256${salt}${dk.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        method, salt, digest = password_hash.split("$")
        return hash_password(password, salt) == password_hash
    except Exception:
        return False


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=SESSION_TTL)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return int(payload["sub"])
    except Exception:
        return None


def create_session(user_id: int) -> tuple[str, str]:
    session_token = secrets.token_urlsafe(32)
    jwt_token = create_access_token(user_id)
    redis_client = get_redis()
    redis_client.setex(f"session:{session_token}", SESSION_TTL, str(user_id))
    redis_client.setex(f"jwt:{user_id}", SESSION_TTL, jwt_token)
    return session_token, jwt_token


def delete_session(session_token: Optional[str]):
    if session_token:
        get_redis().delete(f"session:{session_token}")


def get_role_permissions(db: Session, role_code: str) -> set[str]:
    rows = (
        db.query(Permission.code)
        .join(Role.permissions)
        .filter(Role.code == role_code)
        .all()
    )
    return {r[0] for r in rows}


def get_role_menus(db: Session, role_code: str):
    permissions = get_role_permissions(db, role_code)
    return [item for item in MENU_ITEMS if item["permission"] in permissions]


def serialize_user(db: Session, user: User):
    role_code = normalize_role(user.role)
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "role_code": role_code,
        "role_label": ROLE_LABELS.get(role_code, user.role),
        "display_name": user.display_name,
        "active": user.active,
        "menus": get_role_menus(db, role_code),
    }


def current_user(request: Request, db: Session = Depends(get_db)):
    session_token = request.cookies.get("tiantong_session")
    user_id = None
    if session_token:
        user_id = get_redis().get(f"session:{session_token}")

    if not user_id:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            user_id = decode_access_token(auth_header.removeprefix("Bearer ").strip())

    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")

    user = db.get(User, int(user_id))
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="账号无效")
    return user


def require_user(request: Request, db: Session):
    return serialize_user(db, current_user(request, db))


def require_admin_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in ["owner", "admin"]:
        raise HTTPException(status_code=403, detail="没有管理员权限")
    return user


def require_permission_user(request: Request, db: Session, permission_code: str):
    user = current_user(request, db)
    role_code = normalize_role(user.role)
    if permission_code not in get_role_permissions(db, role_code):
        raise HTTPException(status_code=403, detail="没有访问权限")
    return user
