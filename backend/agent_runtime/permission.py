from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AiEmployee, User
from .constants import CAPABILITY_TYPES, EXECUTOR_TYPES, RISK_LEVELS
from .exceptions import ApprovalRequiredError, CapabilityNotFoundError, ExecutorUnavailableError, InputValidationError, PermissionDeniedError
from .models import AgentCapability, AgentExecution
from .registry import capability_allowed_employee_codes, normalize_capability_payload, resolve_capability, resolve_executor_type


@dataclass(slots=True)
class PermissionContext:
    user: User
    employee: AiEmployee
    capability: AgentCapability
    executor_type: str
    risk_level: str
    approval_required: bool
    security_audit_required: bool
    allowed: bool
    reason: str


def evaluate_permission(
    db: Session,
    user: User,
    employee: AiEmployee,
    capability_id: str,
    input_payload: dict | None = None,
    executor_type: str | None = None,
) -> PermissionContext:
    capability = resolve_capability(db, capability_id)
    if not capability:
        raise CapabilityNotFoundError("能力不存在")
    if not capability.enabled:
        raise PermissionDeniedError("能力已停用")
    if not employee or getattr(employee, "status", "") != "active" or getattr(employee, "is_legacy", False):
        raise PermissionDeniedError("AI 员工不可用")
    allowed_employee_codes = capability_allowed_employee_codes(capability)
    if allowed_employee_codes and employee.employee_code not in allowed_employee_codes:
        raise PermissionDeniedError("当前 AI 员工无权使用该能力")

    chosen_executor = resolve_executor_type(capability, executor_type)
    settings = get_settings()
    if chosen_executor != "mock" and not settings.REAL_EXECUTOR_ENABLED:
        raise ExecutorUnavailableError("真实执行器已关闭")
    if chosen_executor == "desktop" and not settings.COMPUTER_CONTROL_ENABLED:
        raise ExecutorUnavailableError("电脑控制能力已关闭")
    if chosen_executor == "mobile" and not settings.MOBILE_CONTROL_ENABLED:
        raise ExecutorUnavailableError("手机控制能力已关闭")
    if chosen_executor == "browser" and not settings.BROWSER_CONTROL_ENABLED:
        raise ExecutorUnavailableError("浏览器控制能力已关闭")
    if chosen_executor == "shell" and not settings.SHELL_EXECUTION_ENABLED:
        raise ExecutorUnavailableError("Shell 执行能力已关闭")

    normalized_payload = normalize_capability_payload(input_payload)
    if capability.input_schema_json:
        validate_schema_like_payload(capability.input_schema_json, normalized_payload)

    approval_required = bool(capability.requires_boss_approval or capability.risk_level in {"high", "critical"})
    security_audit_required = bool(capability.requires_security_audit or capability.risk_level in {"medium", "high", "critical"})
    if capability.risk_level == "critical":
        raise PermissionDeniedError("极高风险能力默认禁止")

    return PermissionContext(
        user=user,
        employee=employee,
        capability=capability,
        executor_type=chosen_executor,
        risk_level=capability.risk_level,
        approval_required=approval_required,
        security_audit_required=security_audit_required,
        allowed=True,
        reason="校验通过",
    )


def validate_schema_like_payload(schema_json: str, payload: dict[str, object]) -> None:
    try:
        schema = json.loads(schema_json)
    except Exception as exc:
        raise InputValidationError("能力输入 Schema 无法解析") from exc
    required = schema.get("required", [])
    if isinstance(required, list):
        for field in required:
            if field not in payload:
                raise InputValidationError(f"缺少必填字段：{field}")


def ensure_agent_runtime_enabled() -> None:
    if not get_settings().AGENT_RUNTIME_ENABLED:
        raise ExecutorUnavailableError("Agent Runtime 已关闭")
