"""deploy center mvp tables

Revision ID: 0009_deploy_center_tables
Revises: 0008_ai_employees_table
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa


revision = "0009_deploy_center_tables"
down_revision = "0008_ai_employees_table"
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


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade():
    if not _has_table("deploy_records"):
        op.create_table(
            "deploy_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("deploy_version", sa.String(100)),
            sa.Column("commit_hash", sa.String(100)),
            sa.Column("branch", sa.String(100)),
            sa.Column("operator", sa.String(100)),
            sa.Column("status", sa.String(50), nullable=False, server_default="initialized"),
            sa.Column("started_at", sa.DateTime(timezone=True)),
            sa.Column("finished_at", sa.DateTime(timezone=True)),
            sa.Column("note", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_deploy_records_status", "deploy_records", ["status"])

    if not _has_table("deploy_health_checks"):
        op.create_table(
            "deploy_health_checks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("check_type", sa.String(50), nullable=False),
            sa.Column("target", sa.String(100), nullable=False),
            sa.Column("status", sa.String(50), nullable=False),
            sa.Column("message", sa.Text()),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_deploy_health_checks_check_type", "deploy_health_checks", ["check_type"])
    _create_index_if_missing("ix_deploy_health_checks_status", "deploy_health_checks", ["status"])


def downgrade():
    if _has_table("deploy_health_checks"):
        if _has_index("deploy_health_checks", "ix_deploy_health_checks_status"):
            op.drop_index("ix_deploy_health_checks_status", table_name="deploy_health_checks")
        if _has_index("deploy_health_checks", "ix_deploy_health_checks_check_type"):
            op.drop_index("ix_deploy_health_checks_check_type", table_name="deploy_health_checks")
        op.drop_table("deploy_health_checks")

    if _has_table("deploy_records"):
        if _has_index("deploy_records", "ix_deploy_records_status"):
            op.drop_index("ix_deploy_records_status", table_name="deploy_records")
        op.drop_table("deploy_records")
