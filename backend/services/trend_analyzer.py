from __future__ import annotations


def analyze_trend(payload: dict) -> dict:
    keyword = payload.get("keyword") or payload.get("topic") or "AI商业增长"
    views = safe_number(payload.get("views"), 0)
    likes = safe_number(payload.get("likes"), 0)
    comments = safe_number(payload.get("comments"), 0)
    shares = safe_number(payload.get("shares"), 0)
    engagement = likes + comments + shares
    engagement_rate = round(engagement / views, 4) if views else 0

    if engagement_rate >= 0.05:
        heat = "high"
        suggestion = "适合快速生成短视频与种草内容。"
    elif engagement_rate >= 0.02:
        heat = "medium"
        suggestion = "适合进入内容测试池。"
    else:
        heat = "low"
        suggestion = "建议继续观察，不扩大投放。"

    return {
        "keyword": keyword,
        "heat_level": heat,
        "engagement_rate": engagement_rate,
        "engagement": engagement,
        "suggestion": suggestion,
        "auto_publish": False,
    }


def safe_number(value, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
