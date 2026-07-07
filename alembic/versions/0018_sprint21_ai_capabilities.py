"""sprint21 ai capabilities and tool permissions

Revision ID: 0018_sprint21_ai_capabilities
Revises: 0017_sprint20_5_release_center
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0018_sprint21_ai_capabilities"
down_revision = "0017_sprint20_5_release_center"
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
    if not _has_table("ai_capabilities"):
        op.create_table(
            "ai_capabilities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("employee_name", sa.String(100), nullable=False),
            sa.Column("capability_name", sa.String(120), nullable=False),
            sa.Column("capability_type", sa.String(80), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_ai_capabilities_employee_code", "ai_capabilities", ["employee_code"])
    _create_index_if_missing("ix_ai_capabilities_capability_name", "ai_capabilities", ["capability_name"])
    _create_index_if_missing("ix_ai_capabilities_capability_type", "ai_capabilities", ["capability_type"])
    _create_index_if_missing("ix_ai_capabilities_enabled", "ai_capabilities", ["enabled"])
    _create_index_if_missing("ix_ai_capabilities_created_at", "ai_capabilities", ["created_at"])

    if not _has_table("tool_permissions"):
        op.create_table(
            "tool_permissions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("tool_name", sa.String(120), nullable=False),
            sa.Column("permission_level", sa.String(80), nullable=False),
            sa.Column("allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("require_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_tool_permissions_employee_code", "tool_permissions", ["employee_code"])
    _create_index_if_missing("ix_tool_permissions_tool_name", "tool_permissions", ["tool_name"])
    _create_index_if_missing("ix_tool_permissions_permission_level", "tool_permissions", ["permission_level"])
    _create_index_if_missing("ix_tool_permissions_allowed", "tool_permissions", ["allowed"])
    _create_index_if_missing("ix_tool_permissions_require_approval", "tool_permissions", ["require_approval"])
    _create_index_if_missing("ix_tool_permissions_created_at", "tool_permissions", ["created_at"])


def downgrade():
    for table_name in ("tool_permissions", "ai_capabilities"):
        if _has_table(table_name):
            op.drop_table(table_name)
