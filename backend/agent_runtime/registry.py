from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from ..config import get_settings
from .constants import DEFAULT_CAPABILITIES
from .models import AgentCapability


@dataclass(slots=True)
class CapabilityRecord:
    capability_id: str
    capability_name: str
    capability_type: str
    description: str | None
    executor_type: str
    risk_level: str
    enabled: bool
    readonly: bool
    requires_boss_approval: bool
    requires_security_audit: bool
    timeout_seconds: int
    max_retries: int
    input_schema_json: str | None
    output_schema_json: str | None
    allowed_employee_codes: list[str]
    version: str
    created_at: str | None = None
    updated_at: str | None = None


def seed_builtin_capabilities(db: Session) -> None:
    for payload in DEFAULT_CAPABILITIES:
        capability_id = str(payload["capability_id"])
        row = db.get(AgentCapability, capability_id)
        if not row:
            row = AgentCapability(capability_id=capability_id)
            db.add(row)
        row.capability_name = str(payload["capability_name"])
        row.capability_type = str(payload["capability_type"])
        row.description = payload.get("description")  # type: ignore[assignment]
        row.executor_type = str(payload["executor_type"])
        row.risk_level = str(payload["risk_level"])
        row.enabled = bool(payload["enabled"])
        row.readonly = bool(payload["readonly"])
        row.requires_boss_approval = bool(payload["requires_boss_approval"])
        row.requires_security_audit = bool(payload["requires_security_audit"])
        row.timeout_seconds = int(payload["timeout_seconds"])
        row.max_retries = int(payload["max_retries"])
        row.input_schema_json = payload.get("input_schema_json")  # type: ignore[assignment]
        row.output_schema_json = payload.get("output_schema_json")  # type: ignore[assignment]
        row.allowed_employee_codes_json = payload.get("allowed_employee_codes_json")  # type: ignore[assignment]
        row.version = str(payload["version"])
    db.commit()


def list_capabilities(db: Session, include_builtin: bool = True) -> list[AgentCapability]:
    rows = db.query(AgentCapability).order_by(AgentCapability.capability_id.asc()).all()
    if rows:
        return rows
    if include_builtin:
        seed_builtin_capabilities(db)
        return db.query(AgentCapability).order_by(AgentCapability.capability_id.asc()).all()
    return []


def resolve_capability(db: Session, capability_id: str) -> AgentCapability | None:
    row = db.get(AgentCapability, capability_id)
    if row:
        return row
    seed_builtin_capabilities(db)
    return db.get(AgentCapability, capability_id)


def capability_allowed_employee_codes(capability: AgentCapability) -> list[str]:
    raw = capability.allowed_employee_codes_json or "[]"
    try:
        codes = json.loads(raw)
    except Exception:
        return []
    if not isinstance(codes, list):
        return []
    return [str(code) for code in codes if str(code).strip()]


def normalize_capability_payload(payload: dict | None) -> dict[str, object]:
    return payload or {}


def resolve_executor_type(capability: AgentCapability, executor_type: str | None = None) -> str:
    chosen = (executor_type or capability.executor_type or "mock").strip().lower()
    return chosen or "mock"


def capability_to_dict(capability: AgentCapability) -> dict[str, object]:
    return {
        "capability_id": capability.capability_id,
        "capability_name": capability.capability_name,
        "capability_type": capability.capability_type,
        "description": capability.description,
        "executor_type": capability.executor_type,
        "risk_level": capability.risk_level,
        "enabled": capability.enabled,
        "readonly": capability.readonly,
        "requires_boss_approval": capability.requires_boss_approval,
        "requires_security_audit": capability.requires_security_audit,
        "timeout_seconds": capability.timeout_seconds,
        "max_retries": capability.max_retries,
        "input_schema_json": capability.input_schema_json,
        "output_schema_json": capability.output_schema_json,
        "allowed_employee_codes": capability_allowed_employee_codes(capability),
        "allowed_employee_count": len(capability_allowed_employee_codes(capability)),
        "executor_status": executor_status_for_capability(capability),
        "version": capability.version,
        "created_at": capability.created_at.isoformat() if capability.created_at else None,
        "updated_at": capability.updated_at.isoformat() if capability.updated_at else None,
    }


def executor_status_for_capability(capability: AgentCapability) -> str:
    if not capability.enabled:
        return "停用"
    settings = get_settings()
    executor_type = (capability.executor_type or "mock").strip().lower()
    if executor_type == "mock":
        return "就绪"
    if executor_type == "browser":
        if capability.readonly and settings.BROWSER_READONLY_ENABLED:
            return "就绪"
        if settings.BROWSER_CONTROL_ENABLED:
            return "就绪"
        return "已关闭"
    if executor_type in {"desktop"}:
        return "就绪" if settings.COMPUTER_CONTROL_ENABLED else "已关闭"
    if executor_type in {"mobile"}:
        return "就绪" if settings.MOBILE_CONTROL_ENABLED else "已关闭"
    if executor_type in {"shell"}:
        return "就绪" if settings.SHELL_EXECUTION_ENABLED else "已关闭"
    return "已关闭" if not settings.REAL_EXECUTOR_ENABLED else "就绪"
