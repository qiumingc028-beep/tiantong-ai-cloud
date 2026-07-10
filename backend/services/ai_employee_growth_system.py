from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import AiEmployee, TaskCenterAuditLog, TaskCenterTask
from ..services.ai_employee_skills import list_employee_skill_assets
from ..services.ai_workforce_task_flow import (
    WAITING_CONFIRM_STATUSES,
    map_task_lifecycle_status,
    risk_level_for_task,
)


SUCCESS_STATUSES = {"accepted", "audited", "summarized", "completed"}
COMPLETED_STATUSES = {"accepted", "audited", "summarized", "completed"}
FAILURE_STATUSES = {"rejected", "failed", "blocked"}
SUBMITTED_STATUSES = {"result_submitted", "accepted", "audited", "summarized", "completed", "rejected", "failed", "blocked"}


def build_growth_system_overview(db: Session) -> dict:
    employees = non_legacy_employees(db)
    profiles = [employee_growth_profile(db, employee.employee_code) for employee in employees]
    available_profiles = [profile for profile in profiles if profile["growth"]["available"]]
    scores = [profile["growth"]["growth_score"] for profile in available_profiles if profile["growth"]["growth_score"] is not None]
    waiting = waiting_confirm_items(db)
    return {
        "mode": "readonly",
        "employees": {
            "total": len(employees),
            "evaluated": len(available_profiles),
            "pending_review": len(waiting),
        },
        "growth": {
            "average_score": round(sum(scores) / len(scores), 2) if scores else None,
            "available": bool(scores),
            "top_growth_employees": top_growth_employees(available_profiles),
        },
        "memory": memory_overview(db),
        "audit": audit_overview(db, waiting),
        "skill_suggestions": {
            "total": sum(len(profile["skill_suggestions"]) for profile in profiles),
            "waiting_boss_confirm": sum(
                1
                for profile in profiles
                for suggestion in profile["skill_suggestions"]
                if suggestion["boss_confirm_required"]
            ),
        },
        "security": security_payload(),
        "empty_state": empty_state(bool(scores), "暂无成长数据"),
    }


def build_employee_growth_profile(db: Session, employee_id: str) -> dict:
    return employee_growth_profile(db, employee_id)


def build_task_growth_impact(db: Session, task_id: int) -> dict | None:
    task = db.get(TaskCenterTask, task_id)
    if task is None:
        return None
    audit_logs = audit_logs_for_tasks(db, [task.id])
    lifecycle_status = map_task_lifecycle_status(task.status)
    score_delta = score_delta_for_task(task)
    return {
        "mode": "readonly",
        "task": task_payload(task),
        "impact": {
            "lifecycle_status": lifecycle_status,
            "included_in_growth_score": lifecycle_status in {"approved", "completed", "rejected"},
            "score_delta": score_delta,
            "score_reason": score_reason_for_task(task),
            "memory_candidate_type": memory_candidate_type(task),
            "risk_level": risk_level_for_task(task),
        },
        "audit": {
            "events": [audit_payload(log) for log in audit_logs],
            "event_count": len(audit_logs),
            "boss_confirm": lifecycle_status in {"approved", "completed", "rejected"},
            "security_audited": task.status == "audited" or any(log.action == "task_audited" for log in audit_logs),
        },
        "manual_confirm": {
            "boss_confirm_required": lifecycle_status == "waiting_confirm" or risk_level_for_task(task) == "high",
            "security_audited_required": risk_level_for_task(task) == "high",
            "action_available": False,
        },
        "security": security_payload(),
    }


def build_waiting_confirm_growth_items(db: Session) -> dict:
    items = waiting_confirm_items(db)
    return {
        "mode": "readonly",
        "total": len(items),
        "items": items,
        "manual_confirm": {
            "boss_confirm_required": len(items) > 0,
            "security_audited_required": any(item["risk_level"] == "high" for item in items),
            "action_available": False,
        },
        "security": security_payload(),
        "empty_state": empty_state(bool(items), "暂无待 Boss 确认成长事项"),
    }


def build_employee_skill_suggestions(db: Session, employee_id: str) -> dict:
    profile = employee_growth_profile(db, employee_id)
    return {
        "mode": "readonly",
        "employee": profile["employee"],
        "summary": {
            "total": len(profile["skill_suggestions"]),
            "waiting_boss_confirm": sum(1 for item in profile["skill_suggestions"] if item["boss_confirm_required"]),
        },
        "suggestions": profile["skill_suggestions"],
        "security": security_payload(),
        "empty_state": empty_state(bool(profile["skill_suggestions"]), "暂无技能提升建议"),
    }


