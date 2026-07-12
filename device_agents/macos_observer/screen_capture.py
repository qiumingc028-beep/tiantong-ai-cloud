from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class ScreenshotResult:
    reference: str
    content_hash: str
    width: int
    height: int
    mime_type: str = "image/png"


class ScreenCaptureProvider(Protocol):
    def capture(self, window_title: str) -> ScreenshotResult:
        ...


class StaticScreenCaptureProvider:
    def __init__(self, default_reference: str = "screenshot://static-observer", content_hash: str = "static-hash"):
        self.default_reference = default_reference
        self.content_hash = content_hash

    def capture(self, window_title: str) -> ScreenshotResult:
        return ScreenshotResult(
            reference=f"{self.default_reference}:{window_title}",
            content_hash=self.content_hash,
            width=1440,
            height=900,
        )

