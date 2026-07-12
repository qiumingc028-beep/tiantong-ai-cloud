from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import DeviceSecurityEvent


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def redact_sensitive(value):
    if isinstance(value, dict):
        return {key: redact_sensitive("[REDACTED]" if any(token in str(key).lower() for token in ("password", "token", "cookie", "secret", "key", "authorization")) else item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if isinstance(value, str):
        lowered = value.lower()
        for token in ("password=", "token=", "cookie=", "secret=", "private key", "authorization", "apikey", "api_key"):
            if token in lowered:
                return "[REDACTED]"
        return value[:256]
    return value


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def make_screenshot_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_security_event(db: Session, *, device_id: str | None, observation_id: str | None, event_code: str, event_message: str | None, risk_level: str, sensitive_data_involved: bool, trace_id: str | None) -> DeviceSecurityEvent:
    row = DeviceSecurityEvent(
        security_event_id=hashlib.sha256(f"{device_id}:{observation_id}:{event_code}:{utcnow().isoformat()}".encode("utf-8")).hexdigest()[:36],
        device_id=device_id,
        observation_id=observation_id,
        event_code=event_code,
        event_message=event_message,
        risk_level=risk_level,
        sensitive_data_involved=sensitive_data_involved,
        trace_id=trace_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row

