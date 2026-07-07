from __future__ import annotations

from datetime import datetime, timezone

from .content_ai import build_video_content, build_xiaohongshu_content
from .content_to_money_bridge import bind_content_to_product
from .ecommerce_engine import analyze_metrics
from .revenue_feedback_loop import build_feedback, collect_mock_metrics, optimize_strategy
from .trend_analyzer import analyze_trend


def run_profit_cycle(seed: dict, cycle_index: int, strategy: dict | None = None) -> dict:
    strategy = strategy or {}
    trend_input = {
        **seed,
        "topic": strategy.get("topic_bias") or seed.get("topic") or seed.get("keyword") or "AI自动经营",
    }
    trend = analyze_trend(trend_input)
    content_payload = {**trend_input, "content_type": strategy.get("content_type", "video")}
    content = (
        build_xiaohongshu_content(content_payload)
        if content_payload.get("content_type") == "xiaohongshu"
        else build_video_content(content_payload)
    )
    viral = score_viral_potential(trend, content)
    publish_result = publish_content_mock(content, viral)
    product_binding = bind_content_to_product(content, seed)
    ecommerce = analyze_metrics(
        {
            "sku": product_binding["sku"],
            "sales": seed.get("sales", 0),
            "stock": seed.get("stock", 100),
            "current_price": seed.get("current_price", 79),
            "conversion_rate": seed.get("conversion_rate", 0.02),
        }
    )
    metrics = collect_mock_metrics(publish_result, product_binding, cycle_index)
    feedback = build_feedback(metrics, strategy)
    next_strategy = optimize_strategy(feedback)
    return {
        "cycle_index": cycle_index,
        "trend": trend,
        "content": content,
        "viral_score": viral["score"],
        "publish_result": publish_result,
        "product_binding": product_binding,
        "ecommerce": ecommerce,
        "metrics": metrics,
        "feedback": feedback,
        "next_strategy": next_strategy,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "external_actions": [],
    }


def score_viral_potential(trend: dict, content: dict) -> dict:
    heat_bonus = {"high": 35, "medium": 20, "low": 8}.get(trend.get("heat_level"), 8)
    structure_bonus = 20 if content.get("script") or content.get("note") else 5
    engagement_bonus = min(float(trend.get("engagement_rate", 0)) * 1000, 30)
    score = round(min(100, heat_bonus + structure_bonus + engagement_bonus), 2)
    return {
        "score": score,
        "level": "high" if score >= 70 else "medium" if score >= 45 else "low",
        "reason": "基于热度、互动率和内容结构的本地评分。",
    }


def publish_content_mock(content: dict, viral: dict) -> dict:
    return {
        "platform_adapter": "mock_platform_adapter",
        "status": "published_mock",
        "content_id": f"mock-{int(float(viral['score']) * 100)}",
        "viral_score": viral["score"],
        "external_publish": False,
        "note": "仅模拟发布，不调用外部平台。",
    }