def employee_growth_profile(db: Session, employee_id: str) -> dict:
    employee = find_employee(db, employee_id)
    tasks = tasks_for_employee(db, employee_id)
    audit_logs = audit_logs_for_tasks(db, [task.id for task in tasks])
    stats = task_stats(tasks)
    skills = list_employee_skill_assets(db, {"employee_id": employee_id})
    growth = growth_score(stats, skills)
    memory = memory_summary(tasks)
    audit = employee_audit_summary(tasks, audit_logs)
    suggestions = skill_suggestions(employee_id, stats, skills)
    return {
        "mode": "readonly",
        "employee": employee_payload(employee, employee_id),
        "growth": growth,
        "score_breakdown": growth["score_breakdown"],
        "tasks": stats,
        "memory": memory,
        "audit": audit,
        "skill_suggestions": suggestions,
        "manual_confirm": {
            "boss_confirm_required": any(item["boss_confirm_required"] for item in suggestions) or audit["high_risk_count"] > 0,
            "security_audited_required": audit["high_risk_count"] > 0,
            "action_available": False,
        },
        "security": security_payload(),
        "empty_state": empty_state(growth["available"], "暂无成长数据"),
    }


def non_legacy_employees(db: Session) -> list[AiEmployee]:
    return (
        db.query(AiEmployee)
        .filter(AiEmployee.is_legacy.is_(False))
        .order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc())
        .all()
    )


def find_employee(db: Session, employee_id: str) -> AiEmployee | None:
    return (
        db.query(AiEmployee)
        .filter(AiEmployee.employee_code == employee_id)
        .filter(AiEmployee.is_legacy.is_(False))
        .first()
    )


def tasks_for_employee(db: Session, employee_id: str) -> list[TaskCenterTask]:
    return (
        db.query(TaskCenterTask)
        .filter(TaskCenterTask.assigned_ai_employee_code == employee_id)
        .order_by(TaskCenterTask.updated_at.desc(), TaskCenterTask.id.desc())
        .all()
    )


def audit_logs_for_tasks(db: Session, task_ids: list[int]) -> list[TaskCenterAuditLog]:
    if not task_ids:
        return []
    return (
        db.query(TaskCenterAuditLog)
        .filter(TaskCenterAuditLog.task_id.in_(task_ids))
        .order_by(TaskCenterAuditLog.id.asc())
        .all()
    )


def task_stats(tasks: list[TaskCenterTask]) -> dict:
    total = len(tasks)
    submitted = sum(1 for task in tasks if task.status in SUBMITTED_STATUSES)
    completed = sum(1 for task in tasks if task.status in COMPLETED_STATUSES)
    success = sum(1 for task in tasks if task.status in SUCCESS_STATUSES)
    failure = sum(1 for task in tasks if task.status in FAILURE_STATUSES)
    waiting = sum(1 for task in tasks if task.status in WAITING_CONFIRM_STATUSES)
    return {
        "total": total,
        "submitted": submitted,
        "completed": completed,
        "success": success,
        "failure": failure,
        "waiting_confirm": waiting,
        "completion_rate": safe_rate(completed, total),
        "success_rate": safe_rate(success, submitted),
        "failure_rate": safe_rate(failure, total),
        "last_task_at": max_iso([iso(task.updated_at or task.created_at) for task in tasks]),
    }


def growth_score(stats: dict, skills: list[dict]) -> dict:
    if stats["total"] == 0:
        return {
            "available": False,
            "reason": "no_data",
            "growth_score": None,
            "growth_level": "no_data",
            "score_breakdown": empty_score_breakdown(),
        }
    completion_score = int((stats["completion_rate"] or 0) * 100)
    success_score = int((stats["success_rate"] or 0) * 100)
    task_quality_score = task_quality(stats)
    user_rating_score = 60 if stats["waiting_confirm"] else 75
    skill_effectiveness_score = skill_effectiveness(skills)
    risk_penalty = min(stats["failure"] * 12, 30)
    final_score = round(
        completion_score * 0.2
        + task_quality_score * 0.25
        + success_score * 0.2
        + user_rating_score * 0.15
        + skill_effectiveness_score * 0.2
        - risk_penalty,
        2,
    )
    final_score = max(0, min(100, final_score))
    return {
        "available": True,
        "reason": "",
        "growth_score": final_score,
        "growth_level": growth_level(final_score),
        "score_breakdown": {
            "task_completion_score": completion_score,
            "task_quality_score": task_quality_score,
            "success_rate_score": success_score,
            "user_rating_score": user_rating_score,
            "skill_effectiveness_score": skill_effectiveness_score,
            "risk_penalty": risk_penalty,
        },
    }


