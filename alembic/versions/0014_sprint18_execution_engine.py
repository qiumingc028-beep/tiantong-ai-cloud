"""sprint18 execution engine

Revision ID: 0014_sprint18_execution_engine
Revises: 0013_sprint17_auto_dispatch
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa


revision = "0014_sprint18_execution_engine"
down_revision = "0013_sprint17_auto_dispatch"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(column["name"] == column_name for column in _inspector().get_columns(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(index["name"] == index_name for index in _inspector().get_indexes(table_name))


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if _has_table(table_name) and not _has_column(table_name, column.name):
        op.add_column(table_name, column)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade():
    if not _has_table("employee_execution_logs"):
        op.create_table(
            "employee_execution_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("action", sa.String(100), nullable=False),
            sa.Column("result", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    _add_column_if_missing("employee_execution_logs", sa.Column("status", sa.String(50)))
    _add_column_if_missing("employee_execution_logs", sa.Column("input_data", sa.Text()))
    _add_column_if_missing("employee_execution_logs", sa.Column("output_data", sa.Text()))
    _add_column_if_missing("employee_execution_logs", sa.Column("tool_used", sa.Text()))
    _add_column_if_missing("employee_execution_logs", sa.Column("error_message", sa.Text()))
    _add_column_if_missing("employee_execution_logs", sa.Column("started_at", sa.DateTime(timezone=True)))
    _add_column_if_missing("employee_execution_logs", sa.Column("finished_at", sa.DateTime(timezone=True)))

    _create_index_if_missing("ix_employee_execution_logs_task_id", "employee_execution_logs", ["task_id"])
    _create_index_if_missing("ix_employee_execution_logs_employee_code", "employee_execution_logs", ["employee_code"])
    _create_index_if_missing("ix_employee_execution_logs_status", "employee_execution_logs", ["status"])


def downgrade():
    if not _has_table("employee_execution_logs"):
        return
    if _has_index("employee_execution_logs", "ix_employee_execution_logs_status"):
        op.drop_index("ix_employee_execution_logs_status", table_name="employee_execution_logs")
    for column_name in ("finished_at", "started_at", "error_message", "tool_used", "output_data", "input_data", "status"):
        if _has_column("employee_execution_logs", column_name):
            op.drop_column("employee_execution_logs", column_name)
