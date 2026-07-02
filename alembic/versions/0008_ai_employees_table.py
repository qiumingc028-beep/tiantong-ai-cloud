"""ai employees registry table

Revision ID: 0008_ai_employees_table
Revises: 0007_task_center_tables
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa


revision = "0008_ai_employees_table"
down_revision = "0007_task_center_tables"
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
    if not _has_table("ai_employees"):
        op.create_table(
            "ai_employees",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("employee_name", sa.String(100), nullable=False),
            sa.Column("legion", sa.String(100)),
            sa.Column("duty", sa.Text()),
            sa.Column("status", sa.String(50), nullable=False, server_default="active"),
            sa.Column("task_types", sa.Text()),
            sa.Column("default_permissions", sa.Text()),
            sa.Column("is_legacy", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_ai_employees_employee_code", "ai_employees", ["employee_code"], unique=True)
    _create_index_if_missing("ix_ai_employees_status", "ai_employees", ["status"])


def downgrade():
    if _has_table("ai_employees"):
        if _has_index("ai_employees", "ix_ai_employees_status"):
            op.drop_index("ix_ai_employees_status", table_name="ai_employees")
        if _has_index("ai_employees", "ix_ai_employees_employee_code"):
            op.drop_index("ix_ai_employees_employee_code", table_name="ai_employees")
        op.drop_table("ai_employees")
