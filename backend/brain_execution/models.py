from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..brain_orchestrator.models import BrainTaskEdge, BrainTaskNode
from ..brain_tool_router.models import BrainExecutionLog
from ..database import Base


class BrainExecutionRun(Base):
    __tablename__ = "brain_execution_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str | None] = mapped_column(String(120), index=True)
    employee_id: Mapped[str | None] = mapped_column(String(120), index=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="CREATED", index=True)
    priority: Mapped[str] = mapped_column(String(40), nullable=False, default="normal", index=True)
    context: Mapped[str | None] = mapped_column(Text)
    current_node: Mapped[str | None] = mapped_column(String(120), index=True)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, default="low", index=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(100), index=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    max_retry: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    worker_id: Mapped[str | None] = mapped_column(String(120), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class BrainExecutionEvent(Base):
    __tablename__ = "brain_execution_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    event_data: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class BrainExecutionContext(Base):
    __tablename__ = "execution_context"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    node_id: Mapped[str | None] = mapped_column(String(120), index=True)
    employee_code: Mapped[str | None] = mapped_column(String(100), index=True)
    current_task: Mapped[str | None] = mapped_column(Text)
    input_data: Mapped[str | None] = mapped_column(Text)
    tool_permissions: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, default="low", index=True)
    historical_execution: Mapped[str | None] = mapped_column(Text)
    approval_status: Mapped[str | None] = mapped_column(String(80), index=True)
    context_data: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class BrainWorkerStatus(Base):
    __tablename__ = "brain_worker_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="idle", index=True)
    current_execution_id: Mapped[int | None] = mapped_column(Integer, index=True)
    current_node_id: Mapped[str | None] = mapped_column(String(120), index=True)
    current_task: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timeout_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)


class BrainExecutionRecovery(Base):
    __tablename__ = "brain_execution_recovery"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    node_id: Mapped[str | None] = mapped_column(String(120), index=True)
    failure_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retry: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    recovery_action: Mapped[str | None] = mapped_column(Text)
    recovery_status: Mapped[str] = mapped_column(String(80), nullable=False, default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class BrainApprovalRecord(Base):
    __tablename__ = "brain_approval_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    node_id: Mapped[str | None] = mapped_column(String(120), index=True)
    approve_user: Mapped[str | None] = mapped_column(String(100), index=True)
    decision: Mapped[str] = mapped_column(String(40), nullable=False, default="pending", index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    boss_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    security_audited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class BrainToolCall(Base):
    __tablename__ = "brain_tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    node_id: Mapped[str | None] = mapped_column(String(120), index=True)
    employee_code: Mapped[str | None] = mapped_column(String(100), index=True)
    tool_name: Mapped[str | None] = mapped_column(String(120), index=True)
    request_payload: Mapped[str | None] = mapped_column(Text)
    response_payload: Mapped[str | None] = mapped_column(Text)
    permission_result: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, default="low", index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="simulated", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


__all__ = [
    "BrainApprovalRecord",
    "BrainExecutionContext",
    "BrainExecutionEvent",
    "BrainExecutionLog",
    "BrainExecutionRecovery",
    "BrainExecutionRun",
    "BrainTaskEdge",
    "BrainTaskNode",
    "BrainToolCall",
    "BrainWorkerStatus",
]
