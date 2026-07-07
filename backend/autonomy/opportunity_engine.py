from __future__ import annotations

from typing import Any


LIFECYCLE = ["discovered", "analysis", "decision", "approval", "execution", "review", "learning"]


def build_opportunities(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [build_opportunity(signal, index + 1) for index, signal in enumerate(signals)]


def build_opportunity(signal: dict[str, Any], index: int) -> dict[str, Any]:
    store = signal.get("store") or "unknown_store"
    signal_type = signal.get("signal_type") or "business_signal"
    command = command_for_signal(signal)
    return {
        "opportunity_id": f"opp-{signal_type}-{index}",
        "source_signal": signal,
        "command": command,
        "recommended_team": team_for_signal(signal_type),
        "lifecycle": [
            {"stage": stage, "status": "pending" if stage != "discovered" else "completed"}
            for stage in LIFECYCLE
        ],
        "approval_required": signal.get("severity") == "high",
        "learning_goal": f"将 {store} 的 {signal.get('title')} 处理结果回流到下一轮监控阈值。",
    }


def command_for_signal(signal: dict[str, Any]) -> str:
    store = signal.get("store") or "店铺"
    signal_type = signal.get("signal_type")
    evidence = signal.get("evidence") or "业务异常"
    if signal_type in {"sales_decline", "conversion_decline"}:
        return f"分析今天{store}{evidence}原因，并输出天采、天策、天商、天投、天检协作方案"
    if signal_type == "ad_anomaly":
        return f"检查今天{store}广告异常：{evidence}，并给出投放优化和验收方案"
    if signal_type == "product_issue":
        return f"分析{store}商品问题：{evidence}，优化商品结构和转化方案"
    if signal_type == "customer_service_issue":
        return f"分析{store}客服问题：{evidence}，给出客服、商品和内容改进方案"
    return f"分析{store}业务异常：{evidence}"


def team_for_signal(signal_type: str) -> list[str]:
    if signal_type in {"sales_decline", "conversion_decline", "ad_anomaly"}:
        return ["tiancai_data", "tiance_strategy", "tianshang", "tiantou", "tianjian_test"]
    if signal_type == "product_issue":
        return ["tiancai_data", "tiance_strategy", "tianshang", "tianjian_test"]
    if signal_type == "customer_service_issue":
        return ["tiancai_data", "tiance_strategy", "tianshang", "tianjian_test"]
    return ["tiancai_data", "tiance_strategy", "tianjian_test"]
