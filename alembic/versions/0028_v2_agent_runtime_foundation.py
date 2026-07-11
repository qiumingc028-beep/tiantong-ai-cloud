"""v2 agent runtime foundation

Revision ID: 0028_v2_agent_runtime_foundation
Revises: 0027_v1_schema_alignment
Create Date: 2026-07-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0028_v2_agent_runtime_foundation"
down_revision = "0027_v1_schema_alignment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_capabilities",
        sa.Column("capability_id", sa.String(length=120), primary_key=True),
        sa.Column("capability_name", sa.String(length=200), nullable=False),
        sa.Column("capability_type", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("executor_type", sa.String(length=50), nullable=False, server_default="mock"),
        sa.Column("risk_level", sa.String(length=40), nullable=False, server_default="low"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("readonly", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("requires_boss_approval", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("requires_security_audit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_schema_json", sa.Text(), nullable=True),
        sa.Column("output_schema_json", sa.Text(), nullable=True),
        sa.Column("allowed_employee_codes_json", sa.Text(), nullable=True),
        sa.Column("version", sa.String(length=40), nullable=False, server_default="1.0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_capabilities_capability_name", "agent_capabilities", ["capability_name"])
    op.create_index("ix_agent_capabilities_capability_type", "agent_capabilities", ["capability_type"])
    op.create_index("ix_agent_capabilities_executor_type", "agent_capabilities", ["executor_type"])
    op.create_index("ix_agent_capabilities_risk_level", "agent_capabilities", ["risk_level"])
    op.create_index("ix_agent_capabilities_enabled", "agent_capabilities", ["enabled"])
    op.create_index("ix_agent_capabilities_requires_boss_approval", "agent_capabilities", ["requires_boss_approval"])
    op.create_index("ix_agent_capabilities_requires_security_audit", "agent_capabilities", ["requires_security_audit"])
    op.create_index("ix_agent_capabilities_version", "agent_capabilities", ["version"])

    op.create_table(
        "agent_executions",
        sa.Column("execution_id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("capability_id", sa.String(length=120), sa.ForeignKey("agent_capabilities.capability_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending_validation"),
        sa.Column("risk_level", sa.String(length=40), nullable=False, server_default="low"),
        sa.Column("approval_status", sa.String(length=40), nullable=False, server_default="not_required"),
        sa.Column("executor_type", sa.String(length=40), nullable=False, server_default="mock"),
        sa.Column("input_payload", sa.Text(), nullable=True),
        sa.Column("output_payload", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("trace_id", name="uq_agent_executions_trace_id"),
    )
    op.create_index("ix_agent_executions_task_id", "agent_executions", ["task_id"])
    op.create_index("ix_agent_executions_employee_id", "agent_executions", ["employee_id"])
    op.create_index("ix_agent_executions_capability_id", "agent_executions", ["capability_id"])
    op.create_index("ix_agent_executions_status", "agent_executions", ["status"])
    op.create_index("ix_agent_executions_risk_level", "agent_executions", ["risk_level"])
    op.create_index("ix_agent_executions_approval_status", "agent_executions", ["approval_status"])
    op.create_index("ix_agent_executions_executor_type", "agent_executions", ["executor_type"])
    op.create_index("ix_agent_executions_trace_id", "agent_executions", ["trace_id"])
    op.create_index("ix_agent_executions_created_by_id", "agent_executions", ["created_by_id"])

    op.create_table(
        "agent_execution_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("execution_id", sa.String(length=36), sa.ForeignKey("agent_executions.execution_id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("actor_type", sa.String(length=40), nullable=False),
        sa.Column("actor_id", sa.String(length=120), nullable=True),
        sa.Column("approval_status", sa.String(length=40), nullable=True),
        sa.Column("approval_decision", sa.String(length=40), nullable=True),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("executor_name", sa.String(length=80), nullable=True),
        sa.Column("source_ip", sa.String(length=120), nullable=True),
        sa.Column("sensitive_data_involved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("trace_id", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_execution_audits_execution_id", "agent_execution_audits", ["execution_id"])
    op.create_index("ix_agent_execution_audits_event_type", "agent_execution_audits", ["event_type"])
    op.create_index("ix_agent_execution_audits_actor_type", "agent_execution_audits", ["actor_type"])
    op.create_index("ix_agent_execution_audits_approval_status", "agent_execution_audits", ["approval_status"])
    op.create_index("ix_agent_execution_audits_risk_level", "agent_execution_audits", ["risk_level"])
    op.create_index("ix_agent_execution_audits_sensitive_data_involved", "agent_execution_audits", ["sensitive_data_involved"])
    op.create_index("ix_agent_execution_audits_trace_id", "agent_execution_audits", ["trace_id"])


def downgrade():
    op.drop_index("ix_agent_execution_audits_trace_id", table_name="agent_execution_audits")
    op.drop_index("ix_agent_execution_audits_sensitive_data_involved", table_name="agent_execution_audits")
    op.drop_index("ix_agent_execution_audits_risk_level", table_name="agent_execution_audits")
    op.drop_index("ix_agent_execution_audits_approval_status", table_name="agent_execution_audits")
    op.drop_index("ix_agent_execution_audits_actor_type", table_name="agent_execution_audits")
    op.drop_index("ix_agent_execution_audits_event_type", table_name="agent_execution_audits")
    op.drop_index("ix_agent_execution_audits_execution_id", table_name="agent_execution_audits")
    op.drop_table("agent_execution_audits")

    op.drop_index("ix_agent_executions_created_by_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_trace_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_executor_type", table_name="agent_executions")
    op.drop_index("ix_agent_executions_approval_status", table_name="agent_executions")
    op.drop_index("ix_agent_executions_risk_level", table_name="agent_executions")
    op.drop_index("ix_agent_executions_status", table_name="agent_executions")
    op.drop_index("ix_agent_executions_capability_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_employee_id", table_name="agent_executions")
    op.drop_index("ix_agent_executions_task_id", table_name="agent_executions")
    op.drop_table("agent_executions")

    op.drop_index("ix_agent_capabilities_version", table_name="agent_capabilities")
    op.drop_index("ix_agent_capabilities_requires_security_audit", table_name="agent_capabilities")
    op.drop_index("ix_agent_capabilities_requires_boss_approval", table_name="agent_capabilities")
    op.drop_index("ix_agent_capabilities_enabled", table_name="agent_capabilities")
    op.drop_index("ix_agent_capabilities_risk_level", table_name="agent_capabilities")
    op.drop_index("ix_agent_capabilities_executor_type", table_name="agent_capabilities")
    op.drop_index("ix_agent_capabilities_capability_type", table_name="agent_capabilities")
    op.drop_index("ix_agent_capabilities_capability_name", table_name="agent_capabilities")
    op.drop_table("agent_capabilities")

