from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.employee_capability import get_employee_profile
from backend.models import AiEmployee, TaskCenterTask


COMPLETED_STATUSES = {"accepted", "audited", "completed", "summarized"}
FAILED_STATUSES = {"rejected", "failed", "blocked"}
RUNNING_STATUSES = {"in_progress", "running"}
ACTIVE_STATUSES = {"assigned", "in_progress", "running", "result_submitted"}
RISK_KEYWORDS = ("deploy", "部署", "git push", "权限", "花钱", "预算", "广告")


def build_employee_performance_stats(db: Session) -> list[dict[str, Any]]:
    employees = (
        db.query(AiEmployee)
        .filter(AiEmployee.is_legacy.is_(False))
        .order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc())
        .all()
    )
    tasks = db.query(TaskCenterTask).order_by(TaskCenterTask.id.desc()).limit(500).all()
    return [build_single_employee_stats(employee, tasks) for employee in employees]


def build_single_employee_stats(employee: AiEmployee, tasks: list[TaskCenterTask]) -> dict[str, Any]:
    employee_tasks = [task for task in tasks if task.assigned_ai_employee_code == employee.employee_code]
    completed = [task for task in employee_tasks if task.status in COMPLETED_STATUSES]
    failed = [task for task in employee_tasks if task.status in FAILED_STATUSES]
    running = [task for task in employee_tasks if task.status in RUNNING_STATUSES]
    active = [task for task in employee_tasks if task.status in ACTIVE_STATUSES]
    risky = [task for task in employee_tasks if task_requires_tian_shen(task)]
    finished_count = len(completed) + len(failed)
    success_rate = round(len(completed) / finished_count, 4) if finished_count else 0
    risk_rate = round(len(risky) / len(employee_tasks), 4) if employee_tasks else 0
    average_duration_hours = average_task_duration_hours(completed + failed)
    profile = get_employee_profile(employee.employee_code)
    return {
        "employee_code": employee.employee_code,
        "employee_name": employee.employee_name,
        "department": employee.legion,
        "status": employee.status,
        "capability_tags": profile.get("capability_tags") or [],
        "skill_list": profile.get("skills") or [],
        "assigned_task_count": len(employee_tasks),
        "completed_task_count": len(completed),
        "success_rate": success_rate,
        "average_duration_hours": average_duration_hours,
        "failed_task_count": len(failed),
        "risk_count": len(risky),
        "risk_rate": risk_rate,
        "running_task_count": len(running),
        "active_task_count": len(active),
        "today_task_count": today_task_count(employee_tasks),
        "estimated_cost": estimated_cost(employee_tasks, risky),
        "optimization_suggestions": optimization_suggestions(success_rate, len(failed), len(risky), average_duration_hours),
        "safety": {
            "analysis_only": True,
            "can_auto_adjust_permission": False,
            "can_auto_modify_employee_config": False,
            "high_risk_requires_tian_shen": True,
        },
    }


def task_requires_tian_shen(task: TaskCenterTask) -> bool:
    text = f"{task.title} {task.description or ''}".lower()
    return any(keyword in text for keyword in RISK_KEYWORDS)


def average_task_duration_hours(tasks: list[TaskCenterTask]) -> float:
    durations = []
    for task in tasks:
        if not task.created_at or not task.updated_at:
            continue
        duration = task.updated_at - task.created_at
        durations.append(max(duration.total_seconds() / 3600, 0))
    return round(sum(durations) / len(durations), 2) if durations else 0


def today_task_count(tasks: list[TaskCenterTask]) -> int:
    today = datetime.now(timezone.utc).date()
    count = 0
    for task in tasks:
        if task.created_at and task.created_at.date() == today:
            count += 1
    return count


def estimated_cost(tasks: list[TaskCenterTask], risky: list[TaskCenterTask]) -> dict[str, Any]:
    base_units = len(tasks) * 0.2
    risk_units = len(risky) * 0.15
    return {
        "unit": "mock_cost_unit",
        "estimated_total": round(base_units + risk_units, 2),
        "calculation_mode": "readonly_estimate",
        "can_auto_spend_money": False,
    }


def optimization_suggestions(success_rate: float, failed_count: int, risk_count: int, average_duration_hours: float) -> list[str]:
    suggestions = []
    if failed_count:
        suggestions.append("复盘失败任务，将失败原因沉淀到员工成长中心和天藏。")
    if risk_count:
        suggestions.append("高风险任务必须补充 TianShen 审批材料。")
    if average_duration_hours > 24:
        suggestions.append("任务平均耗时偏长，建议拆分步骤并明确验收条件。")
    if success_rate >= 0.9 and not suggestions:
        suggestions.append("表现稳定，可沉淀为最佳实践和 SOP。")
    return suggestions or ["继续积累任务样本，观察完成率、风险率和成本趋势。"]
