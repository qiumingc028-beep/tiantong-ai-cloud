from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class VisionAnalysisResult:
    screen_state: str
    has_loading: bool = False
    has_error: bool = False
    has_confirmation_dialog: bool = False
    has_login_page: bool = False
    sensitive_region_detected: bool = False
    suggested_next_step: str = "继续只读观察"


class VisionProvider(Protocol):
    def analyze(self, windows: list[dict[str, object]]) -> VisionAnalysisResult:
        ...


class LocalRuleBasedVisionProvider:
    def analyze(self, windows: list[dict[str, object]]) -> VisionAnalysisResult:
        titles = " ".join(str(window.get("window_title") or "") for window in windows)
        lowered = titles.lower()
        sensitive = any(term in lowered for term in ["password", "token", "secret", "验证码", "银行卡", "身份证", "keychain", "钥匙串"])
        login = any(term in lowered for term in ["登录", "login", "sign in"])
        error = any(term in lowered for term in ["错误", "error", "failed", "失败"])
        loading = any(term in lowered for term in ["加载中", "loading", "..."])
        confirm = any(term in lowered for term in ["确认", "confirm", "allow"])
        return VisionAnalysisResult(
            screen_state="检测到敏感窗口" if sensitive else ("存在登录页面" if login else ("存在错误提示" if error else "页面状态正常")),
            has_loading=loading,
            has_error=error,
            has_confirmation_dialog=confirm,
            has_login_page=login,
            sensitive_region_detected=sensitive,
            suggested_next_step="请求人工处理敏感窗口" if sensitive else ("等待页面加载完成" if loading else "继续只读观察"),
        )


class ExternalVisionProvider:
    def analyze(self, windows: list[dict[str, object]]) -> VisionAnalysisResult:  # pragma: no cover - explicit off
        raise RuntimeError("外部视觉模型默认关闭")

