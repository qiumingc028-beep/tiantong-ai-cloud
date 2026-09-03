"""Add durable R297 sync-task lease metadata.

Revision ID: 0050_r297_reliable_sync_queue
Revises: 0049_r297_jd_multistore_autosync
Create Date: 2026-09-02
"""

from alembic import op
import sqlalchemy as sa


revision = "0050_r297_reliable_sync_queue"
down_revision = "0049_r297_jd_multistore_autosync"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jd_workbench_sync_policies", sa.Column("active_task_id", sa.String(36)))
    op.add_column("jd_workbench_sync_policies", sa.Column("queue_state", sa.String(16)))
    op.add_column("jd_workbench_sync_policies", sa.Column("lease_worker_id", sa.String(120)))
    op.add_column("jd_workbench_sync_policies", sa.Column("lease_started_at", sa.DateTime(timezone=True)))
    op.add_column("jd_workbench_sync_policies", sa.Column("lease_heartbeat_at", sa.DateTime(timezone=True)))
    op.add_column("jd_workbench_sync_policies", sa.Column("visibility_deadline", sa.DateTime(timezone=True)))
    op.add_column("jd_workbench_sync_policies", sa.Column("sync_window_started_at", sa.DateTime(timezone=True)))
    op.create_unique_constraint(
        "uq_jd_workbench_sync_policies_active_task_id",
        "jd_workbench_sync_policies",
        ["active_task_id"],
    )


def downgrade():
    op.drop_constraint(
        "uq_jd_workbench_sync_policies_active_task_id",
        "jd_workbench_sync_policies",
        type_="unique",
    )
    for column in (
        "sync_window_started_at",
        "visibility_deadline",
        "lease_heartbeat_at",
        "lease_started_at",
        "lease_worker_id",
        "queue_state",
        "active_task_id",
    ):
        op.drop_column("jd_workbench_sync_policies", column)
