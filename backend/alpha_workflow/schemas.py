from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AlphaWorkflowScenarioCreate(BaseModel):
    scenario_code: str = Field(min_length=2, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    input_hint: str | None = None
    default_input_text: str | None = None
    workflow_template: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class AlphaWorkflowStartRequest(BaseModel):
    input_text: str = Field(min_length=1, max_length=500)
    trace_id: str | None = None
    scenario_code: str | None = None


class AlphaWorkflowRecoverRequest(BaseModel):
    reason: str | None = None


class AlphaWorkflowEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    event_code: str
    stage: str
    status: str
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    trace_id: str
    created_at: datetime | None = None


class AlphaWorkflowRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    scenario_id: str
    task_id: int | None = None
    research_execution_id: str | None = None
    knowledge_id: str | None = None
    skill_invocation_id: int | None = None
    status: str
    quality_score: int | None = None
    quality_grade: str | None = None
    risk_score: int | None = None
    risk_level: str | None = None
    failure_reason: str | None = None
    recovery_status: str | None = None
    workflow_context: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] = Field(default_factory=dict)
    report_summary: dict[str, Any] = Field(default_factory=dict)
    dashboard_summary: dict[str, Any] = Field(default_factory=dict)
    trace_id: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    recovered_from_run_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AlphaWorkflowScenarioView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scenario_id: str
    scenario_code: str
    title: str
    description: str | None = None
    input_hint: str | None = None
    default_input_text: str | None = None
    workflow_template: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None
