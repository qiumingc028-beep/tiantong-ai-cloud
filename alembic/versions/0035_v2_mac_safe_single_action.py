"""V2 Mac safe single action

Revision ID: 0035_v2_mac_safe_single_action
Revises: 0034_v2_device_center_readonly_observer
Create Date: 2026-07-12 15:40:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0035_v2_mac_safe_single_action"
down_revision = "0034_v2_device_center_readonly_observer"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "computer_action_plans",
        sa.Column("plan_id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("computer_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("observation_id", sa.String(length=36), sa.ForeignKey("device_observation_sessions.observation_id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_application", sa.String(length=120), nullable=True),
        sa.Column("target_bundle_id", sa.String(length=180), nullable=True),
        sa.Column("target_window", sa.String(length=255), nullable=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("proposed_actions_json", sa.Text(), nullable=False),
        sa.Column("current_action_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_actions", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("approval_mode", sa.String(length=40), nullable=False, server_default=sa.text("'逐步审批'")),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'草稿'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("session_id", "trace_id", name="uq_computer_action_plans_session_trace"),
    )
    for name, cols in [
        ("ix_computer_action_plans_session_id", ["session_id"]),
        ("ix_computer_action_plans_observation_id", ["observation_id"]),
        ("ix_computer_action_plans_task_id", ["task_id"]),
        ("ix_computer_action_plans_employee_id", ["employee_id"]),
        ("ix_computer_action_plans_skill_id", ["skill_id"]),
        ("ix_computer_action_plans_target_application", ["target_application"]),
        ("ix_computer_action_plans_target_bundle_id", ["target_bundle_id"]),
        ("ix_computer_action_plans_target_window", ["target_window"]),
        ("ix_computer_action_plans_risk_level", ["risk_level"]),
        ("ix_computer_action_plans_approval_mode", ["approval_mode"]),
        ("ix_computer_action_plans_status", ["status"]),
        ("ix_computer_action_plans_expires_at", ["expires_at"]),
        ("ix_computer_action_plans_trace_id", ["trace_id"]),
        ("ix_computer_action_plans_created_at", ["created_at"]),
        ("ix_computer_action_plans_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "computer_action_plans", cols)

    op.create_table(
        "computer_action_targets",
        sa.Column("target_id", sa.String(length=36), primary_key=True),
        sa.Column("plan_id", sa.String(length=36), sa.ForeignKey("computer_action_plans.plan_id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("control_type", sa.String(length=80), nullable=True),
        sa.Column("control_label", sa.String(length=255), nullable=True),
        sa.Column("control_identifier", sa.String(length=255), nullable=True),
        sa.Column("target_description", sa.Text(), nullable=True),
        sa.Column("expected_window", sa.String(length=255), nullable=True),
        sa.Column("expected_application", sa.String(length=120), nullable=True),
        sa.Column("coordinates_json", sa.Text(), nullable=True),
        sa.Column("input_text_summary", sa.Text(), nullable=True),
        sa.Column("screenshot_before_reference", sa.Text(), nullable=True),
        sa.Column("screenshot_before_hash", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'待校验'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_computer_action_targets_plan_action", "computer_action_targets", ["plan_id", "action_id"])
    op.create_unique_constraint("uq_computer_action_targets_action_id", "computer_action_targets", ["action_id"])
    for name, cols in [
        ("ix_computer_action_targets_plan_id", ["plan_id"]),
        ("ix_computer_action_targets_action_id", ["action_id"]),
        ("ix_computer_action_targets_action_type", ["action_type"]),
        ("ix_computer_action_targets_control_type", ["control_type"]),
        ("ix_computer_action_targets_control_label", ["control_label"]),
        ("ix_computer_action_targets_control_identifier", ["control_identifier"]),
        ("ix_computer_action_targets_expected_window", ["expected_window"]),
        ("ix_computer_action_targets_expected_application", ["expected_application"]),
        ("ix_computer_action_targets_screenshot_before_hash", ["screenshot_before_hash"]),
        ("ix_computer_action_targets_status", ["status"]),
        ("ix_computer_action_targets_created_at", ["created_at"]),
        ("ix_computer_action_targets_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "computer_action_targets", cols)

    op.create_table(
        "computer_action_approvals",
        sa.Column("approval_id", sa.String(length=36), primary_key=True),
        sa.Column("plan_id", sa.String(length=36), sa.ForeignKey("computer_action_plans.plan_id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", sa.String(length=36), nullable=False),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approval_status", sa.String(length=40), nullable=False, server_default=sa.text("'等待审批'")),
        sa.Column("approval_scope", sa.Text(), nullable=True),
        sa.Column("before_screenshot_hash", sa.String(length=128), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, cols in [
        ("ix_computer_action_approvals_plan_id", ["plan_id"]),
        ("ix_computer_action_approvals_action_id", ["action_id"]),
        ("ix_computer_action_approvals_approved_by", ["approved_by"]),
        ("ix_computer_action_approvals_approval_status", ["approval_status"]),
        ("ix_computer_action_approvals_before_screenshot_hash", ["before_screenshot_hash"]),
        ("ix_computer_action_approvals_approved_at", ["approved_at"]),
        ("ix_computer_action_approvals_expires_at", ["expires_at"]),
        ("ix_computer_action_approvals_trace_id", ["trace_id"]),
        ("ix_computer_action_approvals_created_at", ["created_at"]),
        ("ix_computer_action_approvals_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "computer_action_approvals", cols)

    op.create_table(
        "computer_action_verifications",
        sa.Column("verification_id", sa.String(length=36), primary_key=True),
        sa.Column("plan_id", sa.String(length=36), sa.ForeignKey("computer_action_plans.plan_id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", sa.String(length=36), sa.ForeignKey("computer_action_targets.action_id", ondelete="CASCADE"), nullable=False),
        sa.Column("verification_status", sa.String(length=40), nullable=False),
        sa.Column("expected_window", sa.String(length=255), nullable=True),
        sa.Column("expected_application", sa.String(length=120), nullable=True),
        sa.Column("before_screenshot_reference", sa.Text(), nullable=True),
        sa.Column("after_screenshot_reference", sa.Text(), nullable=True),
        sa.Column("before_screenshot_hash", sa.String(length=128), nullable=True),
        sa.Column("after_screenshot_hash", sa.String(length=128), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_computer_action_verifications_plan_action", "computer_action_verifications", ["plan_id", "action_id"])
    for name, cols in [
        ("ix_computer_action_verifications_plan_id", ["plan_id"]),
        ("ix_computer_action_verifications_action_id", ["action_id"]),
        ("ix_computer_action_verifications_verification_status", ["verification_status"]),
        ("ix_computer_action_verifications_expected_window", ["expected_window"]),
        ("ix_computer_action_verifications_expected_application", ["expected_application"]),
        ("ix_computer_action_verifications_before_screenshot_hash", ["before_screenshot_hash"]),
        ("ix_computer_action_verifications_after_screenshot_hash", ["after_screenshot_hash"]),
        ("ix_computer_action_verifications_trace_id", ["trace_id"]),
        ("ix_computer_action_verifications_created_at", ["created_at"]),
    ]:
        op.create_index(name, "computer_action_verifications", cols)


def downgrade():
    for table in [
        "computer_action_verifications",
        "computer_action_approvals",
        "computer_action_targets",
        "computer_action_plans",
    ]:
        op.drop_table(table)
