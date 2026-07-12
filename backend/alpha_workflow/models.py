from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class AlphaWorkflowScenario(Base):
    __tablename__ = "alpha_workflow_scenarios"
    __table_args__ = (UniqueConstraint("scenario_code", name="uq_alpha_workflow_scenarios_code"),)

    scenario_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scenario_code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    input_hint: Mapped[str | None] = mapped_column(String(200))
    default_input_text: Mapped[str | None] = mapped_column(Text)
    workflow_template_json: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    created_by = relationship("User")


class AlphaWorkflowRun(Base):
    __tablename__ = "alpha_workflow_runs"
    __table_args__ = (UniqueConstraint("trace_id", name="uq_alpha_workflow_runs_trace_id"),)

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scenario_id: Mapped[str] = mapped_column(ForeignKey("alpha_workflow_scenarios.scenario_id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(120), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(80), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), index=True)
    orchestrator_run_id: Mapped[str | None] = mapped_column(String(120), index=True)
    research_execution_id: Mapped[str | None] = mapped_column(String(36), index=True)
    research_report_id: Mapped[str | None] = mapped_column(String(36), index=True)
    knowledge_id: Mapped[str | None] = mapped_column(String(36), index=True)
    knowledge_asset_id: Mapped[str | None] = mapped_column(String(36), index=True)
    knowledge_version_id: Mapped[str | None] = mapped_column(String(36), index=True)
    skill_id: Mapped[str | None] = mapped_column(String(120), index=True)
    skill_version_id: Mapped[str | None] = mapped_column(String(120), index=True)
    skill_invocation_id: Mapped[int | None] = mapped_column(Integer, index=True)
    agent_execution_id: Mapped[str | None] = mapped_column(String(36), index=True)
    verification_id: Mapped[str | None] = mapped_column(String(120), index=True)
    root_span_id: Mapped[str | None] = mapped_column(String(120), index=True)
    approval_ids_json: Mapped[str | None] = mapped_column(Text)
    current_stage: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="草稿", index=True)
    quality_score: Mapped[int | None] = mapped_column(Integer, index=True)
    quality_grade: Mapped[str | None] = mapped_column(String(20), index=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, index=True)
    risk_level: Mapped[str | None] = mapped_column(String(20), index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    recovery_status: Mapped[str | None] = mapped_column(String(40), index=True)
    workflow_context_json: Mapped[str | None] = mapped_column(Text)
    plan_json: Mapped[str | None] = mapped_column(Text)
    report_summary_json: Mapped[str | None] = mapped_column(Text)
    dashboard_summary_json: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    recovered_from_run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    scenario = relationship("AlphaWorkflowScenario")
    created_by = relationship("User", foreign_keys=[created_by_id])


class AlphaWorkflowEvent(Base):
    __tablename__ = "alpha_workflow_events"
    __table_args__ = (UniqueConstraint("event_id", name="uq_alpha_workflow_events_id"),)

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("alpha_workflow_runs.run_id", ondelete="CASCADE"), nullable=False, index=True)
    event_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    message: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[str | None] = mapped_column(Text)
    span_id: Mapped[str | None] = mapped_column(String(120), index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(120), index=True)
    span_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="child", index=True)
    trace_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    run = relationship("AlphaWorkflowRun")
