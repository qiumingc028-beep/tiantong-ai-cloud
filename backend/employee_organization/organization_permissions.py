from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sqlalchemy.orm import Session

from backend.brain_orchestrator.planner import resolve_graph_ownership
from backend.models import AiEmployee
from backend.security.tian_shen import evaluate_command
from backend.task_center_ownership import SESSION_USER_KEY

from .department_system import DEPARTMENT_LEADS
from .org_relationships import manager_for


def build_organization_permission_matrix(db: Session) -> list[dict[str, Any]]:
    employees = (
        db.query(AiEmployee)
        .filter(AiEmployee.is_legacy.is_(False))
        .order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc())
        .all()
    )
    user = db.info.get(SESSION_USER_KEY)
    scope = asdict(resolve_graph_ownership(db, user)) if user is not None else None
    return [permission_row(employee, audit_scope=scope) for employee in employees]


def permission_row(employee: AiEmployee, *, audit_scope: dict[str, Any] | None = None) -> dict[str, Any]:
    role = organization_role(employee)
    return {
        "employee_code": employee.employee_code,
        "employee_name": employee.employee_name,
        "department": employee.legion,
        "organization_role": role,
        "manager_employee_code": manager_for(employee),
        "can_execute_authorized_task": True,
        "can_assign_task": role in {"top_dispatcher", "department_leader"},
        "can_dispatch_company_wide": role == "top_dispatcher",
        "can_change_permission": False,
        "can_modify_employee_config": False,
        "permission_change_gate": permission_change_gate(employee, role, audit_scope=audit_scope),
        "safety": {
            "permission_change_requires_tian_shen": True,
            "can_auto_expand_permission": False,
            "can_auto_modify_permission": False,
        },
    }


def organization_role(employee: AiEmployee) -> str:
    if employee.employee_code == "tiantong":
        return "top_dispatcher"
    if employee.employee_code in set(DEPARTMENT_LEADS.values()):
        return "department_leader"
    return "regular_ai_employee"


def permission_change_gate(
    employee: AiEmployee, role: str, *, audit_scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "source": "employee_organization",
        "target": "tian_shen",
        "action": "review_permission_change",
        "requires_boss_confirmation": True,
        "audit_scope": audit_scope,
        "payload": {
            "employee_code": employee.employee_code,
            "organization_role": role,
            "requested_change": "permission_change_preview",
            "review_only": True,
            "can_auto_expand_permission": False,
            "can_auto_modify_permission": False,
        },
    }
    return evaluate_command(event, {"source": "employee_organization", "target": "tian_shen", "handler": "permission_review"})
