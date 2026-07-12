from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .constants import WORKFLOW_ACTION_TYPES, WORKFLOW_CHECKPOINT_TYPES, WORKFLOW_STEP_STATUSES, WORKFLOW_STATUSES


class WorkflowStepInput(BaseModel):
    action_type: str
    target_application: str | None = None
    target_bundle_id: str | None = None
    target_window: str | None = None
    target_control: str | None = None
    input_summary: str | None = None
    expected_result: str | None = None
    risk_level: str = "低风险"
    approval_required: bool = False
    checkpoint_required: bool = False
    coordinates: dict[str, int] | None = None
    text_input: str | None = None
    screenshot_before_reference: str | None = None
    screenshot_before_hash: str | None = None
    trace_id: str | None = None

    @field_validator("action_type")
    @classmethod
    def validate_action_type(cls, value: str):
        if value not in WORKFLOW_ACTION_TYPES:
            raise ValueError("工作流动作类型不被允许")
        return value


class ComputerWorkflowCreatePayload(BaseModel):
    task_id: int | None = None
    employee_id: int | None = None
    skill_id: int | None = None
    device_id: str | None = None
    session_id: str | None = None
    goal: str
    risk_level: str = "低风险"
    total_steps: int | None = None
    max_steps: int = Field(default=5, ge=2, le=5)
    execution_budget: dict[str, Any] | None = None
    steps: list[WorkflowStepInput] = Field(default_factory=list)
    trace_id: str | None = None


class ComputerWorkflowView(BaseModel):
    workflow_id: str
    task_id: int | None = None
    employee_id: int | None = None
    skill_id: int | None = None
    device_id: str | None = None
    session_id: str | None = None
    goal: str
    status: str
    risk_level: str
    approval_status: str
    total_steps: int
    current_step: int
    max_steps: int
    checkpoint_count: int
    execution_budget: dict[str, Any] | None = None
    started_at: datetime | None = None
    expires_at: datetime | None = None
    finished_at: datetime | None = None
    stop_reason: str | None = None
    trace_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str):
        if value not in WORKFLOW_STATUSES:
            raise ValueError("工作流状态不被允许")
        return value


class ComputerWorkflowStepView(BaseModel):
    step_id: str
    workflow_id: str
    sequence_number: int
    action_type: str
    target_application: str | None = None
    target_bundle_id: str | None = None
    target_window: str | None = None
    target_control: str | None = None
    input_summary: str | None = None
    expected_result: str | None = None
    risk_level: str
    approval_required: bool
    checkpoint_required: bool
    status: str
    action_id: str | None = None
    verification_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    trace_id: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str):
        if value not in WORKFLOW_STEP_STATUSES:
            raise ValueError("工作流步骤状态不被允许")
        return value


class ComputerWorkflowCheckpointView(BaseModel):
    checkpoint_id: str
    workflow_id: str
    step_id: str | None = None
    checkpoint_type: str
    reason: str | None = None
    screenshot_reference: str | None = None
    state_summary: str | None = None
    risk_level: str
    approval_status: str
    approved_by: int | None = None
    approved_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None

    @field_validator("checkpoint_type")
    @classmethod
    def validate_checkpoint_type(cls, value: str):
        if value not in WORKFLOW_CHECKPOINT_TYPES:
            raise ValueError("关键节点类型不被允许")
        return value
