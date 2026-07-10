from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..evolution_models import EmployeeGrowth, RiskEvent
from ..models import AiEmployee, BugCase, KnowledgeArticle, PromptLibrary, SopLibrary, TaskCenterTask, User
from ..routers import employee_capabilities, sop_skill_center


WORKING_TASK_STATUSES = {"assigned", "running", "in_progress"}
PENDING_TASK_STATUSES = {"created", "split", "assigned"}
BLOCKED_TASK_STATUSES = {"rejected", "failed", "blocked"}
REVIEW_PENDING_TASK_STATUSES = {"result_submitted"}
FROZEN_EMPLOYEE_STATUSES = {"inactive", "frozen"}
SUCCESS_TASK_STATUSES = {"accepted", "audited", "summarized"}
HIGH_RISK_LEVELS = {"high", "critical"}


def build_ai_employee_ecosystem_overview(db: Session, user: User) -> dict:
    errors: list[dict] = []
    sections = {
        "employees": safe_collect("employees", lambda: collect_employee_stats(db), default_employee_stats(), errors),
        "capability": safe_collect("capability", lambda: collect_capability_stats(db), default_capability_stats(), errors),
        "skill": safe_collect("skill", collect_skill_stats, default_skill_stats(), errors),
        "memory": safe_collect("memory", lambda: collect_memory_stats(db), default_memory_stats(), errors),
        "growth": safe_collect("growth", lambda: collect_growth_stats(db), default_growth_stats(), errors),
        "audit": safe_collect("audit", lambda: collect_audit_stats(db), default_audit_stats(), errors),
        "meeting": collect_meeting_stats(),
        "task": safe_collect("task", lambda: collect_task_stats(db), default_task_stats(), errors),
    }
    return {
        "mode": "readonly",
        "version": "ai_employee_ecosystem_overview_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **sections,
        "centers": build_center_entries(sections),
        "empty_state": build_empty_state(sections),
        "security": build_security_payload(),
        "data_sources": [
            "ai_workforce",
            "employee_capabilities",
            "sop_skill_center",
            "task_center",
            "tiancang",
            "employee_evolution",
        ],
        "errors": errors,
    }


def collect_employee_stats(db: Session) -> dict:
    employees = db.query(AiEmployee).filter(AiEmployee.is_legacy.is_(False)).all()
    active_codes = [row.employee_code for row in employees if row.status == "active"]
    working_codes: set[str] = set()
    if active_codes:
        rows = (
            db.query(TaskCenterTask.assigned_ai_employee_code)
            .filter(TaskCenterTask.assigned_ai_employee_code.in_(active_codes))
            .filter(TaskCenterTask.status.in_(WORKING_TASK_STATUSES))
            .all()
        )
        working_codes = {row.assigned_ai_employee_code for row in rows if row.assigned_ai_employee_code}
    frozen = sum(1 for row in employees if row.status in FROZEN_EMPLOYEE_STATUSES)
    active = sum(1 for row in employees if row.status == "active")
    offline = sum(1 for row in employees if row.status not in {"active", *FROZEN_EMPLOYEE_STATUSES})
    grouped: dict[str, int] = {}
    for row in employees:
        department = row.legion or "未分配部门"
        grouped[department] = grouped.get(department, 0) + 1
    return {
        "total": len(employees),
        "working": len(working_codes),
        "idle": max(active - len(working_codes), 0),
        "frozen": frozen,
        "offline": offline,
        "departments": [{"name": name, "employee_count": count} for name, count in sorted(grouped.items())],
    }


def collect_capability_stats(db: Session) -> dict:
    rows = employee_capabilities.build_capability_rows(db)
    missing = employee_capabilities.build_missing_capabilities(rows)
    summary = employee_capabilities.build_overview_summary(rows, missing)
    return {
        "available": bool(rows),
        "configured_capabilities": int(summary.get("configured_capabilities") or 0),
        "missing_capability_count": int(summary.get("missing_capability_count") or 0),
        "average_maturity_level": summary.get("average_maturity_level"),
        "average_success_rate": summary.get("average_success_rate"),
    }


def collect_skill_stats() -> dict:
    skills = list(getattr(sop_skill_center, "SKILLS", []))
    sops = list(getattr(sop_skill_center, "SOPS", []))
    prompts = list(getattr(sop_skill_center, "PROMPTS", []))
    return {
        "total": len(skills),
        "enabled": sum(1 for row in skills if skill_status(row) in {"active", "approved", "enabled", "readonly_configured"}),
        "reviewing": sum(1 for row in skills if row.get("requires_security_audit") or skill_status(row) in {"review", "pending"}),
        "high_risk": sum(1 for row in skills if risk_level(row) in HIGH_RISK_LEVELS),
        "sop_count": len(sops),
        "prompt_count": len(prompts),
    }


