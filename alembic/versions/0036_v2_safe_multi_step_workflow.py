"""V2 safe multi-step computer workflow

Revision ID: 0036_v2_safe_multi_step_workflow
Revises: 0035_v2_mac_safe_single_action
Create Date: 2026-07-12 18:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0036_v2_safe_multi_step_workflow"
down_revision = "0035_v2_mac_safe_single_action"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "computer_workflows",
        sa.Column("workflow_id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("device_id", sa.String(length=36), sa.ForeignKey("devices.device_id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), nullable=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'草稿'")),
        sa.Column("risk_level", sa.String(length=40), nullable=False, server_default=sa.text("'低风险'")),
        sa.Column("approval_status", sa.String(length=40), nullable=False, server_default=sa.text("'等待审批'")),
        sa.Column("total_steps", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("current_step", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_steps", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("checkpoint_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("execution_budget_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("task_id", "trace_id", name="uq_computer_workflows_task_trace"),
    )
    for name, cols in [
        ("ix_computer_workflows_task_id", ["task_id"]),
        ("ix_computer_workflows_employee_id", ["employee_id"]),
        ("ix_computer_workflows_skill_id", ["skill_id"]),
        ("ix_computer_workflows_device_id", ["device_id"]),
        ("ix_computer_workflows_session_id", ["session_id"]),
        ("ix_computer_workflows_status", ["status"]),
        ("ix_computer_workflows_risk_level", ["risk_level"]),
        ("ix_computer_workflows_approval_status", ["approval_status"]),
        ("ix_computer_workflows_current_step", ["current_step"]),
        ("ix_computer_workflows_started_at", ["started_at"]),
        ("ix_computer_workflows_expires_at", ["expires_at"]),
        ("ix_computer_workflows_finished_at", ["finished_at"]),
        ("ix_computer_workflows_trace_id", ["trace_id"]),
        ("ix_computer_workflows_created_at", ["created_at"]),
        ("ix_computer_workflows_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "computer_workflows", cols)

    op.create_table(
        "computer_workflow_steps",
        sa.Column("step_id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("computer_workflows.workflow_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("target_application", sa.String(length=120), nullable=True),
        sa.Column("target_bundle_id", sa.String(length=180), nullable=True),
        sa.Column("target_window", sa.String(length=255), nullable=True),
        sa.Column("target_control", sa.String(length=255), nullable=True),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("expected_result", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=40), nullable=False, server_default=sa.text("'低风险'")),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("checkpoint_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'待执行'")),
        sa.Column("action_id", sa.String(length=36), nullable=True),
        sa.Column("verification_id", sa.String(length=36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.UniqueConstraint("workflow_id", "sequence_number", name="uq_computer_workflow_steps_sequence"),
    )
    for name, cols in [
        ("ix_computer_workflow_steps_workflow_id", ["workflow_id"]),
        ("ix_computer_workflow_steps_sequence_number", ["sequence_number"]),
        ("ix_computer_workflow_steps_action_type", ["action_type"]),
        ("ix_computer_workflow_steps_target_application", ["target_application"]),
        ("ix_computer_workflow_steps_target_bundle_id", ["target_bundle_id"]),
        ("ix_computer_workflow_steps_target_window", ["target_window"]),
        ("ix_computer_workflow_steps_target_control", ["target_control"]),
        ("ix_computer_workflow_steps_risk_level", ["risk_level"]),
        ("ix_computer_workflow_steps_approval_required", ["approval_required"]),
        ("ix_computer_workflow_steps_checkpoint_required", ["checkpoint_required"]),
        ("ix_computer_workflow_steps_status", ["status"]),
        ("ix_computer_workflow_steps_action_id", ["action_id"]),
        ("ix_computer_workflow_steps_verification_id", ["verification_id"]),
        ("ix_computer_workflow_steps_started_at", ["started_at"]),
        ("ix_computer_workflow_steps_finished_at", ["finished_at"]),
        ("ix_computer_workflow_steps_error_code", ["error_code"]),
        ("ix_computer_workflow_steps_trace_id", ["trace_id"]),
    ]:
        op.create_index(name, "computer_workflow_steps", cols)

    op.create_table(
        "computer_workflow_approvals",
        sa.Column("approval_id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("computer_workflows.workflow_id", ondelete="CASCADE"), nullable=False),
        sa.Column("approval_scope", sa.Text(), nullable=True),
        sa.Column("approval_status", sa.String(length=40), nullable=False, server_default=sa.text("'等待审批'")),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, cols in [
        ("ix_computer_workflow_approvals_workflow_id", ["workflow_id"]),
        ("ix_computer_workflow_approvals_approval_status", ["approval_status"]),
        ("ix_computer_workflow_approvals_approved_by", ["approved_by"]),
        ("ix_computer_workflow_approvals_approved_at", ["approved_at"]),
        ("ix_computer_workflow_approvals_expires_at", ["expires_at"]),
        ("ix_computer_workflow_approvals_trace_id", ["trace_id"]),
        ("ix_computer_workflow_approvals_created_at", ["created_at"]),
        ("ix_computer_workflow_approvals_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "computer_workflow_approvals", cols)

    op.create_table(
        "computer_workflow_checkpoints",
        sa.Column("checkpoint_id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("computer_workflows.workflow_id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", sa.String(length=36), sa.ForeignKey("computer_workflow_steps.step_id", ondelete="SET NULL"), nullable=True),
        sa.Column("checkpoint_type", sa.String(length=60), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("screenshot_reference", sa.Text(), nullable=True),
        sa.Column("state_summary", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=40), nullable=False, server_default=sa.text("'低风险'")),
        sa.Column("approval_status", sa.String(length=40), nullable=False, server_default=sa.text("'等待审批'")),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, cols in [
        ("ix_computer_workflow_checkpoints_workflow_id", ["workflow_id"]),
        ("ix_computer_workflow_checkpoints_step_id", ["step_id"]),
        ("ix_computer_workflow_checkpoints_checkpoint_type", ["checkpoint_type"]),
        ("ix_computer_workflow_checkpoints_risk_level", ["risk_level"]),
        ("ix_computer_workflow_checkpoints_approval_status", ["approval_status"]),
        ("ix_computer_workflow_checkpoints_approved_by", ["approved_by"]),
        ("ix_computer_workflow_checkpoints_approved_at", ["approved_at"]),
        ("ix_computer_workflow_checkpoints_expires_at", ["expires_at"]),
        ("ix_computer_workflow_checkpoints_trace_id", ["trace_id"]),
        ("ix_computer_workflow_checkpoints_created_at", ["created_at"]),
    ]:
        op.create_index(name, "computer_workflow_checkpoints", cols)

    op.create_table(
        "computer_workflow_verifications",
        sa.Column("verification_id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("computer_workflows.workflow_id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", sa.String(length=36), sa.ForeignKey("computer_workflow_steps.step_id", ondelete="CASCADE"), nullable=False),
        sa.Column("verification_status", sa.String(length=40), nullable=False),
        sa.Column("before_screenshot_reference", sa.Text(), nullable=True),
        sa.Column("after_screenshot_reference", sa.Text(), nullable=True),
        sa.Column("state_summary", sa.Text(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("workflow_id", "step_id", name="uq_computer_workflow_verifications_workflow_step"),
    )
    for name, cols in [
        ("ix_computer_workflow_verifications_workflow_id", ["workflow_id"]),
        ("ix_computer_workflow_verifications_step_id", ["step_id"]),
        ("ix_computer_workflow_verifications_verification_status", ["verification_status"]),
        ("ix_computer_workflow_verifications_trace_id", ["trace_id"]),
        ("ix_computer_workflow_verifications_created_at", ["created_at"]),
    ]:
        op.create_index(name, "computer_workflow_verifications", cols)

    op.create_table(
        "computer_workflow_recoveries",
        sa.Column("recovery_id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("computer_workflows.workflow_id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", sa.String(length=36), sa.ForeignKey("computer_workflow_steps.step_id", ondelete="SET NULL"), nullable=True),
        sa.Column("recovery_type", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'已完成'")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    for name, cols in [
        ("ix_computer_workflow_recoveries_workflow_id", ["workflow_id"]),
        ("ix_computer_workflow_recoveries_step_id", ["step_id"]),
        ("ix_computer_workflow_recoveries_recovery_type", ["recovery_type"]),
        ("ix_computer_workflow_recoveries_status", ["status"]),
        ("ix_computer_workflow_recoveries_trace_id", ["trace_id"]),
        ("ix_computer_workflow_recoveries_created_at", ["created_at"]),
        ("ix_computer_workflow_recoveries_finished_at", ["finished_at"]),
    ]:
        op.create_index(name, "computer_workflow_recoveries", cols)


def downgrade():
    for table in [
        "computer_workflow_recoveries",
        "computer_workflow_verifications",
        "computer_workflow_checkpoints",
        "computer_workflow_approvals",
        "computer_workflow_steps",
        "computer_workflows",
    ]:
        op.drop_table(table)
