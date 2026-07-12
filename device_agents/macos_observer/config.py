from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MacObserverConfig:
    device_code: str
    device_name: str
    allowed_applications: list[str] = field(default_factory=list)
    allowed_window_patterns: list[str] = field(default_factory=list)
    max_screenshots: int = 3
    capture_enabled: bool = False
    window_enumeration_enabled: bool = True
    vision_provider_enabled: bool = False
    stop_on_sensitive_window: bool = True

