from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .constants import ALPHA_WORKFLOW_STATUSES


class AlphaWorkflowTraceSpan(BaseModel):
    span_id: str
    parent_span_id: str | None = None
    span_name: str
    span_kind: str = "child"
    stage: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AlphaWorkflowContext(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="allow")

    workflow_id: str
    tenant_id: str
    user_id: int | None = None
    task_id: int | None = None
    orchestrator_run_id: str | None = None
    research_execution_id: str | None = None
    research_report_id: str | None = None
    knowledge_asset_id: str | None = None
    knowledge_version_id: str | None = None
    skill_id: str | None = None
    skill_version_id: str | None = None
    skill_invocation_id: int | None = None
    agent_execution_id: str | None = None
    verification_id: str | None = None
    trace_id: str
    root_span_id: str
    approval_ids: list[str] = Field(default_factory=list)
    risk_score: int | None = None
    quality_score: int | None = None
    current_stage: str = "orchestrator"
    status: str = "草稿"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    scenario_code: str | None = None
    scenario_title: str | None = None
    input_text: str | None = None
    task_title: str | None = None
    task_status: str | None = None
    report_title: str | None = None
    report_hash: str | None = None
    report_content: str | None = None
    dashboard_status: str | None = None
    step_trace: list[AlphaWorkflowTraceSpan] = Field(default_factory=list)
    stage_history: list[dict[str, Any]] = Field(default_factory=list)
    linked_ids: dict[str, Any] = Field(default_factory=dict)
    recovery_from_run_id: str | None = None

    @property
    def trace_root(self) -> str:
        return self.root_span_id

    def set_stage(self, stage: str, status: str, *, message: str | None = None, metadata: dict[str, Any] | None = None) -> AlphaWorkflowTraceSpan:
        now = datetime.now(timezone.utc)
        span = AlphaWorkflowTraceSpan(
            span_id=f"{self.root_span_id}:{stage}:{len(self.step_trace) + 1}",
            parent_span_id=self.root_span_id,
            span_name=stage,
            stage=stage,
            status=status,
            started_at=now,
            finished_at=now,
            message=message,
            metadata=metadata or {},
        )
        self.step_trace.append(span)
        self.stage_history.append(
            {
                "stage": stage,
                "status": status,
                "message": message,
                "metadata": metadata or {},
            }
        )
        self.current_stage = stage
        self.updated_at = datetime.now(timezone.utc)
        return span

    def ensure_valid_status(self) -> None:
        if self.status not in ALPHA_WORKFLOW_STATUSES:
            raise ValueError(f"invalid alpha workflow status: {self.status}")


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
    root_span_id: str | None = None
