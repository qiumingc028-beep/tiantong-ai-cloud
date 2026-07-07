from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.models import AiEmployee

from .department_system import DEPARTMENT_LEADS


COLLABORATION_MAP = {
    "tiancai_data": ["tianshu", "tiance_strategy"],
    "tianshu": ["tiancai_data", "tiance_strategy"],
    "tiance_strategy": ["tiancai_data", "tianshu", "tianshang", "tiantou", "tianjian_test"],
    "tianbo": ["tianchuang", "tiance_strategy"],
    "tianchuang": ["tianbo", "tianshang"],
    "tianshang": ["tiance_strategy", "tiantou", "tianjian_test"],
    "tiantou": ["tiance_strategy", "tianshang", "tianjian_test"],
    "tianjian_test": ["tiance_strategy", "tiandun_ops"],
    "tiandun_ops": ["tianjian_test", "tiantong"],
}


def build_employee_relationships(db: Session) -> list[dict[str, Any]]:
    employees = (
        db.query(AiEmployee)
        .filter(AiEmployee.is_legacy.is_(False))
        .order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc())
        .all()
    )
    by_code = {employee.employee_code: employee for employee in employees}
    return [relationship_row(employee, by_code) for employee in employees]


def relationship_row(employee: AiEmployee, by_code: dict[str, AiEmployee]) -> dict[str, Any]:
    manager_code = manager_for(employee)
    subordinate_codes = sorted(
        code
        for code, row in by_code.items()
        if code != employee.employee_code and manager_for(row) == employee.employee_code
    )
    collaborators = [code for code in COLLABORATION_MAP.get(employee.employee_code, []) if code in by_code]
    return {
        "employee_code": employee.employee_code,
        "employee_name": employee.employee_name,
        "department": employee.legion,
        "manager_employee_code": manager_code,
        "manager_employee_name": employee_name(manager_code, by_code) if manager_code else "",
        "subordinate_employees": [employee_summary(code, by_code) for code in subordinate_codes],
        "collaboration_employees": [employee_summary(code, by_code) for code in collaborators],
        "is_top_dispatcher": employee.employee_code == "tiantong",
        "safety": {
            "readonly_relationship": True,
            "can_auto_change_manager": False,
            "can_auto_add_subordinate": False,
        },
    }


def manager_for(employee: AiEmployee) -> str:
    if employee.employee_code == "tiantong":
        return ""
    if employee.employee_code in set(DEPARTMENT_LEADS.values()):
        return "tiantong"
    return DEPARTMENT_LEADS.get(employee.legion or "", "tiantong")


def employee_name(employee_code: str, by_code: dict[str, AiEmployee]) -> str:
    employee = by_code.get(employee_code)
    return employee.employee_name if employee else employee_code


def employee_summary(employee_code: str, by_code: dict[str, AiEmployee]) -> dict[str, str]:
    employee = by_code.get(employee_code)
    if not employee:
        return {"employee_code": employee_code, "employee_name": employee_code, "department": ""}
    return {
        "employee_code": employee.employee_code,
        "employee_name": employee.employee_name,
        "department": employee.legion or "",
    }
