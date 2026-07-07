from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from backend.employee_capability import get_employee_profile
from backend.models import AiEmployee, TaskCenterTask


DEPARTMENT_LEADS = {
    "研发交付军团": "tiantong",
    "数据资产军团": "tianshu",
    "经营策略军团": "tiance_strategy",
    "内容创意军团": "tianbo",
    "电商经营军团": "tianshang",
    "增长投放军团": "tiantou",
    "质量验收军团": "tianjian_test",
    "部署运维军团": "tiandun_ops",
}


def build_department_system(db: Session) -> list[dict[str, Any]]:
    employees = (
        db.query(AiEmployee)
        .filter(AiEmployee.is_legacy.is_(False))
        .order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc())
        .all()
    )
    tasks = db.query(TaskCenterTask).order_by(TaskCenterTask.id.desc()).limit(500).all()
    grouped: dict[str, list[AiEmployee]] = defaultdict(list)
    for employee in employees:
        grouped[employee.legion or "未分配军团"].append(employee)
    return [department_row(db, department, rows, tasks) for department, rows in sorted(grouped.items())]


def department_row(db: Session, department: str, employees: list[AiEmployee], tasks: list[TaskCenterTask]) -> dict[str, Any]:
    lead_code = resolve_department_lead(department, employees)
    employee_codes = [employee.employee_code for employee in employees]
    department_tasks = [task for task in tasks if task.assigned_ai_employee_code in employee_codes]
    return {
        "department": department,
        "department_name": department,
        "leader_employee_code": lead_code,
        "leader_employee_name": employee_name(lead_code, employees),
        "employee_count": len(employees),
        "employees": [employee_brief(employee) for employee in employees],
        "task_count": len(department_tasks),
        "active_task_count": sum(1 for task in department_tasks if task.status in {"assigned", "in_progress", "running", "result_submitted"}),
        "capability_tags": sorted({tag for employee in employees for tag in get_employee_profile(employee.employee_code).get("capability_tags", [])}),
        "safety": {
            "readonly_department_structure": True,
            "can_auto_change_leader": False,
            "can_auto_move_employee": False,
        },
    }


def resolve_department_lead(department: str, employees: list[AiEmployee]) -> str:
    configured = DEPARTMENT_LEADS.get(department)
    if configured and any(employee.employee_code == configured for employee in employees):
        return configured
    if any(employee.employee_code == "tiantong" for employee in employees):
        return "tiantong"
    return employees[0].employee_code if employees else ""


def employee_name(employee_code: str, employees: list[AiEmployee]) -> str:
    for employee in employees:
        if employee.employee_code == employee_code:
            return employee.employee_name
    profile = get_employee_profile(employee_code)
    return profile.get("employee_name") or employee_code


def employee_brief(employee: AiEmployee) -> dict[str, Any]:
    profile = get_employee_profile(employee.employee_code)
    return {
        "employee_code": employee.employee_code,
        "employee_name": employee.employee_name,
        "department": employee.legion,
        "duty": employee.duty or "",
        "status": employee.status,
        "capability_tags": profile.get("capability_tags") or [],
        "skill_list": profile.get("skills") or [],
    }
