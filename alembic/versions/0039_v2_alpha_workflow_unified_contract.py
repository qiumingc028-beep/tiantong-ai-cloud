"""V2 alpha workflow unified contract

Revision ID: 0039_v2_alpha_workflow_unified_contract
Revises: 0038_v2_alpha_workflow_engine
Create Date: 2026-07-12 23:15:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0039_v2_alpha_workflow_unified_contract"
down_revision = "0038_v2_alpha_workflow_engine"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("alpha_workflow_runs") as batch_op:
        batch_op.add_column(sa.Column("workflow_id", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("tenant_id", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("orchestrator_run_id", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("research_report_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("knowledge_asset_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("knowledge_version_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("skill_id", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("skill_version_id", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("agent_execution_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("verification_id", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("root_span_id", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("approval_ids_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("current_stage", sa.String(length=80), nullable=True))

    for name, cols in [
        ("ix_alpha_workflow_runs_workflow_id", ["workflow_id"]),
        ("ix_alpha_workflow_runs_tenant_id", ["tenant_id"]),
        ("ix_alpha_workflow_runs_user_id", ["user_id"]),
        ("ix_alpha_workflow_runs_orchestrator_run_id", ["orchestrator_run_id"]),
        ("ix_alpha_workflow_runs_research_report_id", ["research_report_id"]),
        ("ix_alpha_workflow_runs_knowledge_asset_id", ["knowledge_asset_id"]),
        ("ix_alpha_workflow_runs_knowledge_version_id", ["knowledge_version_id"]),
        ("ix_alpha_workflow_runs_skill_id", ["skill_id"]),
        ("ix_alpha_workflow_runs_skill_version_id", ["skill_version_id"]),
        ("ix_alpha_workflow_runs_agent_execution_id", ["agent_execution_id"]),
        ("ix_alpha_workflow_runs_verification_id", ["verification_id"]),
        ("ix_alpha_workflow_runs_root_span_id", ["root_span_id"]),
        ("ix_alpha_workflow_runs_current_stage", ["current_stage"]),
    ]:
        op.create_index(name, "alpha_workflow_runs", cols)

    with op.batch_alter_table("alpha_workflow_events") as batch_op:
        batch_op.add_column(sa.Column("span_id", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("parent_span_id", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("span_kind", sa.String(length=40), nullable=False, server_default=sa.text("'child'")))

    for name, cols in [
        ("ix_alpha_workflow_events_span_id", ["span_id"]),
        ("ix_alpha_workflow_events_parent_span_id", ["parent_span_id"]),
        ("ix_alpha_workflow_events_span_kind", ["span_kind"]),
    ]:
        op.create_index(name, "alpha_workflow_events", cols)


def downgrade():
    for name in [
        "ix_alpha_workflow_events_span_kind",
        "ix_alpha_workflow_events_parent_span_id",
        "ix_alpha_workflow_events_span_id",
    ]:
        op.drop_index(name, table_name="alpha_workflow_events")

    with op.batch_alter_table("alpha_workflow_events") as batch_op:
        batch_op.drop_column("span_kind")
        batch_op.drop_column("parent_span_id")
        batch_op.drop_column("span_id")

    for name in [
        "ix_alpha_workflow_runs_current_stage",
        "ix_alpha_workflow_runs_root_span_id",
        "ix_alpha_workflow_runs_verification_id",
        "ix_alpha_workflow_runs_agent_execution_id",
        "ix_alpha_workflow_runs_skill_version_id",
        "ix_alpha_workflow_runs_skill_id",
        "ix_alpha_workflow_runs_knowledge_version_id",
        "ix_alpha_workflow_runs_knowledge_asset_id",
        "ix_alpha_workflow_runs_research_report_id",
        "ix_alpha_workflow_runs_orchestrator_run_id",
        "ix_alpha_workflow_runs_user_id",
        "ix_alpha_workflow_runs_tenant_id",
        "ix_alpha_workflow_runs_workflow_id",
    ]:
        op.drop_index(name, table_name="alpha_workflow_runs")

    with op.batch_alter_table("alpha_workflow_runs") as batch_op:
        for column in [
            "current_stage",
            "approval_ids_json",
            "root_span_id",
            "verification_id",
            "agent_execution_id",
            "skill_version_id",
            "skill_id",
            "knowledge_version_id",
            "knowledge_asset_id",
            "research_report_id",
            "orchestrator_run_id",
            "user_id",
            "tenant_id",
            "workflow_id",
        ]:
            batch_op.drop_column(column)
