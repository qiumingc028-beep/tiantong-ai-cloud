"""V2 alpha workflow engine

Revision ID: 0038_v2_alpha_workflow_engine
Revises: 0037_v2_execution_observability_security_ops
Create Date: 2026-07-12 22:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0038_v2_alpha_workflow_engine"
down_revision = "0037_v2_execution_observability_security_ops"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "alpha_workflow_scenarios",
        sa.Column("scenario_id", sa.String(length=36), primary_key=True),
        sa.Column("scenario_code", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("input_hint", sa.String(length=200), nullable=True),
        sa.Column("default_input_text", sa.Text(), nullable=True),
        sa.Column("workflow_template_json", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("scenario_code", name="uq_alpha_workflow_scenarios_code"),
    )
    for name, cols in [
        ("ix_alpha_workflow_scenarios_scenario_code", ["scenario_code"]),
        ("ix_alpha_workflow_scenarios_enabled", ["enabled"]),
        ("ix_alpha_workflow_scenarios_created_by_id", ["created_by_id"]),
        ("ix_alpha_workflow_scenarios_created_at", ["created_at"]),
        ("ix_alpha_workflow_scenarios_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "alpha_workflow_scenarios", cols)

    op.create_table(
        "alpha_workflow_runs",
        sa.Column("run_id", sa.String(length=36), primary_key=True),
        sa.Column("scenario_id", sa.String(length=36), sa.ForeignKey("alpha_workflow_scenarios.scenario_id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("research_execution_id", sa.String(length=36), nullable=True),
        sa.Column("knowledge_id", sa.String(length=36), nullable=True),
        sa.Column("skill_invocation_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'草稿'")),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("quality_grade", sa.String(length=20), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=True),
        sa.Column("risk_level", sa.String(length=20), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("recovery_status", sa.String(length=40), nullable=True),
        sa.Column("workflow_context_json", sa.Text(), nullable=True),
        sa.Column("plan_json", sa.Text(), nullable=True),
        sa.Column("report_summary_json", sa.Text(), nullable=True),
        sa.Column("dashboard_summary_json", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recovered_from_run_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("trace_id", name="uq_alpha_workflow_runs_trace_id"),
    )
    for name, cols in [
        ("ix_alpha_workflow_runs_scenario_id", ["scenario_id"]),
        ("ix_alpha_workflow_runs_task_id", ["task_id"]),
        ("ix_alpha_workflow_runs_research_execution_id", ["research_execution_id"]),
        ("ix_alpha_workflow_runs_knowledge_id", ["knowledge_id"]),
        ("ix_alpha_workflow_runs_skill_invocation_id", ["skill_invocation_id"]),
        ("ix_alpha_workflow_runs_status", ["status"]),
        ("ix_alpha_workflow_runs_quality_score", ["quality_score"]),
        ("ix_alpha_workflow_runs_quality_grade", ["quality_grade"]),
        ("ix_alpha_workflow_runs_risk_score", ["risk_score"]),
        ("ix_alpha_workflow_runs_risk_level", ["risk_level"]),
        ("ix_alpha_workflow_runs_recovery_status", ["recovery_status"]),
        ("ix_alpha_workflow_runs_trace_id", ["trace_id"]),
        ("ix_alpha_workflow_runs_started_at", ["started_at"]),
        ("ix_alpha_workflow_runs_finished_at", ["finished_at"]),
        ("ix_alpha_workflow_runs_created_by_id", ["created_by_id"]),
        ("ix_alpha_workflow_runs_recovered_from_run_id", ["recovered_from_run_id"]),
        ("ix_alpha_workflow_runs_created_at", ["created_at"]),
        ("ix_alpha_workflow_runs_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "alpha_workflow_runs", cols)

    op.create_table(
        "alpha_workflow_events",
        sa.Column("event_id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("alpha_workflow_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_code", sa.String(length=80), nullable=False),
        sa.Column("stage", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("event_id", name="uq_alpha_workflow_events_id"),
    )
    for name, cols in [
        ("ix_alpha_workflow_events_run_id", ["run_id"]),
        ("ix_alpha_workflow_events_event_code", ["event_code"]),
        ("ix_alpha_workflow_events_stage", ["stage"]),
        ("ix_alpha_workflow_events_status", ["status"]),
        ("ix_alpha_workflow_events_trace_id", ["trace_id"]),
        ("ix_alpha_workflow_events_created_at", ["created_at"]),
    ]:
        op.create_index(name, "alpha_workflow_events", cols)


def downgrade():
    for name in [
        "ix_alpha_workflow_events_created_at",
        "ix_alpha_workflow_events_trace_id",
        "ix_alpha_workflow_events_status",
        "ix_alpha_workflow_events_stage",
        "ix_alpha_workflow_events_event_code",
        "ix_alpha_workflow_events_run_id",
    ]:
        op.drop_index(name, table_name="alpha_workflow_events")
    op.drop_table("alpha_workflow_events")

    for name in [
        "ix_alpha_workflow_runs_updated_at",
        "ix_alpha_workflow_runs_created_at",
        "ix_alpha_workflow_runs_recovered_from_run_id",
        "ix_alpha_workflow_runs_created_by_id",
        "ix_alpha_workflow_runs_finished_at",
        "ix_alpha_workflow_runs_started_at",
        "ix_alpha_workflow_runs_trace_id",
        "ix_alpha_workflow_runs_risk_level",
        "ix_alpha_workflow_runs_risk_score",
        "ix_alpha_workflow_runs_quality_grade",
        "ix_alpha_workflow_runs_quality_score",
        "ix_alpha_workflow_runs_status",
        "ix_alpha_workflow_runs_skill_invocation_id",
        "ix_alpha_workflow_runs_knowledge_id",
        "ix_alpha_workflow_runs_research_execution_id",
        "ix_alpha_workflow_runs_task_id",
        "ix_alpha_workflow_runs_scenario_id",
    ]:
        op.drop_index(name, table_name="alpha_workflow_runs")
    op.drop_table("alpha_workflow_runs")

    for name in [
        "ix_alpha_workflow_scenarios_updated_at",
        "ix_alpha_workflow_scenarios_created_at",
        "ix_alpha_workflow_scenarios_created_by_id",
        "ix_alpha_workflow_scenarios_enabled",
        "ix_alpha_workflow_scenarios_scenario_code",
    ]:
        op.drop_index(name, table_name="alpha_workflow_scenarios")
    op.drop_table("alpha_workflow_scenarios")