def task_quality(stats: dict) -> int:
    if stats["submitted"] == 0:
        return 50
    if stats["failure"] > 0:
        return max(35, 80 - stats["failure"] * 15)
    if stats["success"] > 0:
        return 85
    if stats["waiting_confirm"] > 0:
        return 65
    return 55


def skill_effectiveness(skills: list[dict]) -> int:
    values = [skill["success_rate"] for skill in skills if skill.get("success_rate") is not None]
    if not values:
        return 50
    return int(round((sum(values) / len(values)) * 100))


def growth_level(score: float) -> str:
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "stable"
    if score >= 50:
        return "needs_review"
    return "high_risk"


def memory_summary(tasks: list[TaskCenterTask]) -> dict:
    success_cases = [task for task in tasks if task.status in SUCCESS_STATUSES]
    failure_cases = [task for task in tasks if task.status in FAILURE_STATUSES]
    pending = [task for task in tasks if task.status in WAITING_CONFIRM_STATUSES]
    return {
        "success_case_candidates": len(success_cases),
        "failure_case_candidates": len(failure_cases),
        "pending_candidates": len(pending),
        "items": [memory_candidate(task) for task in success_cases[:5] + failure_cases[:5] + pending[:5]],
    }


def memory_candidate(task: TaskCenterTask) -> dict:
    return {
        "task_id": task.id,
        "task_title": task.title,
        "candidate_type": memory_candidate_type(task),
        "status": "candidate",
        "risk_level": risk_level_for_task(task),
        "boss_confirm_required": task.status in WAITING_CONFIRM_STATUSES or risk_level_for_task(task) == "high",
        "security_audited_required": risk_level_for_task(task) == "high",
    }


def memory_candidate_type(task: TaskCenterTask) -> str:
    if task.status in SUCCESS_STATUSES:
        return "success_case"
    if task.status in FAILURE_STATUSES:
        return "failure_case"
    if task.status in WAITING_CONFIRM_STATUSES:
        return "pending_review"
    return "task_memory"


def employee_audit_summary(tasks: list[TaskCenterTask], audit_logs: list[TaskCenterAuditLog]) -> dict:
    high_risk_tasks = [task for task in tasks if risk_level_for_task(task) == "high"]
    return {
        "event_count": len(audit_logs),
        "high_risk_count": len(high_risk_tasks),
        "boss_confirm_count": sum(1 for task in tasks if map_task_lifecycle_status(task.status) in {"approved", "completed", "rejected"}),
        "security_audit_count": sum(1 for log in audit_logs if log.action == "task_audited"),
        "recent_events": [audit_payload(log) for log in audit_logs[-10:]],
    }


def skill_suggestions(employee_id: str, stats: dict, skills: list[dict]) -> list[dict]:
    suggestions = []
    if stats["failure"] > 0:
        suggestions.append(
            suggestion_payload(
                employee_id,
                "risk_control",
                "复盘失败任务",
                "存在失败或阻塞任务，建议进行人工复盘。",
                "high",
            )
        )
    if stats["waiting_confirm"] > 0:
        suggestions.append(
            suggestion_payload(
                employee_id,
                "review",
                "处理待确认任务",
                "存在等待 Boss 确认的任务结果，暂不计入正式成长评分。",
                "medium",
            )
        )
    low_success_skills = [skill for skill in skills if skill.get("success_rate") is not None and skill["success_rate"] < 0.7]
    for skill in low_success_skills[:3]:
        suggestions.append(
            suggestion_payload(
                employee_id,
                "skill_improvement",
                f"优化 {skill['skill_name']}",
                "该技能成功率偏低，建议人工评估训练资料和使用边界。",
                "medium",
                skill,
            )
        )
    return suggestions


def suggestion_payload(employee_id: str, suggestion_type: str, title: str, reason: str, risk_level: str, skill: dict | None = None) -> dict:
    return {
        "employee_id": employee_id,
        "suggestion_type": suggestion_type,
        "title": title,
        "reason": reason,
        "risk_level": risk_level,
        "skill_id": skill.get("skill_id") if skill else None,
        "skill_name": skill.get("skill_name") if skill else None,
        "status": "draft",
        "boss_confirm_required": True,
        "security_audited_required": risk_level == "high",
        "action_available": False,
    }


