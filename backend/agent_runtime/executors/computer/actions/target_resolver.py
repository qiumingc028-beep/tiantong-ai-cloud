from __future__ import annotations

from fastapi import HTTPException

from .policy import ensure_coordinates_safe, ensure_target_application_allowed, ensure_target_control_allowed


def resolve_target(payload):
    ensure_target_application_allowed(payload.target_application)
    ensure_target_control_allowed(payload.control_type, payload.control_label, payload.control_identifier, payload.target_description)
    ensure_coordinates_safe(payload.coordinates)
    if payload.target_application and payload.target_window is None:
        raise HTTPException(status_code=400, detail="目标窗口缺失")
    return {
        "target_application": payload.target_application,
        "target_bundle_id": payload.target_bundle_id,
        "target_window": payload.target_window,
        "control_type": payload.control_type,
        "control_label": payload.control_label,
        "control_identifier": payload.control_identifier,
        "coordinates": payload.coordinates,
        "text_input": payload.text_input,
    }
