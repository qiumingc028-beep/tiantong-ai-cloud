from __future__ import annotations

from dataclasses import dataclass

from backend.auth_data import normalize_role
from backend.config import get_settings
from backend.ai_employees.registry import normalize_employee_code

from .constants import (
    ALLOWED_ARCHIVER_EMPLOYEE_CODES,
    ALLOWED_PUBLISHER_EMPLOYEE_CODES,
    ALLOWED_REVIEWER_EMPLOYEE_CODES,
    ALLOWED_SUBMITTER_EMPLOYEE_CODES,
)


@dataclass(frozen=True)
class KnowledgePermissionResult:
    allowed: bool
    reason: str = ""


def knowledge_flags_enabled() -> bool:
    return get_settings().KNOWLEDGE_CENTER_ENABLED


def can_manage_user(user) -> bool:
    return normalize_role(getattr(user, "role", "")) in {"owner", "admin"}


def can_view_all_user(user) -> bool:
    return can_manage_user(user)


def can_submit_employee(employee_code: str | None) -> KnowledgePermissionResult:
    normalized = normalize_employee_code(employee_code)
    if not normalized:
        return KnowledgePermissionResult(False, "员工编号缺失")
    if normalized in ALLOWED_SUBMITTER_EMPLOYEE_CODES:
        return KnowledgePermissionResult(True, "")
    return KnowledgePermissionResult(False, "无知识候选提交权限")


def can_review_employee(employee_code: str | None) -> KnowledgePermissionResult:
    normalized = normalize_employee_code(employee_code)
    if normalized in ALLOWED_REVIEWER_EMPLOYEE_CODES:
        return KnowledgePermissionResult(True, "")
    return KnowledgePermissionResult(False, "无知识审核权限")


def can_publish_employee(employee_code: str | None) -> KnowledgePermissionResult:
    normalized = normalize_employee_code(employee_code)
    if normalized in ALLOWED_PUBLISHER_EMPLOYEE_CODES:
        return KnowledgePermissionResult(True, "")
    return KnowledgePermissionResult(False, "无知识发布权限")


def can_archive_employee(employee_code: str | None) -> KnowledgePermissionResult:
    normalized = normalize_employee_code(employee_code)
    if normalized in ALLOWED_ARCHIVER_EMPLOYEE_CODES:
        return KnowledgePermissionResult(True, "")
    return KnowledgePermissionResult(False, "无知识归档权限")
