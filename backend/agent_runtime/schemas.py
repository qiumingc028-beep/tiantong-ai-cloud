from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentCapabilityBase(BaseModel):
    capability_id: str = Field(min_length=1, max_length=120)
    capability_name: str = Field(min_length=1, max_length=200)
    capability_type: str = Field(min_length=1, max_length=80)
    description: str | None = None
    executor_type: str = "mock"
    risk_level: str = "low"
    enabled: bool = True
    readonly: bool = True
    requires_boss_approval: bool = False
    requires_security_audit: bool = False
    timeout_seconds: int = 30
    max_retries: int = 0
    input_schema_json: str | None = None
    output_schema_json: str | None = None
    allowed_employee_codes: list[str] = Field(default_factory=list)
    version: str = "1.0.0"


class AgentCapabilityCreate(AgentCapabilityBase):
    pass


class AgentCapabilityUpdate(BaseModel):
    capability_name: str | None = None
    capability_type: str | None = None
    description: str | None = None
    executor_type: str | None = None
    risk_level: str | None = None
    enabled: bool | None = None
    readonly: bool | None = None
    requires_boss_approval: bool | None = None
    requires_security_audit: bool | None = None
    timeout_seconds: int | None = None
    max_retries: int | None = None
    input_schema_json: str | None = None
    output_schema_json: str | None = None
    allowed_employee_codes: list[str] | None = None
    version: str | None = None


class AgentCapabilityRead(AgentCapabilityBase):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentExecutionCreate(BaseModel):
    task_id: int | None = None
    employee_id: int
    capability_id: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    executor_type: str | None = None
    trace_id: str | None = None
    link_task_result: bool = False


class AgentExecutionApprove(BaseModel):
    boss_confirmed: bool = True
    security_audited: bool = True


class AgentExecutionReject(BaseModel):
    reason: str | None = None


class AgentExecutionCancel(BaseModel):
    reason: str | None = None


class AgentExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    execution_id: str
    task_id: int | None
    employee_id: int | None
    employee_code: str | None = None
    employee_name: str | None = None
    capability_id: str
    capability_name: str | None = None
    capability_type: str | None = None
    status: str
    status_label: str
    risk_level: str
    approval_status: str
    approval_status_label: str
    executor_type: str
    input_payload: dict[str, Any] | None = None
    output_payload: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    trace_id: str
    created_by_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentExecutionAuditRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    execution_id: str
    event_type: str
    event_label: str
    actor_type: str
    actor_id: str | None = None
    approval_status: str | None = None
    approval_decision: str | None = None
    risk_level: str
    input_summary: str | None = None
    output_summary: str | None = None
    error_summary: str | None = None
    executor_name: str | None = None
    source_ip: str | None = None
    sensitive_data_involved: bool = False
    trace_id: str
    created_at: datetime | None = None