def waiting_confirm_items(db: Session) -> list[dict]:
    tasks = (
        db.query(TaskCenterTask)
        .filter(TaskCenterTask.status.in_(WAITING_CONFIRM_STATUSES))
        .order_by(TaskCenterTask.updated_at.desc(), TaskCenterTask.id.desc())
        .all()
    )
    return [
        {
            "item_type": "task_result",
            "task": task_payload(task),
            "employee_id": task.assigned_ai_employee_code,
            "risk_level": risk_level_for_task(task),
            "boss_confirm_required": True,
            "security_audited_required": risk_level_for_task(task) == "high",
            "action_available": False,
        }
        for task in tasks
    ]


def memory_overview(db: Session) -> dict:
    tasks = db.query(TaskCenterTask).filter(TaskCenterTask.assigned_ai_employee_code.isnot(None)).all()
    return {
        "success_cases": sum(1 for task in tasks if task.status in SUCCESS_STATUSES),
        "failure_cases": sum(1 for task in tasks if task.status in FAILURE_STATUSES),
        "pending_candidates": sum(1 for task in tasks if task.status in WAITING_CONFIRM_STATUSES),
    }


def audit_overview(db: Session, waiting: list[dict]) -> dict:
    tasks = db.query(TaskCenterTask).filter(TaskCenterTask.assigned_ai_employee_code.isnot(None)).all()
    return {
        "events": db.query(TaskCenterAuditLog).count(),
        "high_risk": sum(1 for task in tasks if risk_level_for_task(task) == "high"),
        "waiting_boss_confirm": len(waiting),
    }


def top_growth_employees(profiles: list[dict]) -> list[dict]:
    ordered = sorted(profiles, key=lambda profile: profile["growth"]["growth_score"] or 0, reverse=True)
    return [
        {
            "employee_id": profile["employee"]["employee_id"],
            "employee_name": profile["employee"]["employee_name"],
            "growth_score": profile["growth"]["growth_score"],
            "growth_level": profile["growth"]["growth_level"],
        }
        for profile in ordered[:5]
    ]


def task_payload(task: TaskCenterTask) -> dict:
    return {
        "task_id": task.id,
        "title": task.title,
        "employee_id": task.assigned_ai_employee_code,
        "employee_name": task.assigned_ai_employee_name,
        "task_center_status": task.status,
        "lifecycle_status": map_task_lifecycle_status(task.status),
        "priority": task.priority,
        "created_at": iso(task.created_at),
        "updated_at": iso(task.updated_at),
    }


def employee_payload(employee: AiEmployee | None, employee_id: str) -> dict:
    return {
        "employee_id": employee.employee_code if employee else employee_id,
        "employee_name": employee.employee_name if employee else employee_id,
        "department": employee.legion if employee and employee.legion else "未分配部门",
        "role": employee.duty if employee and employee.duty else "",
        "status": employee.status if employee else "unknown",
    }


def audit_payload(log: TaskCenterAuditLog) -> dict:
    return {
        "id": log.id,
        "task_id": log.task_id,
        "action": log.action,
        "from_status": log.from_status,
        "to_status": log.to_status,
        "created_at": iso(log.created_at),
    }


def score_delta_for_task(task: TaskCenterTask) -> float:
    if task.status in SUCCESS_STATUSES:
        return 5.0
    if task.status in FAILURE_STATUSES:
        return -8.0
    if task.status in WAITING_CONFIRM_STATUSES:
        return 0.0
    return 0.0


def score_reason_for_task(task: TaskCenterTask) -> str:
    if task.status in SUCCESS_STATUSES:
        return "任务已通过验收或审计，可作为正向成长证据。"
    if task.status in FAILURE_STATUSES:
        return "任务被拒绝、失败或阻塞，需要进入风险复盘。"
    if task.status in WAITING_CONFIRM_STATUSES:
        return "任务等待 Boss 确认，暂不计入正式成长评分。"
    return "任务尚未形成可评价结果。"


def empty_score_breakdown() -> dict:
    return {
        "task_completion_score": 0,
        "task_quality_score": 0,
        "success_rate_score": 0,
        "user_rating_score": 0,
        "skill_effectiveness_score": 0,
        "risk_penalty": 0,
    }


def security_payload() -> dict:
    return {
        "readonly": True,
        "boss_confirm_required": True,
        "security_audited_required": True,
        "execution_engine_called": False,
        "openclaw_connected": False,
        "n8n_connected": False,
        "auto_learning": False,
        "auto_skill_upgrade": False,
        "auto_permission_change": False,
        "auto_task_execution": False,
    }


def empty_state(available: bool, message: str) -> dict:
    return {"available": available, "message": "" if available else message}


def safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def max_iso(values: list[str | None]) -> str | None:
    present = [value for value in values if value]
    return max(present) if present else None


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
