from __future__ import annotations

from typing import Any

from backend.ai_employees.registry import AI_EMPLOYEE_REGISTRY


PROFILE_OVERRIDES = {
    "tiancai_data": {
        "capability_tags": ["data_collection", "business_monitoring", "evidence_building"],
        "skills": ["data_collection"],
        "permissions": ["read_business_metrics", "read_task_context"],
    },
    "tianshu": {
        "capability_tags": ["data_analysis", "metric_calculation", "trend_detection"],
        "skills": ["data_collection", "strategy_planning"],
        "permissions": ["read_business_metrics", "read_knowledge"],
    },
    "tiance_strategy": {
        "capability_tags": ["strategy_planning", "business_reasoning", "priority_ranking"],
        "skills": ["strategy_planning", "knowledge_learning"],
        "permissions": ["read_business_metrics", "read_knowledge", "read_strategy_context"],
    },
    "tianshang": {
        "capability_tags": ["ecommerce_operation", "product_optimization", "conversion_growth"],
        "skills": ["ecommerce_operation", "strategy_planning"],
        "permissions": ["read_product_metrics", "read_task_context"],
    },
    "tiantou": {
        "capability_tags": ["ad_analysis", "roi_review", "budget_safety"],
        "skills": ["ad_performance_check"],
        "permissions": ["read_ad_metrics", "read_task_context"],
    },
    "tianjian_test": {
        "capability_tags": ["quality_acceptance", "risk_validation", "regression_check"],
        "skills": ["quality_acceptance"],
        "permissions": ["read_task_context", "read_result"],
    },
    "tiandun_ops": {
        "capability_tags": ["ops_safety", "deploy_review", "health_check"],
        "skills": ["security_approval", "quality_acceptance"],
        "permissions": ["read_health", "read_logs"],
    },
}


def list_employee_profiles(history: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [get_employee_profile(code, history) for code in AI_EMPLOYEE_REGISTRY]


def get_employee_profile(employee_code: str, history: dict[str, Any] | None = None) -> dict[str, Any]:
    base = AI_EMPLOYEE_REGISTRY.get(employee_code)
    override = PROFILE_OVERRIDES.get(employee_code, {})
    history_row = (history or {}).get(employee_code, {}) if isinstance(history, dict) else {}
    return {
        "employee_code": employee_code,
        "employee_name": base.name if base else employee_code,
        "department": base.department if base else "unknown",
        "default_task_type": base.task_type if base else "unknown",
        "capability_tags": list(override.get("capability_tags") or [base.task_type if base else "general"]),
        "skills": list(override.get("skills") or [base.task_type if base else "general"]),
        "permissions": list(override.get("permissions") or ["read_task_context"]),
        "historical_performance": {
            "completion_rate": safe_float(history_row.get("completion_rate"), 0.85),
            "accuracy_rate": safe_float(history_row.get("accuracy_rate"), 0.82),
            "risk_rate": safe_float(history_row.get("risk_rate"), 0.08),
            "efficiency": safe_float(history_row.get("efficiency"), 0.8),
        },
        "can_expand_permission": False,
        "requires_tian_shen_for_high_risk_skill": True,
    }


def safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
