"""sprint22 brain tool router

Revision ID: 0021_sprint22_brain_tool_router
Revises: 0020_sprint21_tool_router
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0021_sprint22_brain_tool_router"
down_revision = "0020_sprint21_tool_router"
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


def upgrade():
    if not _has_table("brain_execution_logs"):
        op.create_table(
            "brain_execution_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_request", sa.Text(), nullable=False),
            sa.Column("ai_analysis_result", sa.Text()),
            sa.Column("recommended_employee", sa.String(100)),
            sa.Column("tool_selection", sa.Text()),
            sa.Column("approval_status", sa.String(40), nullable=False, server_default="not_checked"),
            sa.Column("execution_result", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_brain_execution_logs_recommended_employee", "brain_execution_logs", ["recommended_employee"])
    _create_index_if_missing("ix_brain_execution_logs_approval_status", "brain_execution_logs", ["approval_status"])
    _create_index_if_missing("ix_brain_execution_logs_created_at", "brain_execution_logs", ["created_at"])


def downgrade():
    if _has_table("brain_execution_logs"):
        op.drop_table("brain_execution_logs")

