from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .defaults import DEFAULT_BINDINGS, DEFAULT_TOOLS
from .models import EmployeeToolBinding, ToolExecutionLog, ToolRegistry


HIGH_RISK_LEVELS = {"high", "critical"}
FORBIDDEN_TOOLS = {
    "delete_data",
    "payment_execute",
    "auto_login",
    "submit_order",
    "shell_execute",
    "docker_control",
    "systemctl_control",
    "git_push",
    "deploy_execute",
    "permission_modify",
    "unknown_code_execute",
    "external_api_write",
}
SENSITIVE_WORDS = {
    "password",
    "password_hash",
    "secret",
    "token",
    "api key",
    "apikey",
    "authorization",
    "bearer",
    "private_key",
    "cookie",
}


def list_tools(db: Session) -> list[dict]:
    persisted = [tool_to_dict(row) for row in db.query(ToolRegistry).order_by(ToolRegistry.tool_name.asc()).all()]
    persisted_names = {row["tool_name"] for row in persisted}
    defaults = [tool_to_dict(row) for row in DEFAULT_TOOLS if row["tool_name"] not in persisted_names]
    return sorted([*defaults, *persisted], key=lambda row: row["tool_name"])


def get_tool(db: Session, tool_name: str) -> dict | None:
    row = db.query(ToolRegistry).filter(ToolRegistry.tool_name == tool_name).first()
    if row:
        return tool_to_dict(row)
    for tool in DEFAULT_TOOLS:
        if tool["tool_name"] == tool_name:
            return tool_to_dict(tool)
    return None


def list_employee_bindings(db: Session, employee_code: str) -> list[dict]:
    tools_by_id = {tool["id"]: tool for tool in list_tools(db)}
    rows = [binding_to_dict(row, tools_by_id) for row in db.query(EmployeeToolBinding).filter(EmployeeToolBinding.employee_code == employee_code).all()]
    persisted_tool_ids = {row["tool_id"] for row in rows}
    defaults = [
        binding_to_dict(row, tools_by_id)
        for row in DEFAULT_BINDINGS
        if row["employee_code"] == employee_code and row["tool_id"] not in persisted_tool_ids
    ]
    return sorted([*defaults, *rows], key=lambda row: row["tool_name"])


def find_binding(db: Session, employee_code: str, tool_name: str) -> dict | None:
    tool = get_tool(db, tool_name)
    if not tool:
        return None
    row = (
        db.query(EmployeeToolBinding)
        .filter(EmployeeToolBinding.employee_code == employee_code, EmployeeToolBinding.tool_id == tool["id"])
        .order_by(EmployeeToolBinding.id.desc())
        .first()
    )
    if row:
        return binding_to_dict(row, {tool["id"]: tool})
    for binding in DEFAULT_BINDINGS:
        if binding["employee_code"] == employee_code and binding["tool_id"] == tool["id"]:
            return binding_to_dict(binding, {tool["id"]: tool})
    return None


def check_tool_access(
    db: Session,
    employee_code: str,
    tool_name: str,
    boss_confirmed: bool = False,
    security_audited: bool = False,
) -> dict:
    clean_employee_code = clean_text(employee_code)
    clean_tool_name = clean_text(tool_name)
    tool = get_tool(db, clean_tool_name)
    if not tool:
        return {
            "allowed": False,
            "require_approval": True,
            "reason": "工具未登记，禁止调用未知工具",
            "employee_code": clean_employee_code,
            "tool_name": clean_tool_name,
            "permission_level": "not_configured",
            "risk_level": "unknown",
        }

    binding = find_binding(db, clean_employee_code, clean_tool_name)
    require_approval = bool((binding or {}).get("require_approval") or is_high_risk(tool))
    if clean_tool_name in FORBIDDEN_TOOLS or not tool["enabled"]:
        return {
            "allowed": False,
            "require_approval": True,
            "reason": "工具属于禁止或未启用工具，第一阶段禁止调用",
            "employee_code": clean_employee_code,
            "tool_name": clean_tool_name,
            "permission_level": clean_text((binding or {}).get("permission_level") or "forbidden"),
            "risk_level": tool["risk_level"],
        }
    if not binding:
        return {
            "allowed": False,
            "require_approval": True,
            "reason": "员工未绑定该工具，禁止调用",
            "employee_code": clean_employee_code,
            "tool_name": clean_tool_name,
            "permission_level": "not_configured",
            "risk_level": tool["risk_level"],
        }
    if not binding["allowed"]:
        return {
            "allowed": False,
            "require_approval": require_approval,
            "reason": "员工工具权限被禁止",
            "employee_code": clean_employee_code,
            "tool_name": clean_tool_name,
            "permission_level": binding["permission_level"],
            "risk_level": tool["risk_level"],
        }
    if require_approval and not (boss_confirmed and security_audited):
        return {
            "allowed": False,
            "require_approval": True,
            "reason": "高风险或需审批工具必须老板确认和天监审核",
            "employee_code": clean_employee_code,
            "tool_name": clean_tool_name,
            "permission_level": binding["permission_level"],
            "risk_level": tool["risk_level"],
        }
    return {
        "allowed": True,
        "require_approval": require_approval,
        "reason": "工具权限检查通过，第一阶段仅允许 dry-run 模拟调用",
        "employee_code": clean_employee_code,
        "tool_name": clean_tool_name,
        "permission_level": binding["permission_level"],
        "risk_level": tool["risk_level"],
    }


