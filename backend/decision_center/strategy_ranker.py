from __future__ import annotations

from typing import Any


def build_strategy_candidates(opportunity: dict[str, Any]) -> list[dict[str, Any]]:
    signal = opportunity.get("source_signal") or {}
    signal_type = signal.get("signal_type") or "business_signal"
    store = signal.get("store") or "目标店铺"
    base_actions = {
        "sales_decline": [
            "天采拉取订单、流量、商品和广告摘要",
            "天策拆解销量下降的主因和优先级",
            "天商输出商品、价格和详情页优化建议",
            "天检验证方案风险和验收指标",
        ],
        "conversion_decline": [
            "天采拉取访客、转化、商品详情页和竞品摘要",
            "天策判断转化下降的漏斗位置",
            "天商输出详情页、价格和活动承接建议",
            "天投检查广告流量质量",
            "天检验证方案风险和验收指标",
        ],
        "ad_anomaly": [
            "天采汇总广告消耗、点击率、转化率和 ROI",
            "天投定位异常计划和关键词",
            "天策输出预算保护和恢复建议",
            "天检验证不自动改预算的安全边界",
        ],
        "product_issue": [
            "天采汇总商品差评、库存和转化摘要",
            "天商提出商品结构和页面优化建议",
            "天策评估优先级和预期收益",
            "天检验证商品调整风险",
        ],
        "customer_service_issue": [
            "天采汇总客服问题类型和频次",
            "天策定位问题对转化和复购的影响",
            "天商输出话术、商品和内容修正建议",
            "天检验证改进方案",
        ],
    }
    options = [
        ("conservative", "保守修复方案", 0.72, 18, 18, 55),
        ("balanced", "平衡增长方案", 0.66, 32, 36, 74),
        ("aggressive", "进攻增长方案", 0.58, 55, 62, 88),
    ]
    return [
        build_strategy(
            opportunity=opportunity,
            mode=mode,
            title=f"{store}{title}",
            actions=base_actions.get(signal_type) or base_actions["sales_decline"],
            success_probability=success,
            risk_score=risk,
            cost_score=cost,
            expected_revenue_score=revenue,
        )
        for mode, title, success, risk, cost, revenue in options
    ]


def build_strategy(
    opportunity: dict[str, Any],
    mode: str,
    title: str,
    actions: list[str],
    success_probability: float,
    risk_score: int,
    cost_score: int,
    expected_revenue_score: int,
) -> dict[str, Any]:
    total_score = round(success_probability * 100 + expected_revenue_score - risk_score * 0.7 - cost_score * 0.4, 2)
    return {
        "strategy_code": f"{opportunity.get('opportunity_id', 'opportunity')}-{mode}",
        "strategy_name": title,
        "mode": mode,
        "actions": actions,
        "success_probability": success_probability,
        "risk_score": risk_score,
        "cost_score": cost_score,
        "expected_revenue_score": expected_revenue_score,
        "total_score": total_score,
        "requires_approval": risk_score >= 50 or bool(opportunity.get("approval_required")),
        "can_auto_execute": False,
        "can_modify_data": False,
        "can_spend_money": False,
        "safety_notes": "Phase 3.4 只输出 CEO 决策建议，不自动执行、不改价、不改广告、不调用外部工具。",
    }


def rank_strategies(strategies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(strategies, key=lambda row: row.get("total_score", 0), reverse=True)
