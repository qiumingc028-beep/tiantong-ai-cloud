from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .window_provider import WindowSnapshot


SENSITIVE_WINDOW_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        "password",
        "token",
        "secret",
        "otp",
        "验证码",
        "银行卡",
        "身份证",
        "keychain",
        "钥匙串",
        "ssh",
        "private key",
    ]
]


@dataclass(slots=True)
class SanitizedWindow:
    application_name: str
    bundle_id: str
    window_title: str
    frontmost: bool
    screenshot_allowed: bool
    blocked: bool = False
    blocked_reason: str | None = None


def window_is_sensitive(snapshot: WindowSnapshot) -> bool:
    content = f"{snapshot.application_name} {snapshot.window_title} {snapshot.bundle_id}"
    return any(pattern.search(content) for pattern in SENSITIVE_WINDOW_PATTERNS)


def sanitize_window(snapshot: WindowSnapshot) -> SanitizedWindow:
    blocked = window_is_sensitive(snapshot)
    return SanitizedWindow(
        application_name=snapshot.application_name,
        bundle_id=snapshot.bundle_id,
        window_title=snapshot.window_title if not blocked else "[REDACTED]",
        frontmost=snapshot.frontmost,
        screenshot_allowed=snapshot.screenshot_allowed and not blocked,
        blocked=blocked,
        blocked_reason="SENSITIVE_WINDOW_BLOCKED" if blocked else None,
    )


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def summarize_windows(windows: list[SanitizedWindow]) -> dict[str, object]:
    active = next((window for window in windows if window.frontmost and not window.blocked), None)
    blocked = [window for window in windows if window.blocked]
    return {
        "current_application": active.application_name if active else None,
        "current_window": active.window_title if active else None,
        "window_count": len(windows),
        "sensitive_window_detected": bool(blocked),
        "can_continue": not blocked,
        "suggested_next_step": "继续只读观察" if not blocked else "请求人工处理敏感窗口",
    }

