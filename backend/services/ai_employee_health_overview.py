from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..models import User
from .ai_employee_ecosystem_overview import build_ai_employee_ecosystem_overview


MODULE_DEFINITIONS = [
    ("ai_workforce", "AI Workforce Center", "employees", "total", "/api/ai-workforce/overview"),
    ("capability", "Capability Center", "capability", "configured_capabilities", "/api/employee-capabilities/overview"),
    ("skill_center", "Skill Center", "skill", "total", "/api/sop-skill-center/overview"),
    ("memory_center", "Memory Center", "memory", "total", "/api/ai-employee-ecosystem/overview"),
    ("growth_center", "Growth Center", "growth", "growth_records", "/api/ai-employee-ecosystem/overview"),
    ("audit_center", "Audit Center", "audit", "risk_count", "/api/ai-employee-ecosystem/overview"),
    ("meeting_room", "AI Meeting Room", "meeting", "meeting_count", "/api/ai-employee-ecosystem/overview"),
    ("task_center", "Task Center", "task", "total", "/api/task-center/tasks"),
]


def build_ai_employee_health_overview(db: Session, user: User) -> dict:
    generated_at = datetime.now(timezone.utc).isoformat()
    ecosystem = build_ai_employee_ecosystem_overview(db, user)
    modules = build_module_health(ecosystem)
    apis = build_api_health(ecosystem, generated_at)
    freshness = build_data_freshness(ecosystem, modules)
    security = build_security_payload(ecosystem)
    alerts = build_alerts(ecosystem, modules, apis, freshness, security, generated_at)
    score = compute_health_score(modules, apis, freshness, security, alerts)
    status = overall_status(score["overall"], alerts)
    return {
        "mode": "readonly",
        "version": "ai_employee_health_overview_v1",
        "status": status,
        "overall_score": score["overall"],
        "generated_at": generated_at,
        "alert_count": len(alerts),
        "employees": ecosystem.get("employees", default_employees()),
        "modules": modules,
        "apis": apis,
        "freshness": freshness,
        "score": score,
        "alerts": alerts,
        "empty_state": ecosystem.get("empty_state", {"no_real_business_data": True, "message": "当前未接入真实业务数据"}),
        "security": security,
        "data_sources": [
            "ai_employee_ecosystem_overview",
            "system_health",
            "system_ready",
        ],
    }


def build_module_health(ecosystem: dict) -> list[dict]:
    modules = []
    errors = {row.get("module") for row in ecosystem.get("errors", [])}
    for module_key, module_name, section_key, count_key, source in MODULE_DEFINITIONS:
        section = ecosystem.get(section_key, {}) or {}
        count = int(section.get(count_key) or 0)
        status = module_status(module_key, section, count, section_key in errors)
        modules.append(
            {
                "module_key": module_key,
                "module_name": module_name,
                "status": status,
                "source": source,
                "count": count,
                "last_updated": module_last_updated(section),
                "risk_level": module_risk_level(module_key, section),
                "message": module_message(module_name, status),
                "readonly": True,
            }
        )
    return modules


def module_status(module_key: str, section: dict, count: int, has_error: bool) -> str:
    if has_error:
        return "unavailable"
    if module_key == "meeting_room":
        return "not_connected"
    if module_key == "capability":
        return "connected" if section.get("available") else "empty"
    if module_key == "growth_center":
        return "connected" if section.get("available") else "empty"
    if module_key == "audit_center":
        if int(section.get("high_risk_count") or 0) > 0:
            return "degraded"
        return "connected" if count > 0 else "empty"
    if module_key == "task_center":
        if int(section.get("blocked") or 0) > 0:
            return "degraded"
        return "connected" if count > 0 else "empty"
    return "connected" if count > 0 else "empty"


def module_risk_level(module_key: str, section: dict) -> str:
    if module_key == "audit_center" and int(section.get("high_risk_count") or 0) > 0:
        return "high"
    if module_key == "task_center" and int(section.get("blocked") or 0) > 0:
        return "medium"
    if module_key == "skill_center" and int(section.get("high_risk") or 0) > 0:
        return "high"
    if module_key == "meeting_room":
        return "unknown"
    return "low"


def module_last_updated(section: dict) -> str | None:
    value = section.get("last_updated")
    return str(value) if value else None


