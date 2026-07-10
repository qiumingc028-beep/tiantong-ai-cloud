from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..models import AiEmployee, TaskCenterAuditLog, TaskCenterReview, TaskCenterTask
from ..services.ai_employee_growth_system import (
    FAILURE_STATUSES,
    SUCCESS_STATUSES,
    build_employee_growth_profile,
    build_growth_system_overview,
    memory_candidate_type,
    score_delta_for_task,
    score_reason_for_task,
)
from ..services.ai_employee_skills import list_employee_skill_assets
from ..services.ai_workforce_task_flow import WAITING_CONFIRM_STATUSES, map_task_lifecycle_status, risk_level_for_task


def build_growth_overview(db: Session) -> dict:
    employees = non_legacy_employees(db)
    system = build_growth_system_overview(db)
    task_counts = task_completion_overview(db)
    skill_assets = list_employee_skill_assets(db, {})
    risk = risk_overview(db)
    return {
        "mode": "readonly",
        "employees": {
            "total": len(employees),
            "active": sum(1 for employee in employees if employee.status == "active"),
            "evaluated": system.get("employees", {}).get("evaluated", 0),
            "pending_review": system.get("employees", {}).get("pending_review", 0),
        },
        "average_growth": {
            "score": system.get("growth", {}).get("average_score"),
            "status": average_growth_status(system.get("growth", {}).get("average_score")),
            "available": bool(system.get("growth", {}).get("available")),
        },
        "tasks": task_counts,
        "skills": skill_overview(skill_assets),
        "risk": risk,
        "security": security_payload(),
        "empty_state": {
            "available": bool(system.get("growth", {}).get("available")),
            "message": "" if system.get("growth", {}).get("available") else "暂无成长数据",
        },
    }


def build_employee_growth_detail(db: Session, employee_id: str) -> dict:
    profile = build_employee_growth_profile(db, employee_id)
    skills = list_employee_skill_assets(db, {"employee_id": employee_id})
    audit = audit_summary_for_employee(db, employee_id)
    timeline = growth_timeline(db, employee_id)
    return {
        "mode": "readonly",
        "employee": profile["employee"],
        "skill_summary": skill_overview(skills),
        "task_summary": profile["tasks"],
        "audit_summary": audit,
        "growth_summary": {
            "available": profile["growth"]["available"],
            "growth_score": profile["growth"]["growth_score"],
            "growth_level": profile["growth"]["growth_level"],
            "score_breakdown": profile["score_breakdown"],
        },
        "memory_summary": profile["memory"],
        "recent_timeline": timeline[:10],
        "security": security_payload(),
        "empty_state": profile["empty_state"],
    }


def build_employee_growth_timeline(db: Session, employee_id: str) -> dict:
    employee = find_employee(db, employee_id)
    timeline = growth_timeline(db, employee_id)
    return {
        "mode": "readonly",
        "employee": employee_payload(employee, employee_id),
        "timeline": timeline,
        "summary": {
            "total": len(timeline),
            "task_events": sum(1 for item in timeline if item["event_type"] == "task"),
            "audit_events": sum(1 for item in timeline if item["event_type"] == "audit"),
            "memory_events": sum(1 for item in timeline if item["event_type"] == "memory"),
            "growth_events": sum(1 for item in timeline if item["event_type"] == "growth"),
        },
        "security": security_payload(),
        "empty_state": {
            "available": bool(timeline),
            "message": "" if timeline else "暂无成长时间线数据",
        },
    }


def growth_timeline(db: Session, employee_id: str) -> list[dict]:
    tasks = tasks_for_employee(db, employee_id)
    task_ids = [task.id for task in tasks]
    audits = audit_logs_for_tasks(db, task_ids)
    reviews = reviews_for_tasks(db, task_ids)
    events: list[dict] = []
    for task in tasks:
        events.append(task_event(task))
        if task.status in SUCCESS_STATUSES or task.status in FAILURE_STATUSES or task.status in WAITING_CONFIRM_STATUSES:
            events.append(memory_event(task))
            events.append(growth_event(task))
    for log in audits:
        events.append(audit_event(log))
    for review in reviews:
        events.append(review_event(review))
    events.sort(key=lambda item: item.get("time") or "", reverse=True)
    return events


def task_completion_overview(db: Session) -> dict:
    rows = db.query(TaskCenterTask).all()
    total = len(rows)
    completed = sum(1 for task in rows if task.status in SUCCESS_STATUSES)
    failed = sum(1 for task in rows if task.status in FAILURE_STATUSES)
    waiting = sum(1 for task in rows if task.status in WAITING_CONFIRM_STATUSES)
    return {
        "total": total,
        "completed": completed,
        "failed": failed,
        "waiting_confirm": waiting,
        "completion_rate": safe_rate(completed, total),
    }


