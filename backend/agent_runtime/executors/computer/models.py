from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ....database import Base


class ComputerSession(Base):
    __tablename__ = "computer_sessions"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    execution_id: Mapped[int | None] = mapped_column(ForeignKey("skill_invocations.id", ondelete="SET NULL"), nullable=True, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True, index=True)
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"), nullable=True, index=True)
    executor_type: Mapped[str] = mapped_column(String(40), nullable=False, default="mock", index=True)
    environment_type: Mapped[str] = mapped_column(String(40), nullable=False, default="test", index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="待创建", index=True)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, default="低风险", index=True)
    approval_status: Mapped[str] = mapped_column(String(40), nullable=False, default="无需审批", index=True)
    allowed_applications_json: Mapped[str | None] = mapped_column(Text)
    allowed_windows_json: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    takeover_status: Mapped[str] = mapped_column(String(40), nullable=False, default="未接管", index=True)
    last_screenshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    actions: Mapped[list["ComputerAction"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ComputerAction(Base):
    __tablename__ = "computer_actions"
    __table_args__ = (UniqueConstraint("session_id", "sequence_number", name="uq_computer_actions_sequence"),)

    action_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("computer_sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    target_application: Mapped[str | None] = mapped_column(String(120), index=True)
    target_window: Mapped[str | None] = mapped_column(String(255), index=True)
    target_description: Mapped[str | None] = mapped_column(Text)
    input_summary: Mapped[str | None] = mapped_column(Text)
    coordinates_json: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    approval_status: Mapped[str] = mapped_column(String(40), nullable=False, default="无需审批", index=True)
    screenshot_before: Mapped[str | None] = mapped_column(Text)
    screenshot_after: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(80), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)

    session: Mapped[ComputerSession] = relationship(back_populates="actions")


class ComputerEvidence(Base):
    __tablename__ = "computer_evidence"

    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("computer_sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    action_id: Mapped[str | None] = mapped_column(ForeignKey("computer_actions.action_id", ondelete="SET NULL"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class ComputerTakeover(Base):
    __tablename__ = "computer_takeovers"

    takeover_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("computer_sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by: Mapped[str | None] = mapped_column(String(80), index=True)
    requested_reason: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(80), index=True)
    approval_status: Mapped[str] = mapped_column(String(40), nullable=False, default="等待审批", index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="等待接管", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)


class ComputerPolicyEvent(Base):
    __tablename__ = "computer_policy_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), index=True)
    action_id: Mapped[str | None] = mapped_column(ForeignKey("computer_actions.action_id", ondelete="SET NULL"), index=True)
    event_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    event_message: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    sensitive_data_involved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
