"""jd sync runtime fields

Revision ID: 0004_jd_sync_runtime
Revises: 0003_account_center_tables
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_jd_sync_runtime"
down_revision = "0003_account_center_tables"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jd_accounts", sa.Column("platform", sa.String(50), nullable=False, server_default="jd"))
    op.add_column("jd_accounts", sa.Column("login_status", sa.String(50), server_default="unknown"))
    op.add_column("jd_accounts", sa.Column("cookie_status", sa.String(50), server_default="unknown"))
    op.add_column("jd_accounts", sa.Column("last_login_at", sa.DateTime(timezone=True)))
    op.add_column("jd_accounts", sa.Column("remark", sa.Text()))
    op.create_table(
        "jd_sync_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="SET NULL")),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("jd_accounts.id", ondelete="SET NULL")),
        sa.Column("task_id", sa.String(100)),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("attempt", sa.Integer(), default=0),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_jd_sync_logs_task_id", "jd_sync_logs", ["task_id"])


def downgrade():
    op.drop_index("ix_jd_sync_logs_task_id", table_name="jd_sync_logs")
    op.drop_table("jd_sync_logs")
    op.drop_column("jd_accounts", "remark")
    op.drop_column("jd_accounts", "last_login_at")
    op.drop_column("jd_accounts", "cookie_status")
    op.drop_column("jd_accounts", "login_status")
    op.drop_column("jd_accounts", "platform")
