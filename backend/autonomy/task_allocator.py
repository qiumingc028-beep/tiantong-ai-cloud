from __future__ import annotations

from typing import Any


DEFAULT_AUTONOMOUS_TEAM = ("tiancai_data", "tiance_strategy", "tianjian_test", "tiandun_ops")

TASK_TYPE_TO_TEAM = {
    "business_growth": DEFAULT_AUTONOMOUS_TEAM,
    "ecommerce_growth": DEFAULT_AUTONOMOUS_TEAM,
    "content_growth": ("tiancai_data", "tiance_strategy", "tianjian_test"),
    "deploy_validation": ("tiance_strategy", "tianjian_test", "tiandun_ops"),
    "worker_recovery": ("tianjian_test", "tiandun_ops"),
}


def allocate_task(task: dict[str, Any]) -> dict[str, Any]:
    payload = task if isinstance(task, dict) else {}
    task_type = str(payload.get("task_type") or payload.get("type") or "business_growth")
    team = TASK_TYPE_TO_TEAM.get(task_type, DEFAULT_AUTONOMOUS_TEAM)
    assignments = [
        {
            "employee_code": employee,
            "role": role_for_employee(employee),
            "order": index + 1,
            "task_type": employee_task_type(employee, task_type),
        }
        for index, employee in enumerate(team)
    ]
    return {
        "task_type": task_type,
        "strategy": "multi_agent_autonomous_allocation",
        "assignments": assignments,
        "requires_orchestrator": True,
        "requires_tian_shen": True,
    }


def role_for_employee(employee_code: str) -> str:
    return {
        "tiancai_data": "collect_context",
        "tiance_strategy": "make_strategy",
        "tianjian_test": "validate_result",
        "tiandun_ops": "ops_safety_check",
    }.get(employee_code, "assist")


def employee_task_type(employee_code: str, fallback: str) -> str:
    return {
        "tiancai_data": "data_collection",
        "tiance_strategy": "strategy_planning",
        "tianjian_test": "quality_acceptance",
        "tiandun_ops": "ops_safety_review",
    }.get(employee_code, fallback)
