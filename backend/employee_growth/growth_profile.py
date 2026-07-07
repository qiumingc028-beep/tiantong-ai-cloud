from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.employee_capability import get_employee_profile
from backend.employee_workspace.task_linkage import COMPLETED_STATUSES, FAILED_STATUSES, build_task_linkage
from backend.models import TaskCenterAuditLog


def build_employee_growth_profile(db: Session, employee_code: str) -> dict[str, Any]:
    capability_profile = get_employee_profile(employee_code)
    task_linkage = build_task_linkage(db, employee_code)
    completed_tasks = task_linkage["completed_tasks"]
    failed_tasks = task_linkage["failed_tasks"]
    risk_records = build_risk_records(task_linkage)
    total_finished = len(completed_tasks) + len(failed_tasks)
    success_rate = round(len(completed_tasks) / total_finished, 4) if total_finished else 0
    return {
        "employee_code": employee_code,
        "employee_name": capability_profile["employee_name"],
        "department": capability_profile["department"],
        "completed_task_count": len(completed_tasks),
        "failed_task_count": len(failed_tasks),
        "total_finished_task_count": total_finished,
        "success_rate": success_rate,
        "failure_reasons": failure_reasons(failed_tasks),
        "risk_records": risk_records,
        "skill_growth": build_skill_growth(capability_profile, task_linkage, risk_records),
        "task_status_breakdown": {
            "pending": len(task_linkage["pending_tasks"]),
            "running": len(task_linkage["running_tasks"]),
            "completed": len(completed_tasks),
            "failed": len(failed_tasks),
        },
        "learning_logs": build_learning_logs(employee_code, task_linkage),
        "safety": {
            "suggestion_only": True,
            "can_auto_modify_production_rule": False,
            "can_auto_expand_permission": False,
            "high_risk_requires_tian_shen": True,
        },
    }


def failure_reasons(failed_tasks: list[dict[str, Any]]) -> list[str]:
    reasons = []
    for task in failed_tasks:
        reason = task.get("failure_reason") or "未记录失败原因"
        reasons.append(f"task#{task.get('task_id')}: {reason}")
    return reasons or ["暂无失败记录"]


def build_risk_records(task_linkage: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for task in task_linkage["pending_tasks"] + task_linkage["running_tasks"] + task_linkage["completed_tasks"] + task_linkage["failed_tasks"]:
        if not task.get("requires_tian_shen"):
            continue
        rows.append(
            {
                "task_id": task["task_id"],
                "title": task["title"],
                "status": task["status"],
                "risk_level": "high",
                "risk_reason": "任务涉及部署、权限、预算、广告或代码提交等高风险动作。",
                "requires_tian_shen": True,
                "can_auto_execute": False,
            }
        )
    return rows


def build_skill_growth(
    capability_profile: dict[str, Any],
    task_linkage: dict[str, Any],
    risk_records: list[dict[str, Any]],
) -> dict[str, Any]:
    current_skills = list(capability_profile.get("skills") or [])
    suggested_skills: list[str] = []
    growth_events: list[dict[str, str]] = []
    if task_linkage["completed_tasks"]:
        suggested_skills.append("knowledge_learning")
        growth_events.append({"event": "completed_task", "description": "完成任务可沉淀为 SOP 和最佳实践。"})
    if task_linkage["failed_tasks"]:
        suggested_skills.append("quality_acceptance")
        growth_events.append({"event": "failed_task", "description": "失败任务需要补充验收清单和异常处理经验。"})
    if risk_records:
        suggested_skills.append("security_approval")
        growth_events.append({"event": "risk_record", "description": "高风险任务需要强化 TianShen 审批材料。"})
    deduped = [skill for skill in dict.fromkeys(suggested_skills) if skill not in current_skills]
    return {
        "current_skills": current_skills,
        "suggested_new_skills": deduped or ["knowledge_learning"],
        "growth_events": growth_events or [{"event": "baseline", "description": "暂无历史任务，先积累执行样本。"}],
        "can_auto_add_skill": False,
        "can_auto_expand_permission": False,
    }


def build_learning_logs(employee_code: str, task_linkage: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for task in task_linkage["completed_tasks"]:
        rows.append(
            {
                "employee_code": employee_code,
                "role": "employee_growth_task",
                "status": "completed",
                "task_id": task["task_id"],
                "risk_decision": "YELLOW" if task.get("requires_tian_shen") else "GREEN",
            }
        )
    for task in task_linkage["failed_tasks"]:
        rows.append(
            {
                "employee_code": employee_code,
                "role": "employee_growth_task",
                "status": "failed",
                "task_id": task["task_id"],
                "failure_reason": task.get("failure_reason") or "任务失败",
                "risk_decision": "YELLOW" if task.get("requires_tian_shen") else "GREEN",
            }
        )
    return rows


def latest_audit_detail(db: Session, task_id: int) -> str:
    latest = (
        db.query(TaskCenterAuditLog)
        .filter(TaskCenterAuditLog.task_id == task_id)
        .order_by(TaskCenterAuditLog.id.desc())
        .first()
    )
    return latest.detail if latest and latest.detail else ""
