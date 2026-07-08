from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..models import User
from ..tool_router.router_engine import check_route_permission, list_route_logs, list_routes, route_tool
from ..tool_router.schemas import ToolRoutePayload, ToolRouterCheckPayload


router = APIRouter(prefix="/api/tool-router")
PRIVILEGED_ROLES = {"owner", "admin"}
EMPLOYEE_ROLES = {"operator", "customer_service", "designer", "editor", "finance"}


@router.get("/routes")
def get_routes(request: Request, db: Session = Depends(get_db)):
    user = require_tool_router_user(request, db)
    employee_code = None if can_view_all(user) else user.username
    return {"routes": list_routes(db, employee_code=employee_code)}


@router.post("/check")
def check_tool_route(payload: ToolRouterCheckPayload, request: Request, db: Session = Depends(get_db)):
    user = require_tool_router_user(request, db)
    ensure_employee_scope(user, payload.employee_code)
    return check_route_permission(
        db,
        payload.employee_code,
        payload.tool_name,
        boss_confirmed=payload.boss_confirmed,
        security_audited=payload.security_audited,
    )


@router.post("/route")
def route_tool_request(payload: ToolRoutePayload, request: Request, db: Session = Depends(get_db)):
    user = require_tool_router_user(request, db)
    ensure_employee_scope(user, payload.employee_code)
    return route_tool(
        db,
        payload.employee_code,
        payload.task,
        payload.requirement,
        boss_confirmed=payload.boss_confirmed,
        security_audited=payload.security_audited,
    )


@router.get("/logs")
def get_route_logs(request: Request, db: Session = Depends(get_db)):
    user = require_tool_router_user(request, db)
    logs = list_route_logs(db)
    if not can_view_all(user):
        logs = [row for row in logs if row["employee_code"] == user.username]
    return {"logs": logs}


def require_tool_router_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role == "viewer":
        raise HTTPException(status_code=403, detail="无工具路由中心访问权限")
    if role in PRIVILEGED_ROLES or role in EMPLOYEE_ROLES:
        return user
    raise HTTPException(status_code=403, detail="无工具路由中心访问权限")


def can_view_all(user: User) -> bool:
    return normalize_role(user.role) in PRIVILEGED_ROLES


def ensure_employee_scope(user: User, employee_code: str) -> None:
    if can_view_all(user):
        return
    if employee_code != user.username:
        raise HTTPException(status_code=403, detail="只能查看或路由自己的工具")

