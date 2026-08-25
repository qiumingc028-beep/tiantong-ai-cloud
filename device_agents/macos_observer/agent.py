from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .config import MacObserverConfig
from .permissions import MacObserverPermissionPolicy
from .sanitizer import SanitizedWindow, sanitize_window, summarize_windows
from .screen_capture import ScreenCaptureProvider, ScreenshotResult, StaticScreenCaptureProvider
from .vision import LocalRuleBasedVisionProvider, VisionProvider
from .transport import LocalObservationTransport, ObservationTransport
from .window_provider import StaticWindowProvider, WindowProvider, WindowSnapshot


@dataclass(slots=True)
class MacObservationPlan:
    device_code: str
    device_name: str
    allowed_applications: list[str] = field(default_factory=list)
    allowed_window_patterns: list[str] = field(default_factory=list)
    max_screenshots: int = 3
    stop_on_sensitive_window: bool = True


class MacReadonlyObserverAgent:
    def __init__(
        self,
        config: MacObserverConfig,
        *,
        window_provider: WindowProvider | None = None,
        screen_capture_provider: ScreenCaptureProvider | None = None,
        vision_provider: VisionProvider | None = None,
        transport: ObservationTransport | None = None,
        permission_policy: MacObserverPermissionPolicy | None = None,
    ):
        self.config = config
        self.window_provider = window_provider or StaticWindowProvider()
        self.screen_capture_provider = screen_capture_provider or StaticScreenCaptureProvider()
        self.vision_provider = vision_provider or LocalRuleBasedVisionProvider()
        self.transport = transport or LocalObservationTransport()
        self.permission_policy = permission_policy or MacObserverPermissionPolicy()

    def build_plan(self) -> MacObservationPlan:
        return MacObservationPlan(
            device_code=self.config.device_code,
            device_name=self.config.device_name,
            allowed_applications=list(self.config.allowed_applications),
            allowed_window_patterns=list(self.config.allowed_window_patterns),
            max_screenshots=self.config.max_screenshots,
            stop_on_sensitive_window=self.config.stop_on_sensitive_window,
        )

    def observe(self) -> dict[str, object]:
        windows = self.window_provider.list_windows() if self.config.window_enumeration_enabled else []
        sanitized = [sanitize_window(window) for window in windows]
        summary = summarize_windows(sanitized)
        vision_summary = self.vision_provider.analyze([{
            "application_name": window.application_name,
            "bundle_id": window.bundle_id,
            "window_title": window.window_title,
            "frontmost": window.frontmost,
            "screenshot_allowed": window.screenshot_allowed,
        } for window in sanitized])
        summary.update({
            "screen_state": vision_summary.screen_state,
            "has_loading": vision_summary.has_loading,
            "has_error": vision_summary.has_error,
            "has_confirmation_dialog": vision_summary.has_confirmation_dialog,
            "has_login_page": vision_summary.has_login_page,
            "recommended_next_step": vision_summary.suggested_next_step,
        })
        screenshots: list[ScreenshotResult] = []
        if self.config.capture_enabled and sanitized:
            for window in sanitized[: self.config.max_screenshots]:
                if not window.screenshot_allowed:
                    continue
                screenshots.append(self.screen_capture_provider.capture(window.window_title))
        if summary["sensitive_window_detected"] and self.config.stop_on_sensitive_window:
            summary["suggested_next_step"] = "请求人工处理敏感窗口"
        self.transport.send_observation(
            {
                "device_code": self.config.device_code,
                "device_name": self.config.device_name,
                "window_count": len(sanitized),
                "screenshots": [shot.reference for shot in screenshots],
            }
        )
        return {
            "plan": asdict(self.build_plan()),
            "windows": [asdict(window) for window in sanitized],
            "summary": summary,
            "screenshots": [asdict(shot) for shot in screenshots],
            "permissions": self.permission_policy.minimal_permissions(),
        }
