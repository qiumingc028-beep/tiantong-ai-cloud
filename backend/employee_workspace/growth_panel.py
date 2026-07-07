from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.employee_capability import get_employee_profile
from backend.learning_center import score_employees


def build_growth_panel(db: Session, employee_code: str, task_linkage: dict[str, Any]) -> dict[str, Any]:
    profile = get_employee_profile(employee_code)
    logs = build_learning_logs(employee_code, task_linkage)
    scores = score_employees(logs)
    score = scores[0] if scores else empty_score(employee_code)
    completed = len(task_linkage["completed_tasks"])
    failed = len(task_linkage["failed_tasks"])
    total = completed + failed
    success_rate = round(completed / total, 4) if total else 0
    return {
        "success_rate": success_rate,
        "learning_score": score,
        "optimization_suggestions": optimization_suggestions(score, task_linkage),
        "new_learning_skills": suggest_new_skills(profile, task_linkage),
        "knowledge_sources": ["TianWu Learning Center", "TianCang Knowledge Center", "AI Employee Capability Center"],
        "can_auto_expand_permission": False,
        "requires_tian_shen_for_high_risk_skill": True,
    }


def build_learning_logs(employee_code: str, task_linkage: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for task in task_linkage["completed_tasks"]:
        rows.append({"employee_code": employee_code, "role": "workspace_task", "status": "completed", "risk_decision": "GREEN"})
    for task in task_linkage["failed_tasks"]:
        rows.append(
            {
                "employee_code": employee_code,
                "role": "workspace_task",
                "status": "failed",
                "failure_reason": task.get("failure_reason") or "任务失败",
                "risk_decision": "YELLOW" if task.get("requires_tian_shen") else "GREEN",
            }
        )
    return rows


def empty_score(employee_code: str) -> dict[str, Any]:
    return {
        "employee_code": employee_code,
        "total_tasks": 0,
        "completion_rate": 0,
        "accuracy_rate": 0,
        "risk_rate": 0,
        "efficiency": 0,
        "overall_score": 0,
        "improvement_suggestion": "暂无历史任务，先积累执行样本。",
    }


def optimization_suggestions(score: dict[str, Any], task_linkage: dict[str, Any]) -> list[str]:
    suggestions = [score.get("improvement_suggestion") or "继续沉淀执行经验。"]
    if task_linkage["failed_tasks"]:
        suggestions.append("复盘失败任务，将失败原因沉淀到天藏知识库。")
    if any(task.get("requires_tian_shen") for task in task_linkage["pending_tasks"] + task_linkage["running_tasks"]):
        suggestions.append("高风险任务执行前必须补充 TianShen 审批材料。")
    return suggestions


def suggest_new_skills(profile: dict[str, Any], task_linkage: dict[str, Any]) -> list[str]:
    current = set(profile.get("skills") or [])
    suggestions = []
    if task_linkage["failed_tasks"] and "quality_acceptance" not in current:
        suggestions.append("quality_acceptance")
    if any(task.get("requires_tian_shen") for task in task_linkage["pending_tasks"] + task_linkage["failed_tasks"]) and "security_approval" not in current:
        suggestions.append("security_approval")
    if not suggestions and "knowledge_learning" not in current:
        suggestions.append("knowledge_learning")
    return suggestions
