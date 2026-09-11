"""Add R297 persistent multi-store auto-sync scheduling.

Revision ID: 0049_r297_jd_multistore_autosync
Revises: 0048_r291_jd_workbench_hybrid_cloud
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0049_r297_jd_multistore_autosync"
down_revision = "0048_r291_jd_workbench_hybrid_cloud"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jd_workbench_store_statuses", sa.Column("last_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("jd_workbench_store_statuses", sa.Column("next_sync_at", sa.DateTime(timezone=True)))
    op.add_column(
        "jd_workbench_store_statuses",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("jd_workbench_store_statuses", sa.Column("last_error_at", sa.DateTime(timezone=True)))

    op.create_table(
        "jd_workbench_sync_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("updated_by_user_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "interval_seconds >= 300 AND interval_seconds <= 86400",
            name="ck_jd_workbench_sync_policy_interval",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "store_id", name="uq_jd_workbench_sync_policy_tenant_store"),
    )
    op.create_index("ix_jd_workbench_sync_policies_tenant_id", "jd_workbench_sync_policies", ["tenant_id"])
    op.create_index("ix_jd_workbench_sync_policies_company_id", "jd_workbench_sync_policies", ["company_id"])
    op.create_index("ix_jd_workbench_sync_policies_store_id", "jd_workbench_sync_policies", ["store_id"])


def downgrade():
    op.drop_index("ix_jd_workbench_sync_policies_store_id", table_name="jd_workbench_sync_policies")
    op.drop_index("ix_jd_workbench_sync_policies_company_id", table_name="jd_workbench_sync_policies")
    op.drop_index("ix_jd_workbench_sync_policies_tenant_id", table_name="jd_workbench_sync_policies")
    op.drop_table("jd_workbench_sync_policies")
    op.drop_column("jd_workbench_store_statuses", "last_error_at")
    op.drop_column("jd_workbench_store_statuses", "retry_count")
    op.drop_column("jd_workbench_store_statuses", "next_sync_at")
    op.drop_column("jd_workbench_store_statuses", "last_attempt_at")
