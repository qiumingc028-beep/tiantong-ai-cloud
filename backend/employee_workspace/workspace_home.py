from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.employee_capability import get_employee_profile
from backend.models import AiEmployee

from .growth_panel import build_growth_panel
from .task_linkage import build_task_linkage


def build_employee_home(db: Session, employee_code: str) -> dict[str, Any]:
    employee = db.query(AiEmployee).filter(AiEmployee.employee_code == employee_code).first()
    profile = get_employee_profile(employee_code)
    if employee:
        profile = {
            **profile,
            "employee_name": employee.employee_name or profile["employee_name"],
            "department": employee.legion or profile["department"],
            "duty": employee.duty or "",
            "status": employee.status,
        }
    else:
        profile = {**profile, "duty": "", "status": "active"}
    task_linkage = build_task_linkage(db, employee_code)
    growth = build_growth_panel(db, employee_code, task_linkage)
    return {
        "employee_home": {
            "identity": {
                "employee_code": profile["employee_code"],
                "employee_name": profile["employee_name"],
                "department": profile["department"],
                "duty": profile.get("duty") or "",
                "status": profile.get("status") or "active",
            },
            "capability_tags": profile["capability_tags"],
            "skill_list": profile["skills"],
            "permissions": profile["permissions"],
            "current_task": task_linkage["current_task"],
            "history_completed_tasks": task_linkage["completed_tasks"],
        },
        "task_center_linkage": task_linkage,
        "growth": growth,
        "safety": {
            "authorized_tasks_only": True,
            "can_expand_permission": False,
            "high_risk_requires_tian_shen": True,
        },
    }
