from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.agent_runtime.executors.computer.actions.policy import (
    ensure_action_type_allowed,
    ensure_coordinates_safe,
    ensure_file_transfer_disabled,
    ensure_safe_action_enabled,
    ensure_target_application_allowed,
    ensure_target_control_allowed,
    ensure_text_safe,
)

from .constants import DEFAULT_MAX_STEPS, DEFAULT_MIN_STEPS, WORKFLOW_ACTION_TYPES


def validate_workflow_flags() -> None:
    settings = get_settings()
    if not settings.MAC_SAFE_WORKFLOW_ENABLED:
        raise HTTPException(status_code=403, detail="安全多步骤工作流功能当前未开启")
    if not settings.MAC_MULTI_STEP_ENABLED:
        raise HTTPException(status_code=403, detail="多步骤工作流功能当前未开启")
    if not settings.WORKFLOW_SCOPE_APPROVAL_ENABLED:
        raise HTTPException(status_code=403, detail="工作流范围审批当前未开启")
    if not settings.WORKFLOW_CHECKPOINT_APPROVAL_ENABLED:
        raise HTTPException(status_code=403, detail="工作流关键节点审批当前未开启")
    if settings.WORKFLOW_AUTO_CONTINUE_ENABLED:
        raise HTTPException(status_code=403, detail="自动连续执行必须保持关闭")


def validate_step_payload(step: dict) -> None:
    action_type = str(step.get("action_type") or "").strip()
    if action_type not in WORKFLOW_ACTION_TYPES:
        raise HTTPException(status_code=403, detail="步骤动作类型不被允许")
    ensure_action_type_allowed(action_type)
    ensure_target_application_allowed(step.get("target_application"))
    ensure_target_control_allowed(step.get("target_control") or None, step.get("target_control") or None, None, step.get("target_window") or None)
    ensure_text_safe(step.get("text_input"))
    ensure_coordinates_safe(step.get("coordinates"))
    if step.get("text_input"):
        ensure_file_transfer_disabled()
    if action_type == "输入普通文本":
        ensure_safe_action_enabled()


def validate_workflow_plan(steps: list[dict]) -> None:
    count = len(steps)
    if count < DEFAULT_MIN_STEPS:
        raise HTTPException(status_code=403, detail="工作流步骤数量不足")
    if count > DEFAULT_MAX_STEPS:
        raise HTTPException(status_code=403, detail="工作流步骤数量超限")
    for step in steps:
        validate_step_payload(step)
