"""sprint16 ceo deploy loop

Revision ID: 0012_sprint16_ceo_deploy_loop
Revises: 0011_orchestrator_task_links
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa


revision = "0012_sprint16_ceo_deploy_loop"
down_revision = "0011_orchestrator_task_links"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _columns(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {column["name"] for column in _inspector().get_columns(table_name)}


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(index["name"] == index_name for index in _inspector().get_indexes(table_name))


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _has_table(table_name) and column.name not in _columns(table_name):
        op.add_column(table_name, column)


def upgrade():
    if _has_table("deploy_records"):
        _add_column_if_missing("deploy_records", sa.Column("deploy_id", sa.String(100)))
        _add_column_if_missing("deploy_records", sa.Column("version", sa.String(100)))
        _add_column_if_missing("deploy_records", sa.Column("commit_id", sa.String(100)))
        _add_column_if_missing("deploy_records", sa.Column("deploy_time", sa.DateTime(timezone=True)))
        _add_column_if_missing("deploy_records", sa.Column("deploy_status", sa.String(50)))
        _create_index_if_missing("ix_deploy_records_deploy_id", "deploy_records", ["deploy_id"])
        _create_index_if_missing("ix_deploy_records_deploy_status", "deploy_records", ["deploy_status"])

    if not _has_table("health_check_records"):
        op.create_table(
            "health_check_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("service", sa.String(100), nullable=False),
            sa.Column("status", sa.String(50), nullable=False),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("latency", sa.Integer()),
        )
    _create_index_if_missing("ix_health_check_records_service", "health_check_records", ["service"])
    _create_index_if_missing("ix_health_check_records_status", "health_check_records", ["status"])


def downgrade():
    if _has_table("health_check_records"):
        if _has_index("health_check_records", "ix_health_check_records_status"):
            op.drop_index("ix_health_check_records_status", table_name="health_check_records")
        if _has_index("health_check_records", "ix_health_check_records_service"):
            op.drop_index("ix_health_check_records_service", table_name="health_check_records")
        op.drop_table("health_check_records")

    if _has_table("deploy_records"):
        for index_name in ("ix_deploy_records_deploy_status", "ix_deploy_records_deploy_id"):
            if _has_index("deploy_records", index_name):
                op.drop_index(index_name, table_name="deploy_records")
        existing = _columns("deploy_records")
        for column_name in ("deploy_status", "deploy_time", "commit_id", "version", "deploy_id"):
            if column_name in existing:
                op.drop_column("deploy_records", column_name)
