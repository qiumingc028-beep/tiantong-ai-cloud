from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .....database import Base


class ComputerActionPlan(Base):
    __tablename__ = "computer_action_plans"

    plan_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("computer_sessions.session_id", ondelete="CASCADE"), nullable=False, index=True)
    observation_id: Mapped[str | None] = mapped_column(ForeignKey("device_observation_sessions.observation_id", ondelete="SET NULL"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("ai_employees.id", ondelete="SET NULL"), index=True)
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"), index=True)
    target_application: Mapped[str | None] = mapped_column(String(120), index=True)
    target_bundle_id: Mapped[str | None] = mapped_column(String(180), index=True)
    target_window: Mapped[str | None] = mapped_column(String(255), index=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_actions_json: Mapped[str] = mapped_column(Text, nullable=False)
    current_action_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_actions: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    approval_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="逐步审批", index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="草稿", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    targets: Mapped[list["ComputerActionTarget"]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    approvals: Mapped[list["ComputerActionApproval"]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    verifications: Mapped[list["ComputerActionVerification"]] = relationship(back_populates="plan", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("session_id", "trace_id", name="uq_computer_action_plans_session_trace"),)


class ComputerActionTarget(Base):
    __tablename__ = "computer_action_targets"

    target_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("computer_action_plans.plan_id", ondelete="CASCADE"), nullable=False, index=True)
    action_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    control_type: Mapped[str | None] = mapped_column(String(80), index=True)
    control_label: Mapped[str | None] = mapped_column(String(255), index=True)
    control_identifier: Mapped[str | None] = mapped_column(String(255), index=True)
    target_description: Mapped[str | None] = mapped_column(Text)
    expected_window: Mapped[str | None] = mapped_column(String(255), index=True)
    expected_application: Mapped[str | None] = mapped_column(String(120), index=True)
    coordinates_json: Mapped[str | None] = mapped_column(Text)
    input_text_summary: Mapped[str | None] = mapped_column(Text)
    screenshot_before_reference: Mapped[str | None] = mapped_column(Text)
    screenshot_before_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="待校验", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    plan: Mapped[ComputerActionPlan] = relationship(back_populates="targets")

    __table_args__ = (UniqueConstraint("plan_id", "action_id", name="uq_computer_action_targets_plan_action"), UniqueConstraint("action_id", name="uq_computer_action_targets_action_id"))


class ComputerActionApproval(Base):
    __tablename__ = "computer_action_approvals"

    approval_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("computer_action_plans.plan_id", ondelete="CASCADE"), nullable=False, index=True)
    action_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    approval_status: Mapped[str] = mapped_column(String(40), nullable=False, default="等待审批", index=True)
    approval_scope: Mapped[str | None] = mapped_column(Text)
    before_screenshot_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    plan: Mapped[ComputerActionPlan] = relationship(back_populates="approvals")


class ComputerActionVerification(Base):
    __tablename__ = "computer_action_verifications"

    verification_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("computer_action_plans.plan_id", ondelete="CASCADE"), nullable=False, index=True)
    action_id: Mapped[str] = mapped_column(ForeignKey("computer_action_targets.action_id", ondelete="CASCADE"), nullable=False, index=True)
    verification_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    expected_window: Mapped[str | None] = mapped_column(String(255), index=True)
    expected_application: Mapped[str | None] = mapped_column(String(120), index=True)
    before_screenshot_reference: Mapped[str | None] = mapped_column(Text)
    after_screenshot_reference: Mapped[str | None] = mapped_column(Text)
    before_screenshot_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    after_screenshot_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    result_summary: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    plan: Mapped[ComputerActionPlan] = relationship(back_populates="verifications")

    __table_args__ = (UniqueConstraint("plan_id", "action_id", name="uq_computer_action_verifications_plan_action"),)
