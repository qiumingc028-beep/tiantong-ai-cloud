from __future__ import annotations

from .script_generator import generate_video_script, generate_xiaohongshu_note
from .trend_analyzer import analyze_trend


def build_video_content(payload: dict) -> dict:
    trend = analyze_trend(payload)
    script = generate_video_script(payload, trend)
    return {
        "engine": "content",
        "content_type": "video",
        "trend": trend,
        "script": script,
        "next_action": "进入人工审核发布队列，不自动发布。",
    }


def build_xiaohongshu_content(payload: dict) -> dict:
    trend = analyze_trend(payload)
    note = generate_xiaohongshu_note(payload, trend)
    return {
        "engine": "content",
        "content_type": "xiaohongshu",
        "trend": trend,
        "note": note,
        "next_action": "进入人工审核发布队列，不自动发布。",
    }