def skill_overview(skills: list[dict]) -> dict:
    success_values = [skill.get("success_rate") for skill in skills if skill.get("success_rate") is not None]
    return {
        "total": len(skills),
        "employee_skill_count": len({skill.get("employee_id") for skill in skills if skill.get("employee_id")}),
        "high_risk": sum(1 for skill in skills if skill.get("risk_level") == "high"),
        "average_success_rate": round(sum(success_values) / len(success_values), 4) if success_values else None,
    }


def risk_overview(db: Session) -> dict:
    tasks = db.query(TaskCenterTask).all()
    high_risk = [task for task in tasks if risk_level_for_task(task) == "high"]
    medium_risk = [task for task in tasks if risk_level_for_task(task) == "medium"]
    return {
        "high": len(high_risk),
        "medium": len(medium_risk),
        "waiting_boss_confirm": sum(1 for task in tasks if task.status in WAITING_CONFIRM_STATUSES),
        "boss_confirm": True,
        "security_audited": True,
    }


def audit_summary_for_employee(db: Session, employee_id: str) -> dict:
    task_ids = [task.id for task in tasks_for_employee(db, employee_id)]
    audits = audit_logs_for_tasks(db, task_ids)
    reviews = reviews_for_tasks(db, task_ids)
    return {
        "audit_events": len(audits),
        "review_events": len(reviews),
        "boss_confirm_events": sum(1 for review in reviews if review.review_status in {"accepted", "rejected", "audited"}),
        "security_audited_events": sum(1 for review in reviews if review.review_type == "audit"),
        "recent_events": [audit_payload(log) for log in audits[-10:]],
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


def reviews_for_tasks(db: Session, task_ids: list[int]) -> list[TaskCenterReview]:
    if not task_ids:
        return []
    return (
        db.query(TaskCenterReview)
        .filter(TaskCenterReview.task_id.in_(task_ids))
        .order_by(TaskCenterReview.id.asc())
        .all()
    )


def task_event(task: TaskCenterTask) -> dict:
    return {
        "event_type": "task",
        "task_id": task.id,
        "title": task.title,
        "status": map_task_lifecycle_status(task.status),
        "source_status": task.status,
        "summary": "任务状态进入成长数据链路",
        "time": iso(task.updated_at or task.created_at),
        "risk_level": risk_level_for_task(task),
    }


def audit_event(log: TaskCenterAuditLog) -> dict:
    return {
        "event_type": "audit",
        "task_id": log.task_id,
        "title": log.action,
        "status": map_task_lifecycle_status(log.to_status or log.from_status),
        "source_status": log.to_status or log.from_status,
        "summary": log.detail or "Task Center 审计记录",
        "time": iso(log.created_at),
        "risk_level": "high" if (log.to_status or "") in FAILURE_STATUSES else "low",
    }


def review_event(review: TaskCenterReview) -> dict:
    return {
        "event_type": "audit",
        "task_id": review.task_id,
        "title": f"{review.review_type}_review",
        "status": review.review_status,
        "source_status": review.review_status,
        "summary": review.comment or "审核记录",
        "time": iso(review.created_at),
        "risk_level": "high" if review.review_status == "rejected" else "low",
    }


def memory_event(task: TaskCenterTask) -> dict:
    candidate_type = memory_candidate_type(task)
    return {
        "event_type": "memory",
        "task_id": task.id,
        "title": candidate_type,
        "status": "candidate",
        "source_status": task.status,
        "summary": "由任务结果推导的经验候选",
        "time": iso(task.updated_at or task.created_at),
        "risk_level": risk_level_for_task(task),
    }


def growth_event(task: TaskCenterTask) -> dict:
    return {
        "event_type": "growth",
        "task_id": task.id,
        "title": "growth_score_delta",
        "status": "readonly_evaluated",
        "source_status": task.status,
        "summary": score_reason_for_task(task),
        "score_delta": score_delta_for_task(task),
        "time": iso(task.updated_at or task.created_at),
        "risk_level": risk_level_for_task(task),
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


def average_growth_status(score: float | None) -> str:
    if score is None:
        return "no_data"
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "stable"
    if score >= 50:
        return "needs_review"
    return "high_risk"


def security_payload() -> dict:
    return {
        "readonly": True,
        "boss_confirm": True,
        "boss_confirm_required": True,
        "security_audited": True,
        "security_audited_required": True,
        "execution_engine_called": False,
        "openclaw_connected": False,
        "n8n_connected": False,
        "auto_learning": False,
        "auto_skill_upgrade": False,
        "auto_permission_change": False,
        "auto_task_execution": False,
    }


def safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
