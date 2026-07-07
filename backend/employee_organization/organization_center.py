from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.employee_capability import list_employee_profiles
from backend.employee_performance import build_ai_employee_business_board

from .department_system import build_department_system
from .org_relationships import build_employee_relationships
from .organization_permissions import build_organization_permission_matrix


def build_employee_organization_center(db: Session) -> dict[str, Any]:
    departments = build_department_system(db)
    relationships = build_employee_relationships(db)
    permissions = build_organization_permission_matrix(db)
    performance_board = build_ai_employee_business_board(db)
    capability_profiles = list_employee_profiles()
    return {
        "center": "AI Employee Organization Center",
        "mode": "readonly_organization_structure",
        "summary": {
            "department_count": len(departments),
            "employee_count": sum(row["employee_count"] for row in departments),
            "department_leader_count": sum(1 for row in permissions if row["organization_role"] == "department_leader"),
            "top_dispatcher": "tiantong",
            "permission_change_requires_tian_shen": True,
        },
        "departments": departments,
        "employee_relationships": relationships,
        "organization_permissions": permissions,
        "capability_connection": {
            "source": "Employee Capability Center",
            "profile_count": len(capability_profiles),
            "profiles": capability_profiles,
        },
        "workspace_connection": {
            "source": "Employee Workspace",
            "relationship_view_available": True,
            "can_auto_execute_task": False,
        },
        "performance_connection": {
            "source": "Employee Performance Center",
            "board": performance_board,
        },
        "safety": {
            "analysis_only": True,
            "permission_change_requires_tian_shen": True,
            "can_auto_expand_permission": False,
            "can_auto_modify_employee_config": False,
            "can_auto_change_organization": False,
        },
    }
