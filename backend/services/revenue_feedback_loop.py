from __future__ import annotations


def collect_mock_metrics(publish_result: dict, product_binding: dict, cycle_index: int) -> dict:
    base_views = 1200 + cycle_index * 350
    viral_score = float(publish_result.get("viral_score", 0))
    conversion_rate = round(0.015 + min(viral_score, 100) / 10000, 4)
    orders = int(base_views * conversion_rate)
    revenue = round(orders * 79.0, 2)
    return {
        "views": base_views,
        "clicks": int(base_views * 0.08),
        "orders": orders,
        "revenue": revenue,
        "conversion_rate": conversion_rate,
        "sku": product_binding.get("sku"),
        "cycle_index": cycle_index,
        "external_collection": False,
    }


def build_feedback(metrics: dict, previous_strategy: dict | None = None) -> dict:
    revenue = float(metrics.get("revenue", 0))
    conversion_rate = float(metrics.get("conversion_rate", 0))
    if revenue >= 500 or conversion_rate >= 0.025:
        direction = "scale_content_angle"
        note = "收入或转化率达标，下一轮放大当前内容角度。"
    else:
        direction = "improve_hook_and_offer"
        note = "收入或转化率不足，下一轮优化开头钩子和商品利益点。"
    return {
        "direction": direction,
        "note": note,
        "metrics": metrics,
        "previous_strategy": previous_strategy or {},
        "reusable_as_input": True,
    }


def optimize_strategy(feedback: dict) -> dict:
    direction = feedback.get("direction")
    if direction == "scale_content_angle":
        return {
            "topic_bias": "放大已验证内容主题",
            "offer_bias": "保持商品利益点，增加复购场景",
            "content_type": "video",
        }
    return {
        "topic_bias": "强化痛点和首屏钩子",
        "offer_bias": "突出价格、库存和使用场景",
        "content_type": "xiaohongshu",
    }
