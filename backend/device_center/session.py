from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .audit import make_screenshot_hash, record_security_event, redact_sensitive
from .constants import OBSERVATION_STATUSES
from .models import DeviceObservationEvent, DeviceObservationSession


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def json_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def create_observation_session(device_id: str, *, task_id: int | None = None, employee_id: int | None = None, skill_id: int | None = None, computer_session_id: str | None = None, observation_goal: str | None = None, allowed_applications: list[str] | None = None, allowed_windows: list[str] | None = None, max_screenshots: int = 3, expires_in_minutes: int = 30, trace_id: str | None = None) -> DeviceObservationSession:
    return DeviceObservationSession(
        observation_id=str(uuid4()),
        device_id=device_id,
        computer_session_id=computer_session_id,
        task_id=task_id,
        employee_id=employee_id,
        skill_id=skill_id,
        status="等待设备",
        allowed_applications_json=json_text(allowed_applications or []),
        allowed_windows_json=json_text(allowed_windows or []),
        observation_goal=observation_goal,
        screenshot_count=0,
        max_screenshots=max_screenshots,
        started_at=utcnow(),
        expires_at=utcnow() + timedelta(minutes=expires_in_minutes),
        trace_id=trace_id,
    )


def append_observation_event(observation: DeviceObservationSession, *, application_name: str | None = None, bundle_id: str | None = None, window_title: str | None = None, screenshot_reference: str | None = None, screen_state: str | None = None, risk_flags: list[str] | None = None, suggested_next_step: str | None = None, trace_id: str | None = None, duration_ms: int | None = None) -> DeviceObservationEvent:
    payload = f"{observation.observation_id}:{observation.screenshot_count}:{application_name}:{window_title}:{screen_state}:{screenshot_reference}"
    event = DeviceObservationEvent(
        observation_event_id=hashlib.sha256(payload.encode("utf-8")).hexdigest()[:36],
        observation=observation,
        sequence_number=observation.screenshot_count + 1,
        application_name=application_name,
        bundle_id=bundle_id,
        window_title=window_title,
        screenshot_reference=screenshot_reference,
        screenshot_hash=make_screenshot_hash(screenshot_reference or payload),
        screen_state=screen_state,
        risk_flags=json_text(redact_sensitive(risk_flags or [])),
        suggested_next_step=suggested_next_step,
        duration_ms=duration_ms,
        trace_id=trace_id,
    )
    observation.screenshot_count += 1
    observation.status = "执行中"
    observation.updated_at = utcnow()
    return event


def observation_finished_status(event_count: int, stop_reason: str | None = None) -> str:
    if stop_reason:
        if "敏感" in stop_reason:
            return "敏感内容阻断"
        if "超时" in stop_reason:
            return "已超时"
        if "取消" in stop_reason:
            return "已取消"
        return "已失败"
    if event_count <= 0:
        return "已完成"
    return "已完成"
