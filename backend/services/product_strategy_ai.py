from __future__ import annotations


def recommend_product_strategy(order: dict, metrics: dict | None = None) -> dict:
    sku = order.get("sku") or (metrics or {}).get("sku") or "unknown"
    sales = safe_number((metrics or {}).get("sales"), safe_number(order.get("quantity"), 0))
    stock = safe_number((metrics or {}).get("stock"), 0)
    profit_margin = safe_number((metrics or {}).get("profit_margin"), 0)

    if sales >= 100 and profit_margin >= 0.25:
        tier = "hero_product"
        action = "优先作为主推商品，联动内容引流。"
    elif stock > 100 and sales < 20:
        tier = "clearance_candidate"
        action = "建议进入清库存策略，谨慎降价测试。"
    else:
        tier = "observe"
        action = "继续观察成交、库存和内容转化。"

    return {
        "sku": sku,
        "strategy_tier": tier,
        "selection_reason": action,
        "inventory_strategy": recommend_inventory_strategy(stock, sales),
        "auto_select": True,
        "auto_modify_inventory": False,
    }


def recommend_inventory_strategy(stock: float, sales: float) -> dict:
    if stock <= 0:
        return {"status": "out_of_stock", "suggestion": "缺货，建议人工确认补货。"}
    if sales > 0 and stock / max(sales, 1) < 3:
        return {"status": "low_stock", "suggestion": "库存周转偏紧，建议人工确认补货。"}
    if stock > 100 and sales < 10:
        return {"status": "overstock", "suggestion": "库存偏高，建议内容引流或促销研究。"}
    return {"status": "normal", "suggestion": "库存处于观察区间。"}


def safe_number(value, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
