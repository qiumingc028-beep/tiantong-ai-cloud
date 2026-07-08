"""sprint21 tool router

Revision ID: 0020_sprint21_tool_router
Revises: 0019_sprint21_tool_center
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0020_sprint21_tool_router"
down_revision = "0019_sprint21_tool_center"
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
    if not _has_table("tool_routes"):
        op.create_table(
            "tool_routes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("tool_name", sa.String(120), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("risk_level", sa.String(40), nullable=False, server_default="low"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_tool_routes_employee_code", "tool_routes", ["employee_code"])
    _create_index_if_missing("ix_tool_routes_tool_name", "tool_routes", ["tool_name"])
    _create_index_if_missing("ix_tool_routes_priority", "tool_routes", ["priority"])
    _create_index_if_missing("ix_tool_routes_risk_level", "tool_routes", ["risk_level"])
    _create_index_if_missing("ix_tool_routes_enabled", "tool_routes", ["enabled"])
    _create_index_if_missing("ix_tool_routes_created_at", "tool_routes", ["created_at"])

    if not _has_table("tool_route_logs"):
        op.create_table(
            "tool_route_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("task", sa.Text()),
            sa.Column("requirement", sa.Text()),
            sa.Column("recommended_tool", sa.String(120), nullable=False),
            sa.Column("risk_level", sa.String(40), nullable=False),
            sa.Column("require_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("reason", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_tool_route_logs_employee_code", "tool_route_logs", ["employee_code"])
    _create_index_if_missing("ix_tool_route_logs_recommended_tool", "tool_route_logs", ["recommended_tool"])
    _create_index_if_missing("ix_tool_route_logs_risk_level", "tool_route_logs", ["risk_level"])
    _create_index_if_missing("ix_tool_route_logs_require_approval", "tool_route_logs", ["require_approval"])
    _create_index_if_missing("ix_tool_route_logs_allowed", "tool_route_logs", ["allowed"])
    _create_index_if_missing("ix_tool_route_logs_created_at", "tool_route_logs", ["created_at"])


def downgrade():
    for table_name in ("tool_route_logs", "tool_routes"):
        if _has_table(table_name):
            op.drop_table(table_name)