def collect_memory_stats(db: Session) -> dict:
    task_total = count_rows(db, TaskCenterTask)
    article_total = count_rows(db, KnowledgeArticle)
    sop_total = count_rows(db, SopLibrary)
    prompt_total = count_rows(db, PromptLibrary)
    bug_total = count_rows(db, BugCase)
    success_cases = count_statuses(db, TaskCenterTask, SUCCESS_TASK_STATUSES)
    failure_cases = count_statuses(db, TaskCenterTask, {"rejected"}) + bug_total
    updated_values = [
        max_value(db, TaskCenterTask.updated_at),
        max_value(db, KnowledgeArticle.updated_at),
        max_value(db, SopLibrary.updated_at),
        max_value(db, PromptLibrary.updated_at),
        max_value(db, BugCase.updated_at),
    ]
    types = {
        "Experience": task_total,
        "DecisionHistory": article_total,
        "LearningRecord": sop_total + prompt_total,
        "SuccessCase": success_cases,
        "FailureCase": failure_cases,
    }
    return {
        "total": sum(types.values()),
        "last_updated": iso(max_datetime(updated_values)),
        "types": types,
    }


def collect_growth_stats(db: Session) -> dict:
    rows = db.query(EmployeeGrowth.score, EmployeeGrowth.growth_level, EmployeeGrowth.success_rate).all()
    total = len(rows)
    avg_score = average([row.score for row in rows])
    avg_success = average([row.success_rate for row in rows])
    return {
        "available": total > 0,
        "growth_records": total,
        "growth_level": growth_level(avg_score),
        "skill_trend": skill_trend(avg_success if avg_success is not None else avg_score),
        "recent_growth_records": total,
    }


def collect_audit_stats(db: Session) -> dict:
    events = db.query(RiskEvent.risk_level).all()
    high_risk_count = sum(1 for row in events if normalize_text(row.risk_level) in HIGH_RISK_LEVELS)
    blocked_tasks = count_statuses(db, TaskCenterTask, BLOCKED_TASK_STATUSES)
    high_total = high_risk_count + blocked_tasks
    return {
        "risk_count": len(events) + blocked_tasks,
        "high_risk_count": high_total,
        "pending_boss_confirm": high_total,
        "security_audited_required": high_total,
    }


def collect_meeting_stats() -> dict:
    return {
        "available": False,
        "meeting_count": 0,
        "draft_count": 0,
        "participant_count": 0,
        "status": "not_connected",
    }


def collect_task_stats(db: Session) -> dict:
    rows = db.query(TaskCenterTask.status, func.count(TaskCenterTask.id)).group_by(TaskCenterTask.status).all()
    counts = {normalize_text(status): int(count) for status, count in rows}
    return {
        "total": sum(counts.values()),
        "running": sum(counts.get(status, 0) for status in WORKING_TASK_STATUSES),
        "pending": sum(counts.get(status, 0) for status in PENDING_TASK_STATUSES),
        "blocked": sum(counts.get(status, 0) for status in BLOCKED_TASK_STATUSES),
        "review_pending": sum(counts.get(status, 0) for status in REVIEW_PENDING_TASK_STATUSES),
    }


def build_center_entries(sections: dict) -> list[dict]:
    return [
        center("ai_workforce", "AI Workforce Center", "AI员工总览与部门状态", "/ai-workforce.html", sections["employees"]["total"], "low", sections["employees"]["total"] > 0),
        center("capability", "Capability Center", "员工能力档案与缺口", "/ai-employee-capability.html", sections["capability"]["configured_capabilities"], "medium", sections["capability"]["available"]),
        center("skill", "Skill Center", "技能、SOP 与 Prompt 资产", "/skill-center.html", sections["skill"]["total"], "high" if sections["skill"]["high_risk"] else "low", sections["skill"]["total"] > 0),
        center("memory", "Memory Center", "经验、案例与决策记忆", "/ai-employee-memory.html", sections["memory"]["total"], "medium" if sections["memory"]["types"]["FailureCase"] else "low", sections["memory"]["total"] > 0),
        center("growth", "Growth Center", "成长记录与能力变化", "/ai-employee-growth.html", sections["growth"]["growth_records"], "low", sections["growth"]["available"]),
        center("audit", "Audit Center", "风险事件与安全审核", "/audit-center.html", sections["audit"]["risk_count"], "high" if sections["audit"]["high_risk_count"] else "low", sections["audit"]["risk_count"] > 0),
        center("meeting", "AI Meeting Room", "协作会议与方案草稿", "/ai-meeting-room.html", sections["meeting"]["meeting_count"], "low", False, status="not_connected"),
        center("task", "Task Center", "任务状态与验收进度", "/task-center.html", sections["task"]["total"], "medium" if sections["task"]["blocked"] else "low", sections["task"]["total"] > 0),
    ]


