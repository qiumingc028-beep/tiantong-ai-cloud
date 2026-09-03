"""Fence R297 queue claims and persist task idempotency.

Revision ID: 0051_r297_queue_fencing_and_idempotency
Revises: 0050_r297_reliable_sync_queue
"""

from alembic import op
import sqlalchemy as sa


revision = "0051_r297_queue_fencing_and_idempotency"
down_revision = "0050_r297_reliable_sync_queue"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "jd_workbench_sync_policies",
        sa.Column("claim_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_unique_constraint(
        "uq_jd_sync_logs_task_attempt",
        "jd_sync_logs",
        ["task_id", "attempt"],
    )


def downgrade():
    op.drop_constraint("uq_jd_sync_logs_task_attempt", "jd_sync_logs", type_="unique")
    op.drop_column("jd_workbench_sync_policies", "claim_generation")
