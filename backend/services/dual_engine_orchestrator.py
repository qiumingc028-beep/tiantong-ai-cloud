from __future__ import annotations

from .content_ai import build_video_content, build_xiaohongshu_content
from .decision_center import decide
from .ecommerce_engine import analyze_metrics, analyze_order


def orchestrate_dual_engine(payload: dict) -> dict:
    ecommerce_input = payload.get("ecommerce") if isinstance(payload.get("ecommerce"), dict) else payload
    content_input = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    ecommerce_result = analyze_metrics(ecommerce_input) if ecommerce_input.get("sales") is not None else analyze_order(ecommerce_input)
    content_result = (
        build_xiaohongshu_content(content_input)
        if (content_input.get("content_type") or "").lower() == "xiaohongshu"
        else build_video_content(content_input)
    )
    decision = decide({**ecommerce_input, "engine": "ecommerce"})

    return {
        "mode": "dual_engine",
        "ecommerce": ecommerce_result,
        "content": content_result,
        "decision": decision,
        "closed_loop": {
            "data": "orders + content_metrics + traffic_data + competitor_data",
            "analysis": "ecommerce_engine + content_engine",
            "decision": "decision_center",
            "execution": "internal_task_result_writeback",
            "result": "TaskCenterResult",
            "learning": "feedback_loop_candidate",
        },
        "external_execution": False,
    }
