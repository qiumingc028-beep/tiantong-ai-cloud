from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..evolution_models import RiskEvent
from ..models import AiEmployee, TaskCenterTask, User
from ..routers import sop_skill_center


SUCCESS_TASK_STATUSES = {"accepted", "audited", "summarized"}
FAILURE_TASK_STATUSES = {"rejected", "failed", "blocked"}
HIGH_RISK_LEVELS = {"high", "critical"}


def build_employee_skill_list(db: Session, user: User, filters: dict[str, str | None] | None = None) -> dict:
    assets = list_employee_skill_assets(db, filters or {})
    return {
        "mode": "readonly",
        "summary": skill_summary(assets),
        "skills": assets,
        "security": security_payload(),
        "data_sources": data_sources(),
        "errors": [],
    }


def build_skill_detail(db: Session, user: User, skill_id: str) -> dict:
    assets = list_employee_skill_assets(db, {})
    matched = [row for row in assets if row["skill_id"] == skill_id]
    if not matched:
        return {
            "mode": "readonly",
            "skill": empty_skill_detail(skill_id),
            "employees": [],
            "task_usage": [],
            "memory_refs": [],
            "growth_refs": [],
            "audit_refs": [],
            "security": security_payload(),
            "errors": [],
        }
    first = matched[0]
    return {
        "mode": "readonly",
        "skill": {
            "skill_id": first["skill_id"],
            "skill_name": first["skill_name"],
            "skill_version": first["skill_version"],
            "description": first["description"],
            "risk_level": max_risk(row["risk_level"] for row in matched),
            "employee_count": len({row["employee_id"] for row in matched}),
            "usage_count": sum(int(row["usage_count"] or 0) for row in matched),
            "success_rate": average_success_rate(matched),
            "created_time": min_iso([row.get("created_time") for row in matched]),
            "updated_time": max_iso([row.get("updated_time") for row in matched]),
        },
        "employees": [
            {
                "employee_id": row["employee_id"],
                "employee_name": row["employee_name"],
                "department": row["department"],
                "usage_count": row["usage_count"],
                "success_rate": row["success_rate"],
                "risk_level": row["risk_level"],
            }
            for row in matched
        ],
        "task_usage": task_usage_refs(db, [row["employee_id"] for row in matched]),
        "memory_refs": [],
        "growth_refs": [],
        "audit_refs": audit_refs(db, [row["employee_id"] for row in matched]),
        "security": security_payload(),
        "errors": [],
    }


def build_employee_skill_relations(db: Session, user: User, employee_id: str) -> dict:
    employees = employee_map(db)
    employee = employees.get(employee_id)
    info = static_employee_info().get(employee_id, {})
    assets = [row for row in list_employee_skill_assets(db, {}) if row["employee_id"] == employee_id]
    return {
        "mode": "readonly",
        "employee": {
            "employee_id": employee_id,
            "employee_name": employee.employee_name if employee else info.get("employee_name", employee_id),
            "department": employee.legion if employee and employee.legion else info.get("department", "未分配部门"),
        },
        "summary": {
            "skill_total": len(assets),
            "high_risk_skill_count": sum(1 for row in assets if row["risk_level"] in HIGH_RISK_LEVELS),
            "average_success_rate": average_success_rate(assets),
        },
        "skills": assets,
        "security": security_payload(),
        "errors": [],
    }


def list_employee_skill_assets(db: Session, filters: dict[str, str | None]) -> list[dict]:
    employees = employee_map(db)
    skill_configs = skill_config_map()
    bindings = employee_skill_bindings(db, employees, skill_configs)
    task_stats = task_stats_by_employee(db)
    risk_levels = risk_by_employee(db)
    assets = [
        make_asset(employee_code, skill_id, employees, skill_configs, task_stats, risk_levels)
        for employee_code, skill_id in bindings
    ]
    return filter_assets(assets, filters)


def employee_map(db: Session) -> dict[str, AiEmployee]:
    rows = db.query(AiEmployee).filter(AiEmployee.is_legacy.is_(False)).order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc()).all()
    return {row.employee_code: row for row in rows}


def skill_config_map() -> dict[str, dict]:
    return {row.get("skill_code"): row for row in getattr(sop_skill_center, "SKILLS", []) if row.get("skill_code")}


