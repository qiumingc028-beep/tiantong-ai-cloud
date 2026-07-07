from __future__ import annotations

from .pricing_ai import recommend_price
from .product_strategy_ai import recommend_product_strategy


def analyze_order(order: dict) -> dict:
    return {
        "engine": "ecommerce",
        "signal": "order",
        "order_id": order.get("order_id"),
        "sku": order.get("sku"),
        "quantity": order.get("quantity", 1),
        "amount": order.get("amount", 0),
        "product_strategy": recommend_product_strategy(order),
        "pricing": recommend_price(order),
        "next_action": "生成电商经营决策并进入内容联动候选。",
    }


def analyze_metrics(metrics: dict) -> dict:
    order_like = {"sku": metrics.get("sku"), "current_price": metrics.get("current_price"), "quantity": 1}
    return {
        "engine": "ecommerce",
        "signal": "metrics",
        "sku": metrics.get("sku"),
        "sales": metrics.get("sales", 0),
        "conversion_rate": metrics.get("conversion_rate", 0),
        "profit_margin": metrics.get("profit_margin", 0),
        "product_strategy": recommend_product_strategy(order_like, metrics),
        "pricing": recommend_price(order_like, metrics),
        "next_action": "更新商品优先级、价格建议和库存策略记录。",
    }
