from __future__ import annotations

from fastapi import HTTPException

from backend.config import get_settings
from ..constants import DEFAULT_BLOCKED_APPLICATIONS, HIGH_RISK_ACTION_KEYWORDS
from .constants import DEFAULT_FORBIDDEN_TARGETS, SAFE_ACTION_TYPES, SAFE_SHORTCUTS


def ensure_safe_action_enabled() -> None:
    settings = get_settings()
    if not settings.MAC_SAFE_ACTION_ENABLED:
        raise HTTPException(status_code=403, detail="安全单步操作功能当前未开启")


def ensure_move_enabled() -> None:
    settings = get_settings()
    if not settings.MAC_SAFE_MOUSE_MOVE_ENABLED:
        raise HTTPException(status_code=403, detail="鼠标移动功能当前未开启")


def ensure_click_enabled() -> None:
    settings = get_settings()
    if not settings.MAC_SAFE_CLICK_ENABLED:
        raise HTTPException(status_code=403, detail="安全单击功能当前未开启")


def ensure_text_input_enabled() -> None:
    settings = get_settings()
    if not settings.MAC_SAFE_TEXT_INPUT_ENABLED:
        raise HTTPException(status_code=403, detail="安全文本输入功能当前未开启")


def ensure_per_action_approval_enabled() -> None:
    settings = get_settings()
    if not settings.PER_ACTION_APPROVAL_ENABLED:
        raise HTTPException(status_code=403, detail="逐步审批功能当前未开启")


def ensure_post_action_verification_enabled() -> None:
    settings = get_settings()
    if not settings.POST_ACTION_VERIFICATION_ENABLED:
        raise HTTPException(status_code=403, detail="动作后验证功能当前未开启")


def ensure_clipboard_disabled() -> None:
    settings = get_settings()
    if getattr(settings, "CLIPBOARD_READ_ENABLED", False) or getattr(settings, "CLIPBOARD_WRITE_ENABLED", False):
        raise HTTPException(status_code=403, detail="剪贴板能力必须保持关闭")


def ensure_file_transfer_disabled() -> None:
    settings = get_settings()
    if getattr(settings, "FILE_UPLOAD_ENABLED", False) or getattr(settings, "FILE_DOWNLOAD_ENABLED", False):
        raise HTTPException(status_code=403, detail="文件传输能力必须保持关闭")


def ensure_action_type_allowed(action_type: str) -> None:
    if action_type not in SAFE_ACTION_TYPES:
        raise HTTPException(status_code=403, detail="动作类型不被允许")


def ensure_target_application_allowed(target_application: str | None) -> None:
    blocked = [item.lower() for item in DEFAULT_BLOCKED_APPLICATIONS]
    value = (target_application or "").strip().lower()
    if any(token and token in value for token in blocked):
        raise HTTPException(status_code=403, detail="目标应用不被允许")
    if any(term.lower() in value for term in HIGH_RISK_ACTION_KEYWORDS):
        raise HTTPException(status_code=403, detail="高风险目标不被允许")


def ensure_target_control_allowed(control_type: str | None, control_label: str | None, control_identifier: str | None, target_description: str | None = None) -> None:
    text = " ".join(part or "" for part in [control_type, control_label, control_identifier, target_description]).lower()
    for item in DEFAULT_FORBIDDEN_TARGETS:
        if item.lower() in text:
            raise HTTPException(status_code=403, detail="目标控件不被允许")


def ensure_text_safe(text_input: str | None) -> None:
    text = (text_input or "").strip()
    if not text:
        return
    lowered = text.lower()
    for token in ("password", "验证码", "token", "cookie", "api key", "secret", "private key", "sql", "shell", "ssh", "银行卡", "身份证"):
        if token in lowered:
            raise HTTPException(status_code=403, detail="敏感文本不允许输入")


def ensure_shortcut_safe(shortcut: str | None) -> None:
    value = (shortcut or "").strip()
    if value not in SAFE_SHORTCUTS:
        raise HTTPException(status_code=403, detail="快捷键不被允许")
    if value not in {"Tab", "Shift+Tab", "Escape", "Enter", "方向上", "方向下", "方向左", "方向右"}:
        raise HTTPException(status_code=403, detail="快捷键不被允许")


def ensure_coordinates_safe(coordinates: dict[str, int] | None) -> None:
    if not coordinates:
        return
    x = coordinates.get("x")
    y = coordinates.get("y")
    if not isinstance(x, int) or not isinstance(y, int):
        raise HTTPException(status_code=403, detail="坐标不合法")
    if x < 0 or y < 0:
        raise HTTPException(status_code=403, detail="坐标不合法")
