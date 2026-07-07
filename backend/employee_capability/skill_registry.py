from __future__ import annotations

from typing import Any


SKILL_REGISTRY = [
    {
        "skill_code": "data_collection",
        "skill_name": "经营数据采集",
        "input_requirements": ["store", "date_range", "metric_scope"],
        "output_format": "结构化数据摘要和异常证据",
        "use_cases": ["sales_decline", "conversion_decline", "ad_anomaly"],
        "risk_level": "low",
        "requires_tian_shen_approval": False,
    },
    {
        "skill_code": "strategy_planning",
        "skill_name": "经营策略分析",
        "input_requirements": ["business_goal", "evidence", "constraints"],
        "output_format": "原因拆解、策略优先级和预期收益",
        "use_cases": ["sales_decline", "conversion_decline", "profit_growth", "product_issue"],
        "risk_level": "medium",
        "requires_tian_shen_approval": False,
    },
    {
        "skill_code": "ecommerce_operation",
        "skill_name": "商品经营优化",
        "input_requirements": ["product_metrics", "conversion_metrics", "price_context"],
        "output_format": "商品、价格、详情页和转化建议",
        "use_cases": ["conversion_decline", "product_issue", "profit_growth"],
        "risk_level": "medium",
        "requires_tian_shen_approval": False,
    },
    {
        "skill_code": "ad_performance_check",
        "skill_name": "广告投放检查",
        "input_requirements": ["ad_metrics", "budget_context", "roi_goal"],
        "output_format": "广告异常、预算建议和人工审批项",
        "use_cases": ["ad_anomaly", "conversion_decline", "profit_growth"],
        "risk_level": "high",
        "requires_tian_shen_approval": True,
    },
    {
        "skill_code": "quality_acceptance",
        "skill_name": "验收验证",
        "input_requirements": ["plan", "acceptance_criteria", "risk_notes"],
        "output_format": "验收结论、失败原因和回归建议",
        "use_cases": ["acceptance", "risk_review", "release_check"],
        "risk_level": "low",
        "requires_tian_shen_approval": False,
    },
    {
        "skill_code": "security_approval",
        "skill_name": "安全审批",
        "input_requirements": ["action", "risk", "approval_context"],
        "output_format": "GREEN/YELLOW/RED 审批建议",
        "use_cases": ["permission_change", "deploy", "spend_money", "high_risk_skill"],
        "risk_level": "high",
        "requires_tian_shen_approval": True,
    },
    {
        "skill_code": "knowledge_learning",
        "skill_name": "知识沉淀",
        "input_requirements": ["execution_case", "lessons", "prompt_suggestions"],
        "output_format": "SOP、最佳实践和经验规则",
        "use_cases": ["learning", "sop_generation", "prompt_optimization"],
        "risk_level": "medium",
        "requires_tian_shen_approval": False,
    },
]


def list_skills() -> list[dict[str, Any]]:
    return [dict(row) for row in SKILL_REGISTRY]


def get_skill(skill_code: str) -> dict[str, Any] | None:
    return next((dict(row) for row in SKILL_REGISTRY if row["skill_code"] == skill_code), None)
