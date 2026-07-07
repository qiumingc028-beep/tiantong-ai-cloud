from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..models import User
from ..tool_center.gateway import (
    check_tool_access,
    get_tool,
    list_employee_bindings,
    list_tools,
    log_to_dict,
    write_tool_log,
)
from ..tool_center.models import ToolExecutionLog


router = APIRouter()
PRIVILEGED_ROLES = {"owner", "admin"}
EMPLOYEE_ROLES = {"operator", "customer_service", "designer", "editor", "finance"}


class ToolCheckPayload(BaseModel):
    employee_code: str
    tool_name: str
    boss_confirmed: bool = False
    security_audited: bool = False


class ToolCallPayload(ToolCheckPayload):
    request: dict[str, Any] | None = None
    dry_run: bool = True


@router.get("/api/tools/list")
def get_tools_list(request: Request, db: Session = Depends(get_db)):
    require_tool_center_user(request, db)
    return {"tools": list_tools(db)}


@router.get("/api/tools/employees/{code}")
def get_employee_tools(code: str, request: Request, db: Session = Depends(get_db)):
    user = require_tool_center_user(request, db)
    ensure_employee_scope(user, code)
    return {"employee_code": code, "tools": list_employee_bindings(db, code)}


@router.post("/api/tools/check")
def check_tool_permission(payload: ToolCheckPayload, request: Request, db: Session = Depends(get_db)):
    user = require_tool_center_user(request, db)
    ensure_employee_scope(user, payload.employee_code)
    return check_tool_access(
        db,
        payload.employee_code,
        payload.tool_name,
        boss_confirmed=payload.boss_confirmed,
        security_audited=payload.security_audited,
    )


@router.post("/api/tools/call")
def call_tool(payload: ToolCallPayload, request: Request, db: Session = Depends(get_db)):
    user = require_tool_center_user(request, db)
    ensure_employee_scope(user, payload.employee_code)
    started_at = time.perf_counter()
    decision = check_tool_access(
        db,
        payload.employee_code,
        payload.tool_name,
        boss_confirmed=payload.boss_confirmed,
        security_audited=payload.security_audited,
    )
    if not decision["allowed"]:
        response = {
            "tool": payload.tool_name,
            "status": "blocked",
            "mode": "simulation",
            "allowed": False,
            "require_approval": decision["require_approval"],
            "reason": decision["reason"],
        }
        write_tool_log(
            db,
            payload.employee_code,
            payload.tool_name,
            payload.request or {},
            response,
            "blocked",
            duration=round((time.perf_counter() - started_at) * 1000, 2),
        )
        return response

    response = {
        "tool": payload.tool_name,
        "status": "approved",
        "mode": "simulation",
        "allowed": True,
        "require_approval": decision["require_approval"],
        "reason": "第一阶段 dry-run：已完成权限检查和日志记录，未真实调用工具。",
    }
    log = write_tool_log(
        db,
        payload.employee_code,
        payload.tool_name,
        payload.request or {},
        response,
        "approved",
        cost=0.0,
        duration=round((time.perf_counter() - started_at) * 1000, 2),
    )
    response["log_id"] = log.id
    return response


@router.get("/api/tools/logs")
def get_tool_logs(request: Request, db: Session = Depends(get_db)):
    user = require_tool_center_user(request, db)
    query = db.query(ToolExecutionLog).order_by(ToolExecutionLog.created_at.desc(), ToolExecutionLog.id.desc())
    if not can_view_all(user):
        query = query.filter(ToolExecutionLog.employee_code == user.username)
    return {"logs": [log_to_dict(row) for row in query.limit(100).all()]}


@router.get("/api/tools/{tool_name}")
def get_tool_detail(tool_name: str, request: Request, db: Session = Depends(get_db)):
    require_tool_center_user(request, db)
    tool = get_tool(db, tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail={"error": "tool_not_found", "tool_name": tool_name})
    return {"tool": tool}


def require_tool_center_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role == "viewer":
        raise HTTPException(status_code=403, detail="无工具中心访问权限")
    if role in PRIVILEGED_ROLES or role in EMPLOYEE_ROLES:
        return user
    raise HTTPException(status_code=403, detail="无工具中心访问权限")


def can_view_all(user: User) -> bool:
    return normalize_role(user.role) in PRIVILEGED_ROLES


def ensure_employee_scope(user: User, employee_code: str) -> None:
    if can_view_all(user):
        return
    if employee_code != user.username:
        raise HTTPException(status_code=403, detail="只能查看或调用自己的工具权限")

