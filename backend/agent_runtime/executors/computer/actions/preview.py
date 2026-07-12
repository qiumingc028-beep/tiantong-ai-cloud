from __future__ import annotations

import hashlib

from .planner import utcnow


def preview_payload(plan, target, session) -> dict:
    target_application = getattr(target, "target_application", None) or getattr(target, "expected_application", None)
    target_window = getattr(target, "target_window", None) or getattr(target, "expected_window", None)
    raw = f"{plan.plan_id}:{target.action_id}:{target_application}:{target_window}:{target.control_label}:{target.control_identifier}:{utcnow().isoformat()}"
    preview_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return {
        "plan_id": plan.plan_id,
        "action_id": target.action_id,
        "device_id": getattr(session, "device_id", None),
        "session_id": plan.session_id,
        "target_application": target_application,
        "target_window": target_window,
        "action_type": target.action_type,
        "target_control": {
            "control_type": target.control_type,
            "control_label": target.control_label,
            "control_identifier": target.control_identifier,
        },
        "input_text_summary": target.input_text_summary,
        "risk_level": plan.risk_level,
        "approval_mode": plan.approval_mode,
        "execution_plan": plan.goal,
        "before_screenshot_reference": target.screenshot_before_reference,
        "before_screenshot_hash": target.screenshot_before_hash,
        "expected_result": "执行单个动作后自动暂停",
        "stop_conditions": [
            "窗口变化",
            "控件变化",
            "敏感窗口出现",
            "本地停止信号",
        ],
        "preview_hash": preview_hash,
    }
