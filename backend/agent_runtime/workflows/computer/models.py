from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ....database import Base


class ComputerWorkflow(Base):
    __tablename__ = "computer_workflows"

    workflow_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("ai_employees.id", ondelete="SET NULL"), index=True)
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"), index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.device_id", ondelete="SET NULL"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), index=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="草稿", index=True)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, default="低风险", index=True)
    approval_status: Mapped[str] = mapped_column(String(40), nullable=False, default="等待审批", index=True)
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    max_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    checkpoint_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    execution_budget_json: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    stop_reason: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    steps: Mapped[list["ComputerWorkflowStep"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")
    approvals: Mapped[list["ComputerWorkflowApproval"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")
    checkpoints: Mapped[list["ComputerWorkflowCheckpoint"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")
    verifications: Mapped[list["ComputerWorkflowVerification"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")
    recoveries: Mapped[list["ComputerWorkflowRecovery"]] = relationship(back_populates="workflow", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("task_id", "trace_id", name="uq_computer_workflows_task_trace"),)


class ComputerWorkflowStep(Base):
    __tablename__ = "computer_workflow_steps"

    step_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("computer_workflows.workflow_id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    target_application: Mapped[str | None] = mapped_column(String(120), index=True)
    target_bundle_id: Mapped[str | None] = mapped_column(String(180), index=True)
    target_window: Mapped[str | None] = mapped_column(String(255), index=True)
    target_control: Mapped[str | None] = mapped_column(String(255), index=True)
    input_summary: Mapped[str | None] = mapped_column(Text)
    expected_result: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, default="低风险", index=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    checkpoint_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="待执行", index=True)
    action_id: Mapped[str | None] = mapped_column(String(36), index=True)
    verification_id: Mapped[str | None] = mapped_column(String(36), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    error_code: Mapped[str | None] = mapped_column(String(80), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)

    workflow: Mapped[ComputerWorkflow] = relationship(back_populates="steps")

    __table_args__ = (UniqueConstraint("workflow_id", "sequence_number", name="uq_computer_workflow_steps_sequence"),)


class ComputerWorkflowApproval(Base):
    __tablename__ = "computer_workflow_approvals"

    approval_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("computer_workflows.workflow_id", ondelete="CASCADE"), nullable=False, index=True)
    approval_scope: Mapped[str | None] = mapped_column(Text)
    approval_status: Mapped[str] = mapped_column(String(40), nullable=False, default="等待审批", index=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    workflow: Mapped[ComputerWorkflow] = relationship(back_populates="approvals")


class ComputerWorkflowCheckpoint(Base):
    __tablename__ = "computer_workflow_checkpoints"

    checkpoint_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("computer_workflows.workflow_id", ondelete="CASCADE"), nullable=False, index=True)
    step_id: Mapped[str | None] = mapped_column(ForeignKey("computer_workflow_steps.step_id", ondelete="SET NULL"), index=True)
    checkpoint_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    screenshot_reference: Mapped[str | None] = mapped_column(Text)
    state_summary: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, default="低风险", index=True)
    approval_status: Mapped[str] = mapped_column(String(40), nullable=False, default="等待审批", index=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    workflow: Mapped[ComputerWorkflow] = relationship(back_populates="checkpoints")


class ComputerWorkflowVerification(Base):
    __tablename__ = "computer_workflow_verifications"

    verification_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("computer_workflows.workflow_id", ondelete="CASCADE"), nullable=False, index=True)
    step_id: Mapped[str] = mapped_column(ForeignKey("computer_workflow_steps.step_id", ondelete="CASCADE"), nullable=False, index=True)
    verification_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    before_screenshot_reference: Mapped[str | None] = mapped_column(Text)
    after_screenshot_reference: Mapped[str | None] = mapped_column(Text)
    state_summary: Mapped[str | None] = mapped_column(Text)
    result_summary: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    workflow: Mapped[ComputerWorkflow] = relationship(back_populates="verifications")

    __table_args__ = (UniqueConstraint("workflow_id", "step_id", name="uq_computer_workflow_verifications_workflow_step"),)


class ComputerWorkflowRecovery(Base):
    __tablename__ = "computer_workflow_recoveries"

    recovery_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("computer_workflows.workflow_id", ondelete="CASCADE"), nullable=False, index=True)
    step_id: Mapped[str | None] = mapped_column(ForeignKey("computer_workflow_steps.step_id", ondelete="SET NULL"), index=True)
    recovery_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="已完成", index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    result_summary: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    workflow: Mapped[ComputerWorkflow] = relationship(back_populates="recoveries")
