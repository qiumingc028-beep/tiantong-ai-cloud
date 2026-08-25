"""V2 alpha migration history repair

Revision ID: 0041_v2_alpha_migration_history_repair
Revises: 0040_v2_alpha_workflow_integrity_constraints
Create Date: 2026-07-13 00:30:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "0041_v2_alpha_migration_history_repair"
down_revision = "0040_v2_alpha_workflow_integrity_constraints"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("alpha_workflow_events_run_id_fkey", "alpha_workflow_events", type_="foreignkey")
    op.create_foreign_key(
        "alpha_workflow_events_run_id_fkey",
        "alpha_workflow_events",
        "alpha_workflow_runs",
        ["run_id"],
        ["run_id"],
        ondelete="RESTRICT",
    )

    op.create_foreign_key(
        "alpha_workflow_runs_user_id_fkey",
        "alpha_workflow_runs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("alpha_workflow_runs_user_id_fkey", "alpha_workflow_runs", type_="foreignkey")
    op.drop_constraint("alpha_workflow_events_run_id_fkey", "alpha_workflow_events", type_="foreignkey")
    op.create_foreign_key(
        "alpha_workflow_events_run_id_fkey",
        "alpha_workflow_events",
        "alpha_workflow_runs",
        ["run_id"],
        ["run_id"],
        ondelete="CASCADE",
    )
