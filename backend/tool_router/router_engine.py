from __future__ import annotations

from sqlalchemy.orm import Session

from ..tool_center.gateway import check_tool_access, clean_text
from .models import ToolRoute, ToolRouteLog
from .routing_rules import DEFAULT_TOOL_ROUTES, match_tool_by_text


def list_routes(db: Session, employee_code: str | None = None) -> list[dict]:
    query = db.query(ToolRoute).order_by(ToolRoute.employee_code.asc(), ToolRoute.priority.asc(), ToolRoute.id.asc())
    if employee_code:
        query = query.filter(ToolRoute.employee_code == employee_code)
    persisted = [route_to_dict(row) for row in query.all()]
    persisted_keys = {(row["employee_code"], row["tool_name"]) for row in persisted}
    defaults = [
        route_to_dict(row)
        for row in DEFAULT_TOOL_ROUTES
        if (not employee_code or row["employee_code"] == employee_code)
        and (row["employee_code"], row["tool_name"]) not in persisted_keys
    ]
    return sorted([*defaults, *persisted], key=lambda row: (row["employee_code"], row["priority"], row["tool_name"]))


def check_route_permission(
    db: Session,
    employee_code: str,
    tool_name: str,
    boss_confirmed: bool = False,
    security_audited: bool = False,
) -> dict:
    route = find_enabled_route(db, employee_code, tool_name)
    if not route:
        return {
            "allowed": False,
            "require_approval": True,
            "reason": "员工未配置工具路由，禁止进入调用链",
            "employee_code": clean_text(employee_code),
            "tool_name": clean_text(tool_name),
            "risk_level": "unknown",
            "mode": "simulation",
        }
    decision = check_tool_access(
        db,
        employee_code,
        tool_name,
        boss_confirmed=boss_confirmed,
        security_audited=security_audited,
    )
    return {
        **decision,
        "route_enabled": True,
        "route_priority": route["priority"],
        "mode": "simulation",
    }


def route_tool(
    db: Session,
    employee_code: str,
    task: str,
    requirement: str | None = None,
    boss_confirmed: bool = False,
    security_audited: bool = False,
) -> dict:
    routes = [row for row in list_routes(db, employee_code=employee_code) if row["enabled"]]
    preferred_tool = match_tool_by_text(task, requirement or "")
    selected = next((row for row in routes if row["tool_name"] == preferred_tool), None)
    if not selected and routes:
        selected = routes[0]
    if not selected:
        result = {
            "recommended_tool": None,
            "risk_level": "unknown",
            "require_approval": True,
            "allowed": False,
            "reason": "未找到可用工具路由",
            "employee_code": clean_text(employee_code),
            "mode": "simulation",
        }
        write_route_log(db, employee_code, task, requirement, "none", result)
        return result

    decision = check_route_permission(
        db,
        employee_code,
        selected["tool_name"],
        boss_confirmed=boss_confirmed,
        security_audited=security_audited,
    )
    result = {
        "recommended_tool": selected["tool_name"],
        "risk_level": decision["risk_level"],
        "require_approval": decision["require_approval"],
        "allowed": decision["allowed"],
        "reason": build_route_reason(preferred_tool, selected, decision),
        "employee_code": clean_text(employee_code),
        "route_priority": selected["priority"],
        "mode": "simulation",
    }
    write_route_log(db, employee_code, task, requirement, selected["tool_name"], result)
    return result


def list_route_logs(db: Session) -> list[dict]:
    rows = db.query(ToolRouteLog).order_by(ToolRouteLog.created_at.desc(), ToolRouteLog.id.desc()).limit(100).all()
    return [route_log_to_dict(row) for row in rows]


def find_enabled_route(db: Session, employee_code: str, tool_name: str) -> dict | None:
    row = (
        db.query(ToolRoute)
        .filter(ToolRoute.employee_code == employee_code, ToolRoute.tool_name == tool_name, ToolRoute.enabled.is_(True))
        .order_by(ToolRoute.priority.asc(), ToolRoute.id.asc())
        .first()
    )
    if row:
        return route_to_dict(row)
    for route in DEFAULT_TOOL_ROUTES:
        if route["employee_code"] == employee_code and route["tool_name"] == tool_name and route["enabled"]:
            return route_to_dict(route)
    return None


def write_route_log(db: Session, employee_code: str, task: str, requirement: str | None, tool_name: str, result: dict) -> ToolRouteLog:
    row = ToolRouteLog(
        employee_code=clean_text(employee_code),
        task=clean_text(task)[:1000],
        requirement=clean_text(requirement)[:1000],
        recommended_tool=clean_text(tool_name),
        risk_level=clean_text(result.get("risk_level")),
        require_approval=bool(result.get("require_approval", False)),
        allowed=bool(result.get("allowed", False)),
        reason=clean_text(result.get("reason"))[:1000],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def route_to_dict(row: ToolRoute | dict) -> dict:
    if isinstance(row, dict):
        return {
            "id": row.get("id"),
            "employee_code": clean_text(row.get("employee_code")),
            "tool_name": clean_text(row.get("tool_name")),
            "priority": int(row.get("priority", 100)),
            "risk_level": clean_text(row.get("risk_level") or "low"),
            "enabled": bool(row.get("enabled", False)),
            "created_at": row.get("created_at"),
        }
    return {
        "id": row.id,
        "employee_code": clean_text(row.employee_code),
        "tool_name": clean_text(row.tool_name),
        "priority": int(row.priority),
        "risk_level": clean_text(row.risk_level),
        "enabled": bool(row.enabled),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def route_log_to_dict(row: ToolRouteLog) -> dict:
    return {
        "id": row.id,
        "employee_code": clean_text(row.employee_code),
        "task": clean_text(row.task),
        "requirement": clean_text(row.requirement),
        "recommended_tool": clean_text(row.recommended_tool),
        "risk_level": clean_text(row.risk_level),
        "require_approval": bool(row.require_approval),
        "allowed": bool(row.allowed),
        "reason": clean_text(row.reason),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def build_route_reason(preferred_tool: str | None, route: dict, decision: dict) -> str:
    if preferred_tool == route["tool_name"]:
        prefix = "根据任务关键词匹配到推荐工具"
    else:
        prefix = "未命中特定关键词，使用员工默认优先级工具"
    return f"{prefix}: {route['tool_name']}。{decision['reason']}"

