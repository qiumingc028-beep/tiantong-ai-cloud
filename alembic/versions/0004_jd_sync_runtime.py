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


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(index["name"] == index_name for index in _inspector().get_indexes(table_name))


def _create_table_if_missing(table_name: str, *columns, **kwargs) -> None:
    if not _has_table(table_name):
        op.create_table(table_name, *columns, **kwargs)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str], **kwargs) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns, **kwargs)


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(column["name"] == column_name for column in _inspector().get_columns(table_name))


def _add_column_if_missing(table_name: str, column) -> None:
    if _has_table(table_name) and not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def upgrade():
    _add_column_if_missing("jd_accounts", sa.Column("platform", sa.String(50), nullable=False, server_default="jd"))
    _add_column_if_missing("jd_accounts", sa.Column("login_status", sa.String(50), server_default="unknown"))
    _add_column_if_missing("jd_accounts", sa.Column("cookie_status", sa.String(50), server_default="unknown"))
    _add_column_if_missing("jd_accounts", sa.Column("last_login_at", sa.DateTime(timezone=True)))
    _add_column_if_missing("jd_accounts", sa.Column("remark", sa.Text()))
    _create_table_if_missing(
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
    _create_index_if_missing("ix_jd_sync_logs_task_id", "jd_sync_logs", ["task_id"])


def downgrade():
    op.drop_index("ix_jd_sync_logs_task_id", table_name="jd_sync_logs")
    op.drop_table("jd_sync_logs")
    op.drop_column("jd_accounts", "remark")
    op.drop_column("jd_accounts", "last_login_at")
    op.drop_column("jd_accounts", "cookie_status")
    op.drop_column("jd_accounts", "login_status")
    op.drop_column("jd_accounts", "platform")
