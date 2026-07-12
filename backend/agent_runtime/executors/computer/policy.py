from __future__ import annotations

import re
from urllib.parse import urlparse

from fastapi import HTTPException

from ....config import get_settings
from .constants import DEFAULT_ALLOWED_APPLICATIONS, DEFAULT_BLOCKED_APPLICATIONS, HIGH_RISK_ACTION_KEYWORDS


def _normalize_list(values: list[str] | None) -> list[str]:
    return [str(value).strip() for value in (values or []) if str(value).strip()]


def allowed_applications() -> list[str]:
    settings = get_settings()
    if settings.COMPUTER_ALLOWED_APPLICATIONS:
        return list(settings.COMPUTER_ALLOWED_APPLICATIONS)
    if settings.IS_PRODUCTION:
        return []
    return list(DEFAULT_ALLOWED_APPLICATIONS)


def blocked_applications() -> list[str]:
    settings = get_settings()
    blocked = list(DEFAULT_BLOCKED_APPLICATIONS)
    blocked.extend(settings.COMPUTER_BLOCKED_APPLICATIONS)
    return blocked


def allowed_windows() -> list[str]:
    settings = get_settings()
    if settings.COMPUTER_ALLOWED_WINDOW_PATTERNS:
        return list(settings.COMPUTER_ALLOWED_WINDOW_PATTERNS)
    if settings.IS_PRODUCTION:
        return []
    return [".*隔离.*", ".*测试.*", ".*演示.*"]


def blocked_windows() -> list[str]:
    settings = get_settings()
    return list(settings.COMPUTER_BLOCKED_WINDOW_PATTERNS)


def ensure_executor_enabled() -> None:
    settings = get_settings()
    if not settings.COMPUTER_EXECUTOR_ENABLED:
        raise HTTPException(status_code=403, detail="电脑执行器当前未开启")


def ensure_real_adapter_enabled() -> None:
    settings = get_settings()
    if not settings.OPENCLAW_ADAPTER_ENABLED and not settings.ISOLATED_DESKTOP_ENABLED:
        raise HTTPException(status_code=403, detail="电脑执行适配层未开启")


def ensure_screen_capture_enabled() -> None:
    settings = get_settings()
    if not settings.SCREEN_CAPTURE_ENABLED:
        raise HTTPException(status_code=403, detail="截图功能当前未开启")


def ensure_human_takeover_enabled() -> None:
    settings = get_settings()
    if not settings.HUMAN_TAKEOVER_ENABLED:
        raise HTTPException(status_code=403, detail="人工接管功能当前未开启")


def ensure_application_allowed(application: str | None) -> None:
    application = (application or "").strip()
    if not application:
        return
    allowed = allowed_applications()
    blocked = blocked_applications()
    if any(token and token.lower() in application.lower() for token in blocked):
        raise HTTPException(status_code=403, detail="目标应用不允许执行")
    if allowed and application not in allowed:
        raise HTTPException(status_code=403, detail="目标应用不在白名单内")


def ensure_window_allowed(window: str | None) -> None:
    window = (window or "").strip()
    if not window:
        return
    blocked = blocked_windows()
    if any(pattern and re.search(pattern, window, flags=re.IGNORECASE) for pattern in blocked):
        raise HTTPException(status_code=403, detail="目标窗口不在白名单内")
    allowed = allowed_windows()
    if allowed and allowed != ["*"]:
        if not any(pattern == "*" or re.search(pattern, window, flags=re.IGNORECASE) for pattern in allowed):
            raise HTTPException(status_code=403, detail="目标窗口不在白名单内")


def ensure_text_safe(text: str | None) -> None:
    content = (text or "").strip()
    if not content:
        return
    lowered = content.lower()
    forbidden = ["password", "token", "cookie", "secret", "private key", "验证码", "银行卡", "身份证", "ssh"]
    if any(term in lowered for term in forbidden):
        raise HTTPException(status_code=403, detail="敏感输入不允许自动写入")


def ensure_action_allowed(action_type: str, target_application: str | None = None, target_window: str | None = None, text_input: str | None = None) -> None:
    high_risk = any(keyword.lower() in f"{action_type} {target_application or ''} {target_window or ''} {text_input or ''}".lower() for keyword in HIGH_RISK_ACTION_KEYWORDS)
    if action_type in {"取消任务"}:
        return
    if action_type in {"返回上一步", "等待", "截图", "查看屏幕", "获取窗口列表"}:
        return
    if action_type in {"移动鼠标", "单击", "双击", "滚动"}:
        return
    if action_type == "输入普通文本":
        ensure_text_safe(text_input)
        return
    if action_type == "按允许的快捷键":
        allowed_hotkeys = {"Enter", "Esc", "Tab", "Shift+Tab", "Escape", "方向上", "方向下", "方向左", "方向右"}
        if (text_input or "").strip() not in allowed_hotkeys:
            raise HTTPException(status_code=403, detail="快捷键不在允许范围内")
        return
    if high_risk:
        raise HTTPException(status_code=403, detail="高风险动作默认禁止")
    raise HTTPException(status_code=403, detail="电脑操作类型不允许")


def detect_sensitive_region(window_title: str | None, target_application: str | None, text_input: str | None = None) -> bool:
    tokens = [window_title or "", target_application or "", text_input or ""]
    lowered = " ".join(tokens).lower()
    sensitive = ["密码", "token", "cookie", "keychain", "钥匙串", "bank", "银行卡", "验证码", "secret", "ssh"]
    return any(term in lowered for term in sensitive)


def validate_url_like_reference(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"file", "http", "https", "about"} and bool(parsed.netloc or parsed.scheme == "about")
