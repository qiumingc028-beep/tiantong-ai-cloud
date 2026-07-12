from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    lowered = value.lower()
    for token in ("password", "token", "cookie", "secret", "private key", "验证码", "银行卡", "身份证"):
        if token in lowered:
            return "[REDACTED]"
    return value[:256]


def make_screenshot_reference(session_id: str, action_id: str | None = None) -> str:
    raw = f"{session_id}:{action_id or 'screen'}:{utcnow().isoformat()}"
    return f"screenshot://{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def make_evidence_reference(session_id: str, action_id: str, kind: str) -> str:
    raw = f"{session_id}:{action_id}:{kind}:{utcnow().isoformat()}"
    return f"evidence://{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"


def json_text(payload) -> str:
    if payload is None:
        return "{}"
    return json.dumps(payload, ensure_ascii=False, default=str)