def employee_skill_bindings(db: Session, employees: dict[str, AiEmployee], skill_configs: dict[str, dict]) -> list[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for row in getattr(sop_skill_center, "EMPLOYEE_BINDINGS", []):
        binding = sop_skill_center.employee_binding(row)
        employee_code = binding["employee_code"]
        for skill_id in binding.get("bound_skills", []):
            if skill_id:
                pairs = pairs | {(employee_code, skill_id)}
    for employee in employees.values():
        for skill_id in parse_json_list(employee.task_types):
            normalized = skill_id if skill_id in skill_configs else "mock_skill_" + skill_id
            pairs = pairs | {(employee.employee_code, normalized)}
    return sorted(pairs)


def make_asset(
    employee_code: str,
    skill_id: str,
    employees: dict[str, AiEmployee],
    skill_configs: dict[str, dict],
    task_stats: dict[str, dict],
    risk_levels: dict[str, str],
) -> dict:
    employee = employees.get(employee_code)
    info = static_employee_info().get(employee_code, {})
    config = skill_configs.get(skill_id, {})
    stats = task_stats.get(employee_code, empty_task_stats())
    skill_name = config.get("skill_name") or display_skill_name(skill_id)
    risk_level = normalize_risk(max_risk([config.get("safety_level", "low"), risk_levels.get(employee_code, "low")]))
    return {
        "skill_id": skill_id,
        "skill_name": skill_name,
        "skill_version": config.get("skill_version") or "暂无版本",
        "skill_status": config.get("current_status") or "readonly_mock",
        "description": config.get("description") or f"{skill_name} 的只读技能资产。",
        "employee_id": employee_code,
        "employee_name": employee.employee_name if employee else info.get("employee_name", employee_code),
        "department": employee.legion if employee and employee.legion else info.get("department", "未分配部门"),
        "usage_count": stats["usage_count"],
        "success_count": stats["success_count"],
        "failure_count": stats["failure_count"],
        "success_rate": success_rate(stats["success_count"], stats["usage_count"]),
        "risk_level": risk_level,
        "created_time": iso(employee.created_at if employee else None),
        "updated_time": max_iso([iso(employee.updated_at if employee else None), stats.get("updated_time")]),
        "last_used_at": stats.get("updated_time"),
        "audit_status": "review_required" if risk_level in HIGH_RISK_LEVELS else "readonly",
        "security_audited": False,
        "boss_confirm": False,
        "readonly": True,
    }


def task_stats_by_employee(db: Session) -> dict[str, dict]:
    result: dict[str, dict] = {}
    rows = db.query(TaskCenterTask).filter(TaskCenterTask.assigned_ai_employee_code.isnot(None)).all()
    for task in rows:
        code = task.assigned_ai_employee_code
        if not code:
            continue
        stats = result.setdefault(code, empty_task_stats())
        stats["usage_count"] += 1
        if task.status in SUCCESS_TASK_STATUSES:
            stats["success_count"] += 1
        if task.status in FAILURE_TASK_STATUSES:
            stats["failure_count"] += 1
        stats["updated_time"] = max_iso([stats.get("updated_time"), iso(task.updated_at)])
    return result


def static_employee_info() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in getattr(sop_skill_center, "EMPLOYEE_BINDINGS", []):
        binding = sop_skill_center.employee_binding(row)
        result[binding["employee_code"]] = {
            "employee_name": binding["employee_name"],
            "department": binding["department"],
        }
    return result


def risk_by_employee(db: Session) -> dict[str, str]:
    levels: dict[str, str] = {}
    for task in db.query(TaskCenterTask).filter(TaskCenterTask.assigned_ai_employee_code.isnot(None)).all():
        code = task.assigned_ai_employee_code
        if not code:
            continue
        if task.status in FAILURE_TASK_STATUSES:
            levels[code] = max_risk([levels.get(code, "low"), "high"])
    for event in db.query(RiskEvent).all():
        levels[event.employee_code] = max_risk([levels.get(event.employee_code, "low"), event.risk_level or "low"])
    return levels


def task_usage_refs(db: Session, employee_codes: list[str]) -> list[dict]:
    rows = (
        db.query(TaskCenterTask)
        .filter(TaskCenterTask.assigned_ai_employee_code.in_(employee_codes))
        .order_by(TaskCenterTask.updated_at.desc(), TaskCenterTask.id.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "task_id": row.id,
            "title": row.title,
            "status": row.status,
            "employee_id": row.assigned_ai_employee_code,
            "updated_time": iso(row.updated_at),
        }
        for row in rows
    ]


def audit_refs(db: Session, employee_codes: list[str]) -> list[dict]:
    rows = db.query(RiskEvent).filter(RiskEvent.employee_code.in_(employee_codes)).limit(20).all()
    return [
        {
            "employee_id": row.employee_code,
            "event_type": row.event_type,
            "risk_level": normalize_risk(row.risk_level),
        }
        for row in rows
    ]


def filter_assets(assets: list[dict], filters: dict[str, str | None]) -> list[dict]:
    employee_id = clean(filters.get("employee_id"))
    department = clean(filters.get("department"))
    risk_level = clean(filters.get("risk_level"))
    skill_version = clean(filters.get("skill_version"))
    query = clean(filters.get("q")).lower()
    result = []
    for row in assets:
        if employee_id and row["employee_id"] != employee_id:
            continue
        if department and row["department"] != department:
            continue
        if risk_level and row["risk_level"] != risk_level:
            continue
        if skill_version and row["skill_version"] != skill_version:
            continue
        if query and query not in (row["skill_name"] + " " + row["employee_name"]).lower():
            continue
        result.append(row)
    return result


def skill_summary(assets: list[dict]) -> dict:
    employee_ids = {row["employee_id"] for row in assets}
    success_values = [row["success_rate"] for row in assets if row["success_rate"] is not None]
    return {
        "skill_total": len(assets),
        "employee_with_skill_count": len(employee_ids),
        "high_risk_skill_count": sum(1 for row in assets if row["risk_level"] in HIGH_RISK_LEVELS),
        "average_success_rate": round(sum(success_values) / len(success_values), 4) if success_values else None,
        "last_updated": max_iso([row.get("updated_time") for row in assets]),
    }


def average_success_rate(assets: list[dict]) -> float | None:
    total_usage = sum(int(row.get("usage_count") or 0) for row in assets)
    if not total_usage:
        return None
    total_success = sum(int(row.get("success_count") or 0) for row in assets)
    return round(total_success / total_usage, 4)


def success_rate(success_count: int, usage_count: int) -> float | None:
    if not usage_count:
        return None
    return round(success_count / usage_count, 4)


def empty_skill_detail(skill_id: str) -> dict:
    return {
        "skill_id": skill_id,
        "skill_name": skill_id,
        "skill_version": "暂无版本",
        "description": "暂无技能数据",
        "risk_level": "low",
        "employee_count": 0,
        "usage_count": 0,
        "success_rate": None,
        "created_time": None,
        "updated_time": None,
    }


def empty_task_stats() -> dict:
    return {"usage_count": 0, "success_count": 0, "failure_count": 0, "updated_time": None}


def security_payload() -> dict:
    return {
        "readonly": True,
        "auto_skill_call_enabled": False,
        "auto_skill_install_enabled": False,
        "auto_skill_upgrade_enabled": False,
        "permission_mutation_enabled": False,
        "execution_engine_called": False,
        "openclaw_connected": False,
        "n8n_connected": False,
    }


def data_sources() -> list[str]:
    return [
        "ai_workforce",
        "sop_skill_center",
        "task_center_readonly",
        "memory_center_readonly",
        "growth_center_readonly",
        "audit_center_readonly",
    ]


def parse_json_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if str(item).strip()]
        except Exception:
            return [part.strip() for part in value.split(",") if part.strip()]
    return []


def display_skill_name(skill_id: str) -> str:
    if skill_id.startswith("mock_skill_"):
        skill_id = skill_id.removeprefix("mock_skill_")
    return skill_id.replace("_", " ").strip() or "未命名技能"


def normalize_risk(value: str | None) -> str:
    clean_value = clean(value).lower()
    if clean_value in {"critical", "high"}:
        return "high"
    if clean_value in {"medium", "warning"}:
        return "medium"
    return "low"


def max_risk(values) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    best = "low"
    for value in values:
        risk = normalize_risk(value)
        if order[risk] > order[best]:
            best = risk
    return best


def min_iso(values: list[str | None]) -> str | None:
    cleaned = [value for value in values if value]
    return min(cleaned) if cleaned else None


def max_iso(values: list[str | None]) -> str | None:
    cleaned = [value for value in values if value]
    return max(cleaned) if cleaned else None


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def clean(value: Any) -> str:
    return str(value or "").strip()
