from __future__ import annotations


def search_market(goal: str) -> dict:
    clean_goal = (goal or "").strip()
    return {
        "tool": "market_search",
        "mode": "internal_mock",
        "query": clean_goal,
        "category": "男士机械表",
        "market_signals": [
            {"signal": "通勤正装", "demand": "high", "price_band": "800-1500"},
            {"signal": "复古镂空", "demand": "medium", "price_band": "500-900"},
            {"signal": "入门商务礼品", "demand": "high", "price_band": "300-699"},
        ],
        "competitor_brands": ["海鸥", "飞亚达", "罗西尼", "精工入门线"],
        "external_requests": 0,
    }
