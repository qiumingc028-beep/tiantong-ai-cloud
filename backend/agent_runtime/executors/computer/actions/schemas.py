from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .constants import ACTION_CONTROL_TYPES, ACTION_PLAN_STATUSES, ACTION_APPROVAL_STATUSES, ACTION_VERIFICATION_STATUSES, SAFE_ACTION_TYPES, SAFE_SHORTCUTS


class ComputerActionPlanCreatePayload(BaseModel):
    session_id: str
    observation_id: str | None = None
    task_id: int | None = None
    employee_id: int | None = None
    skill_id: int | None = None
    target_application: str | None = None
    target_bundle_id: str | None = None
    target_window: str | None = None
    goal: str
    action_type: str
    control_type: str | None = None
    control_label: str | None = None
    control_identifier: str | None = None
    target_description: str | None = None
    coordinates: dict[str, int] | None = None
    text_input: str | None = None
    approval_mode: str = "逐步审批"
    risk_level: str = "中低"
    max_actions: int = 1
    trace_id: str | None = None
    allow_coordinate_fallback: bool = False

    @field_validator("action_type")
    @classmethod
    def validate_action_type(cls, value: str):
        if value not in SAFE_ACTION_TYPES:
            raise ValueError("动作类型不被允许")
        return value

    @field_validator("control_type")
    @classmethod
    def validate_control_type(cls, value: str | None):
        if value and value not in ACTION_CONTROL_TYPES:
            raise ValueError("控件类型不被允许")
        return value


class ComputerActionPlanView(BaseModel):
    plan_id: str
    session_id: str
    observation_id: str | None = None
    task_id: int | None = None
    employee_id: int | None = None
    skill_id: int | None = None
    target_application: str | None = None
    target_bundle_id: str | None = None
    target_window: str | None = None
    goal: str
    proposed_actions: list[dict[str, Any]]
    current_action_index: int
    max_actions: int
    risk_level: str
    approval_mode: str
    status: str
    expires_at: datetime | None = None
    trace_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str):
        if value not in ACTION_PLAN_STATUSES:
            raise ValueError("动作计划状态不被允许")
        return value


class ComputerActionPreviewView(BaseModel):
    plan: ComputerActionPlanView
    preview: dict[str, Any]


class ComputerActionApprovalPayload(BaseModel):
    approval_range: str | None = None
    note: str | None = None
    trace_id: str | None = None


class ComputerActionRejectPayload(BaseModel):
    reason: str | None = None
    trace_id: str | None = None


class ComputerActionExecutePayload(BaseModel):
    current_application: str | None = None
    current_window: str | None = None
    current_screenshot_hash: str | None = None
    trace_id: str | None = None


class ComputerActionVerificationView(BaseModel):
    verification_id: str
    plan_id: str
    action_id: str
    verification_status: str
    expected_window: str | None = None
    expected_application: str | None = None
    before_screenshot_reference: str | None = None
    after_screenshot_reference: str | None = None
    before_screenshot_hash: str | None = None
    after_screenshot_hash: str | None = None
    result_summary: str | None = None
    trace_id: str | None = None
    created_at: datetime | None = None

    @field_validator("verification_status")
    @classmethod
    def validate_verification_status(cls, value: str):
        if value not in ACTION_VERIFICATION_STATUSES:
            raise ValueError("动作验证状态不被允许")
        return value