def module_message(module_name: str, status: str) -> str:
    messages = {
        "connected": f"{module_name} 只读数据可用",
        "empty": f"{module_name} 暂无数据",
        "degraded": f"{module_name} 存在需要关注的风险",
        "unavailable": f"{module_name} 当前数据不可用",
        "not_connected": f"{module_name} V1 暂未接入",
    }
    return messages.get(status, f"{module_name} 状态未知")


def build_api_health(ecosystem: dict, checked_at: str) -> list[dict]:
    ecosystem_errors = ecosystem.get("errors", [])
    ecosystem_status = "degraded" if ecosystem_errors else "available"
    return [
        api_item("ai_employee_health_overview", "/api/ai-employee-health/overview", "available", 200, checked_at),
        api_item("ai_employee_ecosystem_overview", "/api/ai-employee-ecosystem/overview", ecosystem_status, 200, checked_at),
        api_item("system_health", "/api/health", "not_checked", None, checked_at),
        api_item("system_ready", "/api/ready", "not_checked", None, checked_at),
    ]


def api_item(api_key: str, path: str, status: str, http_status: int | None, checked_at: str) -> dict:
    return {
        "api_key": api_key,
        "path": path,
        "status": status,
        "http_status": http_status,
        "latency_ms": None,
        "last_checked_at": checked_at,
        "readonly": True,
        "error_message": None,
    }


def build_data_freshness(ecosystem: dict, modules: list[dict]) -> list[dict]:
    generated_at = ecosystem.get("generated_at")
    freshness = [
        freshness_item("ai_workforce", "AI Workforce Center", generated_at, "fresh", 60, "AI员工状态来自当前只读聚合"),
        freshness_item("skill_center", "Skill Center", None, "empty", 1440, "Skill Center 暂无统一更新时间"),
        freshness_item("capability", "Capability Center", generated_at, "fresh", 1440, "能力状态来自当前只读聚合"),
        freshness_item("memory_center", "Memory Center", ecosystem.get("memory", {}).get("last_updated"), None, 1440, "Memory 数据更新时间"),
        freshness_item("growth_center", "Growth Center", generated_at if ecosystem.get("growth", {}).get("available") else None, None, 1440, "Growth 数据更新时间"),
        freshness_item("audit_center", "Audit Center", generated_at if ecosystem.get("audit", {}).get("risk_count") else None, None, 60, "Audit 风险数据更新时间"),
        freshness_item("meeting_room", "AI Meeting Room", None, "not_connected", 1440, "AI Meeting Room V1 暂未接入"),
        freshness_item("task_center", "Task Center", generated_at if ecosystem.get("task", {}).get("total") else None, None, 30, "Task Center 数据更新时间"),
    ]
    module_statuses = {row["module_key"]: row["status"] for row in modules}
    for row in freshness:
        module_status = module_statuses.get(row["data_key"])
        if module_status == "unavailable":
            row["freshness_status"] = "unavailable"
        elif row["freshness_status"] is None:
            row["freshness_status"] = "fresh" if row["last_updated"] else "empty"
    return freshness


def freshness_item(data_key: str, data_name: str, last_updated: str | None, status: str | None, threshold_minutes: int, message: str) -> dict:
    return {
        "data_key": data_key,
        "data_name": data_name,
        "last_updated": last_updated,
        "freshness_status": status,
        "age_minutes": None,
        "threshold_minutes": threshold_minutes,
        "message": message if last_updated else "暂无更新时间" if status != "not_connected" else message,
    }


def compute_health_score(modules: list[dict], apis: list[dict], freshness: list[dict], security: dict, alerts: list[dict]) -> dict:
    module_score = average_score([status_score(row["status"], {"connected": 100, "empty": 75, "degraded": 60, "not_connected": 70, "unavailable": 0}) for row in modules])
    api_score = average_score([status_score(row["status"], {"available": 100, "degraded": 70, "not_checked": 80, "unavailable": 0}) for row in apis])
    freshness_score = average_score([status_score(row["freshness_status"], {"fresh": 100, "empty": 75, "stale": 60, "not_connected": 70, "unavailable": 0}) for row in freshness])
    security_score = 100 if security_ok(security) else 0
    alert_penalty = min(sum(alert_penalty_value(row["level"]) for row in alerts), 40)
    overall = round(module_score * 0.35 + api_score * 0.25 + freshness_score * 0.20 + security_score * 0.20 - alert_penalty)
    return {
        "overall": clamp(overall),
        "module_score": round(module_score),
        "api_score": round(api_score),
        "freshness_score": round(freshness_score),
        "security_score": round(security_score),
        "alert_penalty": alert_penalty,
        "breakdown": {row["module_key"]: status_score(row["status"], {"connected": 100, "empty": 75, "degraded": 60, "not_connected": 70, "unavailable": 0}) for row in modules},
    }


