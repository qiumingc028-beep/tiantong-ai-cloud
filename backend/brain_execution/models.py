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
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="CREATED", index=True)
    current_node: Mapped[str | None] = mapped_column(String(120), index=True)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, default="low", index=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(100), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class BrainExecutionEvent(Base):
    __tablename__ = "brain_execution_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    event_data: Mapped[str | None] = mapped_column(Text)
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
    "BrainExecutionEvent",
    "BrainExecutionLog",
    "BrainExecutionRun",
    "BrainTaskEdge",
    "BrainTaskNode",
    "BrainToolCall",
]
