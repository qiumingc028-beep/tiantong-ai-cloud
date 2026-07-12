from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class WindowSnapshot:
    application_name: str
    bundle_id: str
    window_title: str
    width: int | None = None
    height: int | None = None
    frontmost: bool = False
    screenshot_allowed: bool = True
    metadata: dict[str, object] = field(default_factory=dict)


class WindowProvider(Protocol):
    def list_windows(self) -> list[WindowSnapshot]:
        ...


class StaticWindowProvider:
    def __init__(self, windows: list[WindowSnapshot] | None = None):
        self._windows = windows or []

    def list_windows(self) -> list[WindowSnapshot]:
        return list(self._windows)