def center(key: str, name: str, description: str, href: str, count: int, risk: str, available: bool, status: str | None = None) -> dict:
    return {
        "key": key,
        "name": name,
        "description": description,
        "status": status or ("available" if available else "empty"),
        "count": int(count or 0),
        "last_updated": None,
        "risk_level": risk,
        "href": href,
    }


def build_empty_state(sections: dict) -> dict:
    has_data = any(
        [
            sections["employees"]["total"],
            sections["skill"]["total"],
            sections["memory"]["total"],
            sections["growth"]["growth_records"],
            sections["audit"]["risk_count"],
            sections["task"]["total"],
        ]
    )
    return {
        "no_real_business_data": not has_data,
        "message": "当前未接入真实业务数据" if not has_data else "当前展示本地系统只读聚合数据",
    }


def build_security_payload() -> dict:
    return {
        "readonly": True,
        "execution_engine_called": False,
        "openclaw_connected": False,
        "n8n_connected": False,
        "auto_execute": False,
        "high_risk_requires": {
            "boss_confirm": True,
            "security_audited": True,
        },
    }


def safe_collect(module: str, collector: Callable[[], dict], default: dict, errors: list[dict]) -> dict:
    try:
        return collector()
    except Exception as exc:
        errors.append({"module": module, "status": "unavailable", "message": "当前数据不可用"})
        return default


def default_employee_stats() -> dict:
    return {"total": 0, "working": 0, "idle": 0, "frozen": 0, "offline": 0, "departments": []}


def default_capability_stats() -> dict:
    return {"available": False, "configured_capabilities": 0, "missing_capability_count": 0, "average_maturity_level": None, "average_success_rate": None}


def default_skill_stats() -> dict:
    return {"total": 0, "enabled": 0, "reviewing": 0, "high_risk": 0, "sop_count": 0, "prompt_count": 0}


def default_memory_stats() -> dict:
    return {"total": 0, "last_updated": None, "types": {"Experience": 0, "DecisionHistory": 0, "LearningRecord": 0, "SuccessCase": 0, "FailureCase": 0}}


def default_growth_stats() -> dict:
    return {"available": False, "growth_records": 0, "growth_level": None, "skill_trend": None, "recent_growth_records": 0}


def default_audit_stats() -> dict:
    return {"risk_count": 0, "high_risk_count": 0, "pending_boss_confirm": 0, "security_audited_required": 0}


def default_task_stats() -> dict:
    return {"total": 0, "running": 0, "pending": 0, "blocked": 0, "review_pending": 0}


def count_rows(db: Session, model: Any) -> int:
    return int(db.query(func.count(model.id)).scalar() or 0)


def count_statuses(db: Session, model: Any, statuses: set[str]) -> int:
    return int(db.query(func.count(model.id)).filter(model.status.in_(statuses)).scalar() or 0)


def max_value(db: Session, column: Any):
    return db.query(func.max(column)).scalar()


def max_datetime(values: list[Any]):
    valid = [value for value in values if value is not None]
    return max(valid, key=lambda value: str(value)) if valid else None


def iso(value: Any) -> str | None:
    if not value:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def average(values: list[Any]) -> float | None:
    nums = [float(value) for value in values if value is not None]
    return round(sum(nums) / len(nums), 4) if nums else None


def growth_level(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 85:
        return "L4 高成长"
    if score >= 70:
        return "L3 稳定成长"
    if score >= 50:
        return "L2 待提升"
    return "L1 观察期"


def skill_trend(value: float | None) -> str | None:
    if value is None:
        return None
    if value >= 80:
        return "up"
    if value >= 55:
        return "stable"
    return "down"


def skill_status(row: dict) -> str:
    return normalize_text(row.get("current_status") or row.get("skill_status") or row.get("status") or "readonly_configured")


def risk_level(row: dict) -> str:
    return normalize_text(row.get("safety_level") or row.get("risk_level") or "low")


def normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()
