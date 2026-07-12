"""sprint26 ai employee execution mvp

Revision ID: 0026_sprint26_ai_employee_execution_mvp
Revises: 0025_sprint25_3_execution_engine_enhancement
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0026_sprint26_ai_employee_execution_mvp"
down_revision = "0025_sprint25_3_execution_engine_enhancement"
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


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _ensure_alembic_version_length() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    if _has_table("alembic_version"):
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=128),
            type_=sa.String(length=128),
            existing_nullable=False,
        )


def upgrade():
    _ensure_alembic_version_length()
    if not _has_table("employee_execution_contracts"):
        op.create_table(
            "employee_execution_contracts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_id", sa.String(120), nullable=False),
            sa.Column("task_id", sa.String(120), nullable=False),
            sa.Column("input_data", sa.Text(), nullable=True),
            sa.Column("required_tools", sa.Text(), nullable=True),
            sa.Column("execution_plan", sa.Text(), nullable=True),
            sa.Column("result", sa.Text(), nullable=True),
            sa.Column("status", sa.String(40), nullable=False, server_default="CREATED"),
            sa.Column("error_log", sa.Text(), nullable=True),
            sa.Column("review_status", sa.String(40), nullable=False, server_default="pending"),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("current_step", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    for name, columns in {
        "ix_employee_execution_contracts_employee_id": ["employee_id"],
        "ix_employee_execution_contracts_task_id": ["task_id"],
        "ix_employee_execution_contracts_status": ["status"],
        "ix_employee_execution_contracts_review_status": ["review_status"],
        "ix_employee_execution_contracts_created_at": ["created_at"],
        "ix_employee_execution_contracts_updated_at": ["updated_at"],
    }.items():
        _create_index_if_missing(name, "employee_execution_contracts", columns)


def downgrade():
    if _has_table("employee_execution_contracts"):
        op.drop_table("employee_execution_contracts")
