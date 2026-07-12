from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .constants import (
    DEFAULT_MAC_ALLOWED_APPLICATIONS,
    DEFAULT_MAC_ALLOWED_WINDOW_PATTERNS,
    DEFAULT_MAC_BLOCKED_APPLICATIONS,
    DEFAULT_MAC_BLOCKED_WINDOW_PATTERNS,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_list(values: Iterable[str] | None) -> list[str]:
    return [str(value).strip() for value in (values or []) if str(value).strip()]


def default_allowed_applications() -> list[str]:
    return list(DEFAULT_MAC_ALLOWED_APPLICATIONS)


def default_blocked_applications() -> list[str]:
    return list(DEFAULT_MAC_BLOCKED_APPLICATIONS)


def default_allowed_windows() -> list[str]:
    return list(DEFAULT_MAC_ALLOWED_WINDOW_PATTERNS)


def default_blocked_windows() -> list[str]:
    return list(DEFAULT_MAC_BLOCKED_WINDOW_PATTERNS)

