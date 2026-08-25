import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .auth_data import MENU_ITEMS, ROLE_LABELS, normalize_role
from .config import get_settings
from .database import get_db, get_redis
from .models import Permission, Role, User


settings = get_settings()
SESSION_TTL = settings.SESSION_TTL_SECONDS
CAPTURE_AUTH_PURPOSE = "computer_workflow_readonly_capture"
CAPTURE_AUTH_WORKFLOW_HEADER = "X-Tiantong-Capture-Workflow"
CAPTURE_AUTH_TTL_SECONDS = 60
CAPTURE_PAGE_PATH = "/computer-workflow-center.html"
CAPTURE_READONLY_PATHS = frozenset(
    {
        CAPTURE_PAGE_PATH,
        "/rbac-navigation.js",
        "/api/me",
        "/api/task-center/tasks",
        "/api/v2/computer/workflows",
    }
)
CAPTURE_READONLY_METHODS = frozenset({"GET", "HEAD"})


@dataclass
class CaptureAuthorization:
    token: str = field(repr=False)
    workflow_id: str
    origin: str
    target_path: str
    allowed_paths: frozenset[str] = CAPTURE_READONLY_PATHS

    def clear(self) -> None:
        self.token = ""


def _capture_signing_key(active_settings) -> bytes:
    return hashlib.sha256(
        f"{active_settings.JWT_SECRET}\0{CAPTURE_AUTH_PURPOSE}".encode("utf-8")
    ).digest()


def create_capture_authorization(*, user_id: int, workflow_id: str, target_url: str) -> CaptureAuthorization:
    active_settings = get_settings()
    parsed = urlsplit((target_url or "").strip())
    origin = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port is not None:
        origin = f"{origin}:{parsed.port}"
    if (
        active_settings.APP_ENV != "test"
        or active_settings.IS_PRODUCTION
        or origin not in active_settings.PAGE_CAPTURE_ALLOWED_ORIGINS
        or parsed.path != CAPTURE_PAGE_PATH
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or not workflow_id
        or int(user_id) <= 0
    ):
        raise ValueError("capture authorization target is not permitted")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "purpose": CAPTURE_AUTH_PURPOSE,
        "workflow_id": workflow_id,
        "origin": origin,
        "target_path": parsed.path,
        "jti": secrets.token_urlsafe(16),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=CAPTURE_AUTH_TTL_SECONDS)).timestamp()),
    }
    token = jwt.encode(
        payload,
        _capture_signing_key(active_settings),
        algorithm=active_settings.JWT_ALGORITHM,
    )
    return CaptureAuthorization(
        token=token,
        workflow_id=workflow_id,
        origin=origin,
        target_path=parsed.path,
    )


def decode_capture_access_token(token: str, request: Request) -> int | None:
    active_settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            _capture_signing_key(active_settings),
            algorithms=[active_settings.JWT_ALGORITHM],
        )
        request_origin = f"{request.url.scheme}://{request.url.hostname}"
        if request.url.port is not None:
            request_origin = f"{request_origin}:{request.url.port}"
        if (
            active_settings.APP_ENV != "test"
            or active_settings.IS_PRODUCTION
            or payload.get("purpose") != CAPTURE_AUTH_PURPOSE
            or request.method.upper() not in CAPTURE_READONLY_METHODS
            or request.url.path not in CAPTURE_READONLY_PATHS
            or request_origin != payload.get("origin")
            or payload.get("target_path") != CAPTURE_PAGE_PATH
            or request.headers.get(CAPTURE_AUTH_WORKFLOW_HEADER) != payload.get("workflow_id")
        ):
            return None
        request.state.capture_workflow_id = str(payload["workflow_id"])
        return int(payload["sub"])
    except Exception:
        return None


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


def decode_access_token(token: str) -> int | None:
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


def delete_session(session_token: str | None):
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


def capture_workflow_id(request: Request) -> str | None:
    return getattr(request.state, "capture_workflow_id", None)


def current_user(request: Request, db: Session = Depends(get_db)):
    session_token = request.cookies.get("tiantong_session")
    user_id = None
    if session_token:
        user_id = get_redis().get(f"session:{session_token}")

    if not user_id:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
            user_id = decode_access_token(token) or decode_capture_access_token(token, request)

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
