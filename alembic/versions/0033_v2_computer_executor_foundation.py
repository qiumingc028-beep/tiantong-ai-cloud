"""V2 computer executor foundation

Revision ID: 0033_v2_computer_executor_foundation
Revises: 0032_v2_skills_engine_foundation
Create Date: 2026-07-12 14:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0033_v2_computer_executor_foundation"
down_revision = "0032_v2_skills_engine_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "computer_sessions",
        sa.Column("session_id", sa.String(length=36), primary_key=True),
        sa.Column("execution_id", sa.Integer(), sa.ForeignKey("skill_invocations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("executor_type", sa.String(length=40), nullable=False, server_default=sa.text("'mock'")),
        sa.Column("environment_type", sa.String(length=40), nullable=False, server_default=sa.text("'test'")),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'待创建'")),
        sa.Column("risk_level", sa.String(length=40), nullable=False, server_default=sa.text("'低风险'")),
        sa.Column("approval_status", sa.String(length=40), nullable=False, server_default=sa.text("'无需审批'")),
        sa.Column("allowed_applications_json", sa.Text(), nullable=True),
        sa.Column("allowed_windows_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("takeover_status", sa.String(length=40), nullable=False, server_default=sa.text("'未接管'")),
        sa.Column("last_screenshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, cols in [
        ("ix_computer_sessions_execution_id", ["execution_id"]),
        ("ix_computer_sessions_task_id", ["task_id"]),
        ("ix_computer_sessions_employee_id", ["employee_id"]),
        ("ix_computer_sessions_skill_id", ["skill_id"]),
        ("ix_computer_sessions_executor_type", ["executor_type"]),
        ("ix_computer_sessions_environment_type", ["environment_type"]),
        ("ix_computer_sessions_status", ["status"]),
        ("ix_computer_sessions_risk_level", ["risk_level"]),
        ("ix_computer_sessions_approval_status", ["approval_status"]),
        ("ix_computer_sessions_takeover_status", ["takeover_status"]),
        ("ix_computer_sessions_trace_id", ["trace_id"]),
        ("ix_computer_sessions_created_at", ["created_at"]),
        ("ix_computer_sessions_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "computer_sessions", cols)

    op.create_table(
        "computer_actions",
        sa.Column("action_id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("computer_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("target_application", sa.String(length=120), nullable=True),
        sa.Column("target_window", sa.String(length=255), nullable=True),
        sa.Column("target_description", sa.Text(), nullable=True),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("coordinates_json", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("approval_status", sa.String(length=40), nullable=False, server_default=sa.text("'无需审批'")),
        sa.Column("screenshot_before", sa.Text(), nullable=True),
        sa.Column("screenshot_after", sa.Text(), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.UniqueConstraint("session_id", "sequence_number", name="uq_computer_actions_sequence"),
    )
    for name, cols in [
        ("ix_computer_actions_session_id", ["session_id"]),
        ("ix_computer_actions_sequence_number", ["sequence_number"]),
        ("ix_computer_actions_action_type", ["action_type"]),
        ("ix_computer_actions_target_application", ["target_application"]),
        ("ix_computer_actions_target_window", ["target_window"]),
        ("ix_computer_actions_risk_level", ["risk_level"]),
        ("ix_computer_actions_approval_required", ["approval_required"]),
        ("ix_computer_actions_approval_status", ["approval_status"]),
        ("ix_computer_actions_error_code", ["error_code"]),
        ("ix_computer_actions_trace_id", ["trace_id"]),
    ]:
        op.create_index(name, "computer_actions", cols)

    op.create_table(
        "computer_evidence",
        sa.Column("evidence_id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("computer_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", sa.String(length=36), sa.ForeignKey("computer_actions.action_id", ondelete="SET NULL"), nullable=True),
        sa.Column("evidence_type", sa.String(length=40), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, cols in [
        ("ix_computer_evidence_session_id", ["session_id"]),
        ("ix_computer_evidence_action_id", ["action_id"]),
        ("ix_computer_evidence_evidence_type", ["evidence_type"]),
        ("ix_computer_evidence_created_at", ["created_at"]),
    ]:
        op.create_index(name, "computer_evidence", cols)

    op.create_table(
        "computer_takeovers",
        sa.Column("takeover_id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("computer_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by", sa.String(length=80), nullable=True),
        sa.Column("requested_reason", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.String(length=80), nullable=True),
        sa.Column("approval_status", sa.String(length=40), nullable=False, server_default=sa.text("'等待审批'")),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'等待接管'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, cols in [
        ("ix_computer_takeovers_session_id", ["session_id"]),
        ("ix_computer_takeovers_requested_by", ["requested_by"]),
        ("ix_computer_takeovers_approved_by", ["approved_by"]),
        ("ix_computer_takeovers_approval_status", ["approval_status"]),
        ("ix_computer_takeovers_status", ["status"]),
        ("ix_computer_takeovers_created_at", ["created_at"]),
        ("ix_computer_takeovers_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "computer_takeovers", cols)

    op.create_table(
        "computer_policy_events",
        sa.Column("event_id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), nullable=True),
        sa.Column("action_id", sa.String(length=36), sa.ForeignKey("computer_actions.action_id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_code", sa.String(length=80), nullable=False),
        sa.Column("event_message", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("sensitive_data_involved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, cols in [
        ("ix_computer_policy_events_session_id", ["session_id"]),
        ("ix_computer_policy_events_action_id", ["action_id"]),
        ("ix_computer_policy_events_event_code", ["event_code"]),
        ("ix_computer_policy_events_risk_level", ["risk_level"]),
        ("ix_computer_policy_events_sensitive_data_involved", ["sensitive_data_involved"]),
        ("ix_computer_policy_events_trace_id", ["trace_id"]),
        ("ix_computer_policy_events_created_at", ["created_at"]),
    ]:
        op.create_index(name, "computer_policy_events", cols)


def downgrade():
    for table in [
        "computer_policy_events",
        "computer_takeovers",
        "computer_evidence",
        "computer_actions",
        "computer_sessions",
    ]:
        op.drop_table(table)