def build_alerts(ecosystem: dict, modules: list[dict], apis: list[dict], freshness: list[dict], security: dict, detected_at: str) -> list[dict]:
    alerts: list[dict] = []
    for row in ecosystem.get("errors", []):
        alerts.append(alert("ecosystem-" + str(row.get("module", "unknown")), "warning", "module_unavailable", str(row.get("module", "unknown")), "模块数据不可用", "当前数据不可用", detected_at))
    for row in modules:
        if row["status"] == "unavailable":
            alerts.append(alert("module-" + row["module_key"], "warning", "module_unavailable", row["module_key"], row["module_name"] + " 不可用", row["message"], detected_at))
        elif row["status"] == "degraded":
            level = "high" if row["risk_level"] == "high" else "warning"
            alerts.append(alert("module-" + row["module_key"] + "-risk", level, "module_degraded", row["module_key"], row["module_name"] + " 需关注", row["message"], detected_at))
    for row in apis:
        if row["status"] == "unavailable":
            alerts.append(alert("api-" + row["api_key"], "high", "api_unavailable", row["api_key"], row["path"] + " 不可用", "只读 API 当前不可用", detected_at))
    for row in freshness:
        if row["freshness_status"] == "stale":
            alerts.append(alert("freshness-" + row["data_key"], "warning", "data_stale", row["data_key"], row["data_name"] + " 数据过期", row["message"], detected_at))
    if not security_ok(security):
        alerts.append(alert("security-boundary", "high", "security_warning", "security", "安全边界异常", "只读安全边界字段异常", detected_at))
    return dedupe_alerts(alerts)


def alert(alert_id: str, level: str, alert_type: str, module_key: str, title: str, message: str, detected_at: str) -> dict:
    high = level == "high"
    return {
        "alert_id": alert_id,
        "level": level,
        "type": alert_type,
        "module_key": module_key,
        "title": title,
        "message": message,
        "detected_at": detected_at,
        "requires_boss_confirm": high,
        "security_audited_required": high,
        "action_available": False,
    }


def dedupe_alerts(alerts: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for row in alerts:
        if row["alert_id"] in seen:
            continue
        seen = seen | {row["alert_id"]}
        unique.append(row)
    return unique


def build_security_payload(ecosystem: dict) -> dict:
    source = ecosystem.get("security", {})
    return {
        "readonly": bool(source.get("readonly", True)),
        "auto_repair_enabled": False,
        "auto_execute_enabled": bool(source.get("auto_execute", False)),
        "execution_engine_called": bool(source.get("execution_engine_called", False)),
        "openclaw_connected": bool(source.get("openclaw_connected", False)),
        "n8n_connected": bool(source.get("n8n_connected", False)),
        "permission_mutation_enabled": False,
        "task_mutation_enabled": False,
        "high_risk_requires": source.get("high_risk_requires", {"boss_confirm": True, "security_audited": True}),
    }


def security_ok(security: dict) -> bool:
    return (
        security.get("readonly") is True
        and security.get("auto_repair_enabled") is False
        and security.get("auto_execute_enabled") is False
        and security.get("execution_engine_called") is False
        and security.get("openclaw_connected") is False
        and security.get("n8n_connected") is False
        and security.get("permission_mutation_enabled") is False
        and security.get("task_mutation_enabled") is False
    )


def overall_status(score: int, alerts: list[dict]) -> str:
    if any(row["level"] == "high" for row in alerts) or score < 60:
        return "unavailable" if score < 60 else "degraded"
    if score < 85 or any(row["level"] == "warning" for row in alerts):
        return "degraded"
    return "healthy"


def status_score(status: str, mapping: dict[str, int]) -> int:
    return mapping.get(status, 50)


def average_score(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0


def alert_penalty_value(level: str) -> int:
    return {"high": 12, "warning": 6, "info": 2}.get(level, 0)


def clamp(value: int) -> int:
    return max(0, min(100, value))


def default_employees() -> dict:
    return {"total": 0, "working": 0, "idle": 0, "frozen": 0, "offline": 0, "departments": []}
