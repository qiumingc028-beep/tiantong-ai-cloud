"""V2 alpha workflow integrity constraints

Revision ID: 0040_v2_alpha_workflow_integrity_constraints
Revises: 0039_v2_alpha_workflow_unified_contract
Create Date: 2026-07-12 23:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0040_v2_alpha_workflow_integrity_constraints"
down_revision = "0039_v2_alpha_workflow_unified_contract"
branch_labels = None
depends_on = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade():
    for name, table, cols in [
        ("uq_alpha_workflow_runs_root_span_id", "alpha_workflow_runs", ["root_span_id"]),
        ("uq_alpha_workflow_runs_workflow_id", "alpha_workflow_runs", ["workflow_id"]),
        ("uq_alpha_workflow_runs_orchestrator_run_id", "alpha_workflow_runs", ["orchestrator_run_id"]),
        ("uq_alpha_workflow_runs_research_report_id", "alpha_workflow_runs", ["research_report_id"]),
        ("uq_alpha_workflow_runs_knowledge_asset_id", "alpha_workflow_runs", ["knowledge_asset_id"]),
        ("uq_alpha_workflow_runs_skill_invocation_id", "alpha_workflow_runs", ["skill_invocation_id"]),
    ]:
        op.create_index(name, table, cols, unique=True)

    if _is_sqlite():
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS alpha_workflow_events_no_update
            BEFORE UPDATE ON alpha_workflow_events
            BEGIN
                SELECT RAISE(ABORT, 'alpha_workflow_events is append-only');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS alpha_workflow_events_no_delete
            BEFORE DELETE ON alpha_workflow_events
            BEGIN
                SELECT RAISE(ABORT, 'alpha_workflow_events is append-only');
            END;
            """
        )
    else:
        op.execute(
            """
            CREATE OR REPLACE FUNCTION alpha_workflow_events_append_only()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'alpha_workflow_events is append-only';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute("DROP TRIGGER IF EXISTS alpha_workflow_events_no_update ON alpha_workflow_events;")
        op.execute(
            """
            CREATE TRIGGER alpha_workflow_events_no_update
            BEFORE UPDATE ON alpha_workflow_events
            FOR EACH ROW EXECUTE FUNCTION alpha_workflow_events_append_only();
            """
        )
        op.execute("DROP TRIGGER IF EXISTS alpha_workflow_events_no_delete ON alpha_workflow_events;")
        op.execute(
            """
            CREATE TRIGGER alpha_workflow_events_no_delete
            BEFORE DELETE ON alpha_workflow_events
            FOR EACH ROW EXECUTE FUNCTION alpha_workflow_events_append_only();
            """
        )


def downgrade():
    if _is_sqlite():
        op.execute("DROP TRIGGER IF EXISTS alpha_workflow_events_no_delete;")
        op.execute("DROP TRIGGER IF EXISTS alpha_workflow_events_no_update;")
    else:
        op.execute("DROP TRIGGER IF EXISTS alpha_workflow_events_no_delete ON alpha_workflow_events;")
        op.execute("DROP TRIGGER IF EXISTS alpha_workflow_events_no_update ON alpha_workflow_events;")

    for name, table in [
        ("uq_alpha_workflow_runs_skill_invocation_id", "alpha_workflow_runs"),
        ("uq_alpha_workflow_runs_knowledge_asset_id", "alpha_workflow_runs"),
        ("uq_alpha_workflow_runs_research_report_id", "alpha_workflow_runs"),
        ("uq_alpha_workflow_runs_orchestrator_run_id", "alpha_workflow_runs"),
        ("uq_alpha_workflow_runs_workflow_id", "alpha_workflow_runs"),
        ("uq_alpha_workflow_runs_root_span_id", "alpha_workflow_runs"),
    ]:
        op.drop_index(name, table_name=table)
