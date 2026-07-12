from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class AgentCapability(Base):
    __tablename__ = "agent_capabilities"

    capability_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    capability_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    capability_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    executor_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True, default="mock")
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True, default="low")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    readonly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    requires_boss_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    requires_security_audit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_schema_json: Mapped[str | None] = mapped_column(Text)
    output_schema_json: Mapped[str | None] = mapped_column(Text)
    allowed_employee_codes_json: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(40), nullable=False, default="1.0.0", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class AgentExecution(Base):
    __tablename__ = "agent_executions"
    __table_args__ = (
        UniqueConstraint("trace_id", name="uq_agent_executions_trace_id"),
    )

    execution_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True, index=True)
    capability_id: Mapped[str] = mapped_column(ForeignKey("agent_capabilities.capability_id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending_validation", index=True)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, default="low", index=True)
    approval_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_required", index=True)
    executor_type: Mapped[str] = mapped_column(String(40), nullable=False, default="mock", index=True)
    input_payload: Mapped[str | None] = mapped_column(Text)
    output_payload: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    trace_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    capability: Mapped[AgentCapability] = relationship()


class AgentExecutionAudit(Base):
    __tablename__ = "agent_execution_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("agent_executions.execution_id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(120))
    approval_status: Mapped[str | None] = mapped_column(String(40), index=True)
    approval_decision: Mapped[str | None] = mapped_column(String(40))
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    input_summary: Mapped[str | None] = mapped_column(Text)
    output_summary: Mapped[str | None] = mapped_column(Text)
    error_summary: Mapped[str | None] = mapped_column(Text)
    executor_name: Mapped[str | None] = mapped_column(String(80))
    source_ip: Mapped[str | None] = mapped_column(String(120))
    sensitive_data_involved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

