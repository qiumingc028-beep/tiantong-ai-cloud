"""sprint21 tool center

Revision ID: 0019_sprint21_tool_center
Revises: 0018_sprint21_ai_capabilities
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0019_sprint21_tool_center"
down_revision = "0018_sprint21_ai_capabilities"
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
    if not _has_table("tool_registry"):
        op.create_table(
            "tool_registry",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tool_name", sa.String(120), nullable=False, unique=True),
            sa.Column("tool_type", sa.String(80), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("provider", sa.String(120), nullable=False, server_default="internal"),
            sa.Column("version", sa.String(40), nullable=False, server_default="v1"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("risk_level", sa.String(40), nullable=False, server_default="low"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_tool_registry_tool_name", "tool_registry", ["tool_name"])
    _create_index_if_missing("ix_tool_registry_tool_type", "tool_registry", ["tool_type"])
    _create_index_if_missing("ix_tool_registry_enabled", "tool_registry", ["enabled"])
    _create_index_if_missing("ix_tool_registry_risk_level", "tool_registry", ["risk_level"])
    _create_index_if_missing("ix_tool_registry_created_at", "tool_registry", ["created_at"])

    if not _has_table("employee_tool_binding"):
        op.create_table(
            "employee_tool_binding",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("tool_id", sa.Integer(), nullable=False),
            sa.Column("permission_level", sa.String(80), nullable=False, server_default="read_only"),
            sa.Column("allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("require_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    _create_index_if_missing("ix_employee_tool_binding_employee_code", "employee_tool_binding", ["employee_code"])
    _create_index_if_missing("ix_employee_tool_binding_tool_id", "employee_tool_binding", ["tool_id"])
    _create_index_if_missing("ix_employee_tool_binding_permission_level", "employee_tool_binding", ["permission_level"])
    _create_index_if_missing("ix_employee_tool_binding_allowed", "employee_tool_binding", ["allowed"])
    _create_index_if_missing("ix_employee_tool_binding_require_approval", "employee_tool_binding", ["require_approval"])

    if not _has_table("tool_execution_logs"):
        op.create_table(
            "tool_execution_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("tool_name", sa.String(120), nullable=False),
            sa.Column("request", sa.Text()),
            sa.Column("response", sa.Text()),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("cost", sa.Float(), nullable=False, server_default="0"),
            sa.Column("duration", sa.Float(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_tool_execution_logs_employee_code", "tool_execution_logs", ["employee_code"])
    _create_index_if_missing("ix_tool_execution_logs_tool_name", "tool_execution_logs", ["tool_name"])
    _create_index_if_missing("ix_tool_execution_logs_status", "tool_execution_logs", ["status"])
    _create_index_if_missing("ix_tool_execution_logs_created_at", "tool_execution_logs", ["created_at"])


def downgrade():
    for table_name in ("tool_execution_logs", "employee_tool_binding", "tool_registry"):
        if _has_table(table_name):
            op.drop_table(table_name)

