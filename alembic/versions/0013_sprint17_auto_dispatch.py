"""sprint17 auto dispatch

Revision ID: 0013_sprint17_auto_dispatch
Revises: 0012_sprint16_ceo_deploy_loop
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa


revision = "0013_sprint17_auto_dispatch"
down_revision = "0012_sprint16_ceo_deploy_loop"
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
    if not _has_table("employee_capabilities"):
        op.create_table(
            "employee_capabilities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("employee_name", sa.String(100), nullable=False),
            sa.Column("skills", sa.Text()),
            sa.Column("supported_tasks", sa.Text()),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("risk_level", sa.String(50), nullable=False, server_default="low"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_employee_capabilities_employee_code", "employee_capabilities", ["employee_code"])
    _create_index_if_missing("ix_employee_capabilities_risk_level", "employee_capabilities", ["risk_level"])

    if not _has_table("task_routing_rules"):
        op.create_table(
            "task_routing_rules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_type", sa.String(100), nullable=False),
            sa.Column("keyword_rules", sa.Text()),
            sa.Column("recommended_employee", sa.String(100), nullable=False),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("risk_level", sa.String(50), nullable=False, server_default="low"),
        )
    _create_index_if_missing("ix_task_routing_rules_task_type", "task_routing_rules", ["task_type"])
    _create_index_if_missing("ix_task_routing_rules_recommended_employee", "task_routing_rules", ["recommended_employee"])
    _create_index_if_missing("ix_task_routing_rules_risk_level", "task_routing_rules", ["risk_level"])

    if not _has_table("dispatch_records"):
        op.create_table(
            "dispatch_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("dispatch_reason", sa.Text()),
            sa.Column("dispatch_status", sa.String(50), nullable=False, server_default="planned"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_dispatch_records_task_id", "dispatch_records", ["task_id"])
    _create_index_if_missing("ix_dispatch_records_employee_code", "dispatch_records", ["employee_code"])
    _create_index_if_missing("ix_dispatch_records_dispatch_status", "dispatch_records", ["dispatch_status"])

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
    _create_index_if_missing("ix_employee_execution_logs_task_id", "employee_execution_logs", ["task_id"])
    _create_index_if_missing("ix_employee_execution_logs_employee_code", "employee_execution_logs", ["employee_code"])


def downgrade():
    for table_name, indexes in (
        ("employee_execution_logs", ("ix_employee_execution_logs_employee_code", "ix_employee_execution_logs_task_id")),
        ("dispatch_records", ("ix_dispatch_records_dispatch_status", "ix_dispatch_records_employee_code", "ix_dispatch_records_task_id")),
        ("task_routing_rules", ("ix_task_routing_rules_risk_level", "ix_task_routing_rules_recommended_employee", "ix_task_routing_rules_task_type")),
        ("employee_capabilities", ("ix_employee_capabilities_risk_level", "ix_employee_capabilities_employee_code")),
    ):
        if _has_table(table_name):
            for index_name in indexes:
                if _has_index(table_name, index_name):
                    op.drop_index(index_name, table_name=table_name)
            op.drop_table(table_name)
