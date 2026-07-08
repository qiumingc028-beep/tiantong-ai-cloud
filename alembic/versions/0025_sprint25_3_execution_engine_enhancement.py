"""sprint25.3 execution engine enhancement

Revision ID: 0025_sprint25_3_execution_engine_enhancement
Revises: 0024_sprint25_brain_runtime
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0025_sprint25_3_execution_engine_enhancement"
down_revision = "0024_sprint25_brain_runtime"
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


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def _ensure_alembic_version_length() -> None:
    if _has_table("alembic_version"):
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=32),
            type_=sa.String(length=128),
            existing_nullable=False,
        )


def upgrade():
    _ensure_alembic_version_length()
    for column in (
        sa.Column("employee_id", sa.String(120), nullable=True),
        sa.Column("priority", sa.String(40), nullable=False, server_default="normal"),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retry", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("worker_id", sa.String(120), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    ):
        _add_column_if_missing("brain_execution_runs", column)

    for name, columns in {
        "ix_brain_execution_runs_employee_id": ["employee_id"],
        "ix_brain_execution_runs_priority": ["priority"],
        "ix_brain_execution_runs_queued_at": ["queued_at"],
        "ix_brain_execution_runs_timeout_seconds": ["timeout_seconds"],
        "ix_brain_execution_runs_retry_count": ["retry_count"],
        "ix_brain_execution_runs_worker_id": ["worker_id"],
    }.items():
        _create_index_if_missing(name, "brain_execution_runs", columns)

    if not _has_table("execution_context"):
        op.create_table(
            "execution_context",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("execution_id", sa.Integer(), nullable=False),
            sa.Column("node_id", sa.String(120), nullable=True),
            sa.Column("employee_code", sa.String(100), nullable=True),
            sa.Column("current_task", sa.Text(), nullable=True),
            sa.Column("input_data", sa.Text(), nullable=True),
            sa.Column("tool_permissions", sa.Text(), nullable=True),
            sa.Column("risk_level", sa.String(40), nullable=False, server_default="low"),
            sa.Column("historical_execution", sa.Text(), nullable=True),
            sa.Column("approval_status", sa.String(80), nullable=True),
            sa.Column("context_data", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    for name, columns in {
        "ix_execution_context_execution_id": ["execution_id"],
        "ix_execution_context_node_id": ["node_id"],
        "ix_execution_context_employee_code": ["employee_code"],
        "ix_execution_context_risk_level": ["risk_level"],
        "ix_execution_context_approval_status": ["approval_status"],
        "ix_execution_context_created_at": ["created_at"],
    }.items():
        _create_index_if_missing(name, "execution_context", columns)

    if not _has_table("brain_worker_status"):
        op.create_table(
            "brain_worker_status",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("worker_id", sa.String(120), nullable=False),
            sa.Column("status", sa.String(40), nullable=False, server_default="idle"),
            sa.Column("current_execution_id", sa.Integer(), nullable=True),
            sa.Column("current_node_id", sa.String(120), nullable=True),
            sa.Column("current_task", sa.Text(), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("timeout_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    for name, columns, unique in (
        ("ix_brain_worker_status_worker_id", ["worker_id"], True),
        ("ix_brain_worker_status_status", ["status"], False),
        ("ix_brain_worker_status_current_execution_id", ["current_execution_id"], False),
        ("ix_brain_worker_status_current_node_id", ["current_node_id"], False),
        ("ix_brain_worker_status_heartbeat_at", ["heartbeat_at"], False),
        ("ix_brain_worker_status_updated_at", ["updated_at"], False),
    ):
        _create_index_if_missing(name, "brain_worker_status", columns, unique=unique)

    if not _has_table("brain_execution_recovery"):
        op.create_table(
            "brain_execution_recovery",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("execution_id", sa.Integer(), nullable=False),
            sa.Column("node_id", sa.String(120), nullable=True),
            sa.Column("failure_type", sa.String(80), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_retry", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("recovery_action", sa.Text(), nullable=True),
            sa.Column("recovery_status", sa.String(80), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    for name, columns in {
        "ix_brain_execution_recovery_execution_id": ["execution_id"],
        "ix_brain_execution_recovery_node_id": ["node_id"],
        "ix_brain_execution_recovery_failure_type": ["failure_type"],
        "ix_brain_execution_recovery_recovery_status": ["recovery_status"],
        "ix_brain_execution_recovery_created_at": ["created_at"],
    }.items():
        _create_index_if_missing(name, "brain_execution_recovery", columns)


def downgrade():
    for table_name in ("brain_execution_recovery", "brain_worker_status", "execution_context"):
        if _has_table(table_name):
            op.drop_table(table_name)