def write_tool_log(
    db: Session,
    employee_code: str,
    tool_name: str,
    request_payload: Any,
    response_payload: Any,
    status: str,
    cost: float = 0.0,
    duration: float = 0.0,
) -> ToolExecutionLog:
    row = ToolExecutionLog(
        employee_code=clean_text(employee_code),
        tool_name=clean_text(tool_name),
        request=to_summary(request_payload),
        response=to_summary(response_payload),
        status=clean_text(status),
        cost=float(cost or 0.0),
        duration=float(duration or 0.0),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def tool_to_dict(row: ToolRegistry | dict) -> dict:
    if isinstance(row, dict):
        return {
            "id": row.get("id"),
            "tool_name": clean_text(row.get("tool_name")),
            "tool_type": clean_text(row.get("tool_type")),
            "description": clean_text(row.get("description")),
            "provider": clean_text(row.get("provider")),
            "version": clean_text(row.get("version")),
            "enabled": bool(row.get("enabled", False)),
            "risk_level": clean_text(row.get("risk_level") or "low"),
            "created_at": row.get("created_at"),
        }
    return {
        "id": row.id,
        "tool_name": clean_text(row.tool_name),
        "tool_type": clean_text(row.tool_type),
        "description": clean_text(row.description),
        "provider": clean_text(row.provider),
        "version": clean_text(row.version),
        "enabled": bool(row.enabled),
        "risk_level": clean_text(row.risk_level),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def binding_to_dict(row: EmployeeToolBinding | dict, tools_by_id: dict[int, dict]) -> dict:
    tool_id = row["tool_id"] if isinstance(row, dict) else row.tool_id
    tool = tools_by_id.get(tool_id, {})
    return {
        "id": row.get("id") if isinstance(row, dict) else row.id,
        "employee_code": clean_text(row["employee_code"] if isinstance(row, dict) else row.employee_code),
        "tool_id": tool_id,
        "tool_name": clean_text(tool.get("tool_name")),
        "tool_type": clean_text(tool.get("tool_type")),
        "permission_level": clean_text(row["permission_level"] if isinstance(row, dict) else row.permission_level),
        "allowed": bool(row["allowed"] if isinstance(row, dict) else row.allowed),
        "require_approval": bool(row["require_approval"] if isinstance(row, dict) else row.require_approval),
        "risk_level": clean_text(tool.get("risk_level") or "unknown"),
    }


def log_to_dict(row: ToolExecutionLog) -> dict:
    return {
        "id": row.id,
        "employee_code": clean_text(row.employee_code),
        "tool_name": clean_text(row.tool_name),
        "request": clean_text(row.request),
        "response": clean_text(row.response),
        "status": clean_text(row.status),
        "cost": float(row.cost or 0.0),
        "duration": float(row.duration or 0.0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def is_high_risk(tool: dict) -> bool:
    return clean_text(tool.get("risk_level")).lower() in HIGH_RISK_LEVELS


def to_summary(value: Any) -> str:
    if value is None:
        return "{}"
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        text = str(value)
    return clean_text(text)[:1000]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    lowered = text.lower()
    if any(word in lowered for word in SENSITIVE_WORDS):
        return "[REDACTED]"
    return text


def now_iso() -> str:
    return datetime.utcnow().isoformat()

