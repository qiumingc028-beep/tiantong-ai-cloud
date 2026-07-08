"""sprint25 brain runtime state machine

Revision ID: 0024_sprint25_brain_runtime
Revises: 0023_sprint24_brain_execution
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0024_sprint25_brain_runtime"
down_revision = "0023_sprint24_brain_execution"
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
            sa.Column("task_id", sa.String(120), nullable=True),
            sa.Column("goal", sa.Text(), nullable=False),
            sa.Column("status", sa.String(40), nullable=False, server_default="CREATED"),
            sa.Column("current_node", sa.String(120), nullable=True),
            sa.Column("risk_level", sa.String(40), nullable=False, server_default="low"),
            sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.String(100), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    else:
        for column in (
            sa.Column("task_id", sa.String(120), nullable=True),
            sa.Column("current_node", sa.String(120), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
        ):
            _add_column_if_missing("brain_execution_runs", column)

    for name, columns in {
        "ix_brain_execution_runs_task_id": ["task_id"],
        "ix_brain_execution_runs_current_node": ["current_node"],
        "ix_brain_execution_runs_started_at": ["started_at"],
        "ix_brain_execution_runs_finished_at": ["finished_at"],
    }.items():
        _create_index_if_missing(name, "brain_execution_runs", columns)

    if not _has_table("brain_execution_events"):
        op.create_table(
            "brain_execution_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("execution_id", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(120), nullable=False),
            sa.Column("event_data", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    for name, columns in {
        "ix_brain_execution_events_execution_id": ["execution_id"],
        "ix_brain_execution_events_event_type": ["event_type"],
        "ix_brain_execution_events_created_at": ["created_at"],
    }.items():
        _create_index_if_missing(name, "brain_execution_events", columns)


def downgrade():
    if _has_table("brain_execution_events"):
        op.drop_table("brain_execution_events")
