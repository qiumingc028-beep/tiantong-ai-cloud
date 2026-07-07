from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..ai_capabilities.defaults import DEFAULT_CAPABILITIES, DEFAULT_TOOL_PERMISSIONS
from ..ai_capabilities.models import AiCapability, ToolPermission
from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..models import User


router = APIRouter()
PRIVILEGED_ROLES = {"owner", "admin"}
EMPLOYEE_ROLES = {"operator", "customer_service", "designer", "editor"}
HIGH_RISK_TOOLS = {
    "delete_data",
    "payment_execute",
    "shell_execute",
    "docker_control",
    "systemctl_control",
    "git_push",
    "deploy_execute",
    "unknown_api",
    "external_api_write",
    "permission_modify",
}
SENSITIVE_WORDS = {"password", "password_hash", "secret", "token", "api key", "authorization", "bearer", "private_key"}


class CapabilityCreatePayload(BaseModel):
    employee_code: str
    employee_name: str
    capability_name: str
    capability_type: str
    description: str | None = None
    enabled: bool = True


class ToolCheckPayload(BaseModel):
    employee_code: str
    tool_name: str
    boss_confirmed: bool = False
    security_audited: bool = False


@router.get("/api/capabilities/employees/{code}")
def get_employee_capabilities(code: str, request: Request, db: Session = Depends(get_db)):
    user = require_capability_user(request, db)
    ensure_employee_scope(user, code)
    rows = load_capabilities(db, employee_code=code)
    return {"employee_code": code, "capabilities": [capability_to_dict(row) for row in rows]}


@router.get("/api/capabilities/list")
def list_capabilities(request: Request, db: Session = Depends(get_db)):
    user = require_capability_user(request, db)
    employee_code = None if can_view_all(user) else user.username
    rows = load_capabilities(db, employee_code=employee_code)
    return {"capabilities": [capability_to_dict(row) for row in rows]}


@router.post("/api/capabilities/create")
def create_capability(payload: CapabilityCreatePayload, request: Request, db: Session = Depends(get_db)):
    require_capability_admin(request, db)
    row = AiCapability(
        employee_code=clean_value(payload.employee_code),
        employee_name=clean_value(payload.employee_name),
        capability_name=clean_value(payload.capability_name),
        capability_type=clean_value(payload.capability_type),
        description=clean_value(payload.description),
        enabled=payload.enabled,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"capability": capability_to_dict(row)}


@router.get("/api/tools/permissions/{code}")
def get_tool_permissions(code: str, request: Request, db: Session = Depends(get_db)):
    user = require_capability_user(request, db)
    ensure_employee_scope(user, code)
    rows = load_tool_permissions(db, employee_code=code)
    return {"employee_code": code, "permissions": [permission_to_dict(row) for row in rows]}


@router.post("/api/tools/check")
def check_tool_permission(payload: ToolCheckPayload, request: Request, db: Session = Depends(get_db)):
    user = require_capability_user(request, db)
    ensure_employee_scope(user, payload.employee_code)
    permission = find_tool_permission(db, payload.employee_code, payload.tool_name)
    tool_name = clean_value(payload.tool_name)
    if not permission:
        return {
            "allowed": False,
            "require_approval": True,
            "reason": "未配置工具权限，禁止调用未知工具",
            "employee_code": clean_value(payload.employee_code),
            "tool_name": tool_name,
            "permission_level": "not_configured",
        }

    require_approval = bool(permission["require_approval"] or is_high_risk_tool(tool_name))
    if not permission["allowed"]:
        return {
            "allowed": False,
            "require_approval": require_approval,
            "reason": "工具权限被禁止",
            "employee_code": clean_value(payload.employee_code),
            "tool_name": tool_name,
            "permission_level": clean_value(permission["permission_level"]),
        }
    if require_approval and not (payload.boss_confirmed and payload.security_audited):
        return {
            "allowed": False,
            "require_approval": True,
            "reason": "需要老板确认和安全审核",
            "employee_code": clean_value(payload.employee_code),
            "tool_name": tool_name,
            "permission_level": clean_value(permission["permission_level"]),
        }
    return {
        "allowed": True,
        "require_approval": require_approval,
        "reason": "工具权限检查通过",
        "employee_code": clean_value(payload.employee_code),
        "tool_name": tool_name,
        "permission_level": clean_value(permission["permission_level"]),
    }


