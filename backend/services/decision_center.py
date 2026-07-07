from __future__ import annotations

from ..ai_employees import DEFAULT_STRATEGY_EMPLOYEE
from .content_ai import build_video_content, build_xiaohongshu_content
from .ecommerce_engine import analyze_metrics, analyze_order


def classify_business_task(payload: dict) -> str:
    explicit = (payload.get("engine") or payload.get("type") or "").lower()
    if explicit in {"ecommerce", "order", "metrics", "pricing", "product"}:
        return "ecommerce"
    if explicit in {"content", "video", "xiaohongshu", "trend"}:
        return "content"
    if payload.get("order_id") or payload.get("sku"):
        return "ecommerce"
    if payload.get("topic") or payload.get("content_id") or payload.get("keyword"):
        return "content"
    return "ecommerce"


def decide(payload: dict) -> dict:
    engine = classify_business_task(payload)
    if engine == "content":
        content_type = (payload.get("content_type") or "video").lower()
        recommendation = build_xiaohongshu_content(payload) if content_type == "xiaohongshu" else build_video_content(payload)
        assigned_to = "tianbo"
    else:
        recommendation = analyze_metrics(payload) if payload.get("sales") is not None else analyze_order(payload)
        assigned_to = DEFAULT_STRATEGY_EMPLOYEE

    return {
        "engine": engine,
        "assigned_to": assigned_to,
        "recommendation": recommendation,
        "optimization_strategy": "电商利润与内容流量联动优化",
        "requires_human_review": True,
        "external_execution": False,
    }
