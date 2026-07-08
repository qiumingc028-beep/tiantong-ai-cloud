"""sprint24 brain execution center

Revision ID: 0023_sprint24_brain_execution
Revises: 0022_sprint23_brain_orchestrator
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0023_sprint24_brain_execution"
down_revision = "0022_sprint23_brain_orchestrator"
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
    if not _has_table("brain_execution_runs"):
        op.create_table(
            "brain_execution_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("goal", sa.Text(), nullable=False),
            sa.Column("status", sa.String(40), nullable=False, server_default="planned"),
            sa.Column("risk_level", sa.String(40), nullable=False, server_default="low"),
            sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.String(100)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    for name, columns in {
        "ix_brain_execution_runs_status": ["status"],
        "ix_brain_execution_runs_risk_level": ["risk_level"],
        "ix_brain_execution_runs_approval_required": ["approval_required"],
        "ix_brain_execution_runs_dry_run": ["dry_run"],
        "ix_brain_execution_runs_created_by": ["created_by"],
        "ix_brain_execution_runs_created_at": ["created_at"],
    }.items():
        _create_index_if_missing(name, "brain_execution_runs", columns)

    _add_column_if_missing("brain_task_nodes", sa.Column("execution_id", sa.Integer(), nullable=True))
    _add_column_if_missing("brain_task_nodes", sa.Column("tool_name", sa.String(120), nullable=True))
    _create_index_if_missing("ix_brain_task_nodes_execution_id", "brain_task_nodes", ["execution_id"])
    _create_index_if_missing("ix_brain_task_nodes_tool_name", "brain_task_nodes", ["tool_name"])

    _add_column_if_missing("brain_task_edges", sa.Column("execution_id", sa.Integer(), nullable=True))
    _create_index_if_missing("ix_brain_task_edges_execution_id", "brain_task_edges", ["execution_id"])

    if not _has_table("brain_approval_records"):
        op.create_table(
            "brain_approval_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("execution_id", sa.Integer(), nullable=False),
            sa.Column("node_id", sa.String(120)),
            sa.Column("approve_user", sa.String(100)),
            sa.Column("decision", sa.String(40), nullable=False, server_default="pending"),
            sa.Column("reason", sa.Text()),
            sa.Column("boss_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("security_audited", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    for name, columns in {
        "ix_brain_approval_records_execution_id": ["execution_id"],
        "ix_brain_approval_records_node_id": ["node_id"],
        "ix_brain_approval_records_approve_user": ["approve_user"],
        "ix_brain_approval_records_decision": ["decision"],
        "ix_brain_approval_records_boss_confirmed": ["boss_confirmed"],
        "ix_brain_approval_records_security_audited": ["security_audited"],
        "ix_brain_approval_records_timestamp": ["timestamp"],
    }.items():
        _create_index_if_missing(name, "brain_approval_records", columns)

    if not _has_table("brain_tool_calls"):
        op.create_table(
            "brain_tool_calls",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("execution_id", sa.Integer(), nullable=False),
            sa.Column("node_id", sa.String(120)),
            sa.Column("employee_code", sa.String(100)),
            sa.Column("tool_name", sa.String(120)),
            sa.Column("request_payload", sa.Text()),
            sa.Column("response_payload", sa.Text()),
            sa.Column("permission_result", sa.Text()),
            sa.Column("risk_level", sa.String(40), nullable=False, server_default="low"),
            sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("status", sa.String(40), nullable=False, server_default="simulated"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    for name, columns in {
        "ix_brain_tool_calls_execution_id": ["execution_id"],
        "ix_brain_tool_calls_node_id": ["node_id"],
        "ix_brain_tool_calls_employee_code": ["employee_code"],
        "ix_brain_tool_calls_tool_name": ["tool_name"],
        "ix_brain_tool_calls_risk_level": ["risk_level"],
        "ix_brain_tool_calls_dry_run": ["dry_run"],
        "ix_brain_tool_calls_status": ["status"],
        "ix_brain_tool_calls_created_at": ["created_at"],
    }.items():
        _create_index_if_missing(name, "brain_tool_calls", columns)

    for column in (
        sa.Column("run_id", sa.String(80), nullable=True),
        sa.Column("node_id", sa.String(120), nullable=True),
        sa.Column("employee_code", sa.String(100), nullable=True),
        sa.Column("action", sa.String(120), nullable=True),
        sa.Column("input_data", sa.Text(), nullable=True),
        sa.Column("output_data", sa.Text(), nullable=True),
        sa.Column("status", sa.String(40), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    ):
        _add_column_if_missing("brain_execution_logs", column)
    for name, columns in {
        "ix_brain_execution_logs_run_id": ["run_id"],
        "ix_brain_execution_logs_node_id": ["node_id"],
        "ix_brain_execution_logs_employee_code": ["employee_code"],
        "ix_brain_execution_logs_status": ["status"],
    }.items():
        _create_index_if_missing(name, "brain_execution_logs", columns)


def downgrade():
    for table_name in ("brain_tool_calls", "brain_approval_records", "brain_execution_runs"):
        if _has_table(table_name):
            op.drop_table(table_name)

