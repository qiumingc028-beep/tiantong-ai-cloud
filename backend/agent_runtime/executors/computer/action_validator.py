from __future__ import annotations

from fastapi import HTTPException

from .policy import ensure_action_allowed, ensure_application_allowed, ensure_window_allowed, detect_sensitive_region


def validate_action_payload(payload) -> None:
    ensure_action_allowed(payload.action_type, payload.target_application, payload.target_window, payload.text_input)
    ensure_application_allowed(payload.target_application)
    ensure_window_allowed(payload.target_window)
    if detect_sensitive_region(payload.target_window, payload.target_application, payload.text_input):
        raise HTTPException(status_code=403, detail="检测到敏感区域，需要人工接管")
