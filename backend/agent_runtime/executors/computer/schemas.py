from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .constants import ACTION_TYPES, SESSION_STATUSES, TAKEOVER_STATUSES


class ComputerExecutionContext(BaseModel):
    execution_id: int | None = None
    task_id: int | None = None
    employee_id: int | None = None
    skill_id: int | None = None
    session_id: str | None = None
    action_type: str | None = None
    target_application: str | None = None
    target_window: str | None = None
    coordinates: dict[str, int] | None = None
    text_input: str | None = None
    timeout: int = 30
    trace_id: str | None = None
    approval_context: dict[str, Any] | None = None


class ComputerActionPayload(BaseModel):
    action_type: str
    target_application: str | None = None
    target_window: str | None = None
    target_description: str | None = None
    coordinates: dict[str, int] | None = None
    text_input: str | None = None
    timeout: int = 30
    trace_id: str | None = None
    approval_context: dict[str, Any] | None = None
    simulate_outcome: str | None = None

    @field_validator("action_type")
    @classmethod
    def validate_action_type(cls, value: str):
        if value not in ACTION_TYPES:
            raise ValueError("动作类型不被允许")
        return value


class ComputerSessionCreatePayload(BaseModel):
    execution_id: int | None = None
    task_id: int | None = None
    employee_id: int | None = None
    skill_id: int | None = None
    executor_type: str = "mock"
    environment_type: str = "test"
    risk_level: str = "低风险"
    approval_status: str = "无需审批"
    allowed_applications: list[str] = Field(default_factory=list)
    allowed_windows: list[str] = Field(default_factory=list)
    trace_id: str | None = None


class ComputerSessionView(BaseModel):
    session_id: str
    execution_id: int | None = None
    task_id: int | None = None
    employee_id: int | None = None
    skill_id: int | None = None
    executor_type: str
    environment_type: str
    status: str
    risk_level: str
    approval_status: str
    allowed_applications: list[str]
    allowed_windows: list[str]
    started_at: datetime | None = None
    expires_at: datetime | None = None
    ended_at: datetime | None = None
    takeover_status: str
    last_screenshot_at: datetime | None = None
    trace_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str):
        if value not in SESSION_STATUSES:
            raise ValueError("会话状态不被允许")
        return value

    @field_validator("takeover_status")
    @classmethod
    def validate_takeover_status(cls, value: str):
        if value not in TAKEOVER_STATUSES:
            raise ValueError("接管状态不被允许")
        return value


class ComputerActionView(BaseModel):
    action_id: str
    session_id: str
    sequence_number: int
    action_type: str
    target_application: str | None = None
    target_window: str | None = None
    target_description: str | None = None
    input_summary: str | None = None
    coordinates: dict[str, int] | None = None
    risk_level: str
    approval_required: bool
    approval_status: str
    screenshot_before: str | None = None
    screenshot_after: str | None = None
    result: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    trace_id: str | None = None
