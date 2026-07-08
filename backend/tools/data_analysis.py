from __future__ import annotations


def analyze_market_data(market_data: dict) -> dict:
    signals = market_data.get("market_signals") or []
    high_demand = [row for row in signals if row.get("demand") == "high"]
    return {
        "tool": "data_analysis",
        "mode": "internal_mock",
        "price_opportunity": {
            "primary_band": "800-1500",
            "reason": "商务通勤和礼品场景需求强，价格带仍有差异化空间。",
        },
        "competition": {
            "level": "medium",
            "brands": market_data.get("competitor_brands") or [],
            "gap": "可通过机芯透明背、商务表盘和礼盒套装形成组合差异。",
        },
        "high_demand_signal_count": len(high_demand),
        "risk": "中低风险：第一阶段只生成商品建议，不自动上架、不改价、不投放。",
    }