def require_capability_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role == "viewer":
        raise HTTPException(status_code=403, detail="无 AI能力中心访问权限")
    if role in PRIVILEGED_ROLES or role in EMPLOYEE_ROLES:
        return user
    raise HTTPException(status_code=403, detail="无 AI能力中心访问权限")


def require_capability_admin(request: Request, db: Session) -> User:
    user = require_capability_user(request, db)
    if not can_view_all(user):
        raise HTTPException(status_code=403, detail="无 AI能力中心管理权限")
    return user


def can_view_all(user: User) -> bool:
    return normalize_role(user.role) in PRIVILEGED_ROLES


def ensure_employee_scope(user: User, employee_code: str) -> None:
    if can_view_all(user):
        return
    if employee_code != user.username:
        raise HTTPException(status_code=403, detail="只能查看自己的能力和工具权限")


def load_capabilities(db: Session, employee_code: str | None = None) -> list[AiCapability | dict]:
    query = db.query(AiCapability).order_by(AiCapability.employee_code.asc(), AiCapability.id.asc())
    if employee_code:
        query = query.filter(AiCapability.employee_code == employee_code)
    rows = query.all()
    defaults = [row for row in DEFAULT_CAPABILITIES if not employee_code or row["employee_code"] == employee_code]
    return [*defaults, *rows]


def load_tool_permissions(db: Session, employee_code: str | None = None) -> list[ToolPermission | dict]:
    query = db.query(ToolPermission).order_by(ToolPermission.employee_code.asc(), ToolPermission.id.asc())
    if employee_code:
        query = query.filter(ToolPermission.employee_code == employee_code)
    rows = query.all()
    defaults = [row for row in DEFAULT_TOOL_PERMISSIONS if not employee_code or row["employee_code"] == employee_code]
    return [*defaults, *rows]


def find_tool_permission(db: Session, employee_code: str, tool_name: str) -> dict | None:
    row = (
        db.query(ToolPermission)
        .filter(ToolPermission.employee_code == employee_code, ToolPermission.tool_name == tool_name)
        .order_by(ToolPermission.id.desc())
        .first()
    )
    if row:
        return permission_to_dict(row)
    for item in DEFAULT_TOOL_PERMISSIONS:
        if item["employee_code"] == employee_code and item["tool_name"] == tool_name:
            return permission_to_dict(item)
    return None


def capability_to_dict(row: AiCapability | dict) -> dict:
    if isinstance(row, dict):
        return {
            "id": row.get("id"),
            "employee_code": clean_value(row.get("employee_code")),
            "employee_name": clean_value(row.get("employee_name")),
            "capability_name": clean_value(row.get("capability_name")),
            "capability_type": clean_value(row.get("capability_type")),
            "description": clean_value(row.get("description")),
            "enabled": bool(row.get("enabled", True)),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
    return {
        "id": row.id,
        "employee_code": clean_value(row.employee_code),
        "employee_name": clean_value(row.employee_name),
        "capability_name": clean_value(row.capability_name),
        "capability_type": clean_value(row.capability_type),
        "description": clean_value(row.description),
        "enabled": bool(row.enabled),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def permission_to_dict(row: ToolPermission | dict) -> dict:
    if isinstance(row, dict):
        return {
            "id": row.get("id"),
            "employee_code": clean_value(row.get("employee_code")),
            "tool_name": clean_value(row.get("tool_name")),
            "permission_level": clean_value(row.get("permission_level")),
            "allowed": bool(row.get("allowed", False)),
            "require_approval": bool(row.get("require_approval", False)),
            "created_at": row.get("created_at"),
        }
    return {
        "id": row.id,
        "employee_code": clean_value(row.employee_code),
        "tool_name": clean_value(row.tool_name),
        "permission_level": clean_value(row.permission_level),
        "allowed": bool(row.allowed),
        "require_approval": bool(row.require_approval),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def is_high_risk_tool(tool_name: str) -> bool:
    name = (tool_name or "").lower()
    return name in HIGH_RISK_TOOLS or any(word in name for word in ("delete", "payment", "deploy", "docker", "systemctl", "git_push"))


def clean_value(value: str | None) -> str:
    text = (value or "").strip()
    lowered = text.lower()
    if any(word in lowered for word in SENSITIVE_WORDS):
        return "[REDACTED]"
    return text
