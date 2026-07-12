from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AlphaWorkflowTraceStep(BaseModel):
    step_code: str
    title: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AlphaWorkflowContext(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scenario_code: str
    scenario_title: str
    input_text: str
    task_id: int | None = None
    task_title: str | None = None
    task_status: str | None = None
    research_execution_id: str | None = None
    research_report_id: str | None = None
    knowledge_id: str | None = None
    knowledge_version_id: str | None = None
    skill_invocation_id: int | None = None
    report_title: str | None = None
    report_hash: str | None = None
    report_content: str | None = None
    dashboard_status: str | None = None
    trace_id: str
    step_trace: list[AlphaWorkflowTraceStep] = Field(default_factory=list)
    linked_ids: dict[str, Any] = Field(default_factory=dict)
    recovery_from_run_id: str | None = None


class AlphaWorkflowPlanStep(BaseModel):
    step_code: str
    title: str
    description: str
    expected_result: str
    module: str
    risk_level: str = "低"


class AlphaWorkflowPlan(BaseModel):
    scenario_code: str
    title: str
    description: str
    input_hint: str
    steps: list[AlphaWorkflowPlanStep] = Field(default_factory=list)
    max_steps: int = 7
    trace_id: str
