from __future__ import annotations


def recommend_price(order: dict, metrics: dict | None = None) -> dict:
    quantity = safe_number(order.get("quantity"), 1)
    amount = safe_number(order.get("amount"), 0)
    current_price = safe_number(order.get("current_price"), 0) or (round(amount / quantity, 2) if quantity else amount)
    conversion_rate = safe_number((metrics or {}).get("conversion_rate"), 0)
    stock = safe_number((metrics or {}).get("stock"), 0)

    if stock > 0 and stock < 20:
        multiplier = 1.05
        reason = "库存偏低，建议小幅提价保护利润。"
    elif conversion_rate >= 0.08:
        multiplier = 1.03
        reason = "转化率较高，建议测试小幅提价。"
    elif conversion_rate and conversion_rate < 0.02:
        multiplier = 0.97
        reason = "转化率偏低，建议小幅降价测试。"
    else:
        multiplier = 1.0
        reason = "数据不足，建议保持当前价格。"

    return {
        "current_price": current_price,
        "recommended_price": round(current_price * multiplier, 2),
        "price_change_rate": round(multiplier - 1, 4),
        "reason": reason,
        "auto_apply": False,
        "requires_human_review": True,
    }


def safe_number(value, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
