"""task center mvp tables

Revision ID: 0007_task_center_tables
Revises: 0006_merge_knowledge_heads
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa


revision = "0007_task_center_tables"
down_revision = "0006_merge_knowledge_heads"
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
    if not _has_table("task_center_tasks"):
        op.create_table(
            "task_center_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("status", sa.String(50), nullable=False, server_default="created"),
            sa.Column("priority", sa.String(50), nullable=False, server_default="normal"),
            sa.Column("source", sa.String(50), nullable=False, server_default="boss"),
            sa.Column("parent_task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL")),
            sa.Column("assigned_ai_employee_code", sa.String(50)),
            sa.Column("assigned_ai_employee_name", sa.String(100)),
            sa.Column("split_plan", sa.Text()),
            sa.Column("summary", sa.Text()),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_task_center_tasks_status", "task_center_tasks", ["status"])
    _create_index_if_missing("ix_task_center_tasks_assigned_ai_employee_code", "task_center_tasks", ["assigned_ai_employee_code"])

    if not _has_table("task_center_results"):
        op.create_table(
            "task_center_results",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("ai_employee_code", sa.String(50), nullable=False),
            sa.Column("ai_employee_name", sa.String(100)),
            sa.Column("result_content", sa.Text(), nullable=False),
            sa.Column("attachments_json", sa.Text()),
            sa.Column("submitted_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_task_center_results_task_id", "task_center_results", ["task_id"])

    if not _has_table("task_center_reviews"):
        op.create_table(
            "task_center_reviews",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("review_type", sa.String(50), nullable=False),
            sa.Column("review_status", sa.String(50), nullable=False),
            sa.Column("comment", sa.Text()),
            sa.Column("reviewer_role", sa.String(50)),
            sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_task_center_reviews_task_id", "task_center_reviews", ["task_id"])

    if not _has_table("task_center_audit_logs"):
        op.create_table(
            "task_center_audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("action", sa.String(100), nullable=False),
            sa.Column("from_status", sa.String(50)),
            sa.Column("to_status", sa.String(50)),
            sa.Column("detail", sa.Text()),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("actor_role", sa.String(50)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_task_center_audit_logs_task_id", "task_center_audit_logs", ["task_id"])


def downgrade():
    if _has_table("task_center_audit_logs"):
        if _has_index("task_center_audit_logs", "ix_task_center_audit_logs_task_id"):
            op.drop_index("ix_task_center_audit_logs_task_id", table_name="task_center_audit_logs")
        op.drop_table("task_center_audit_logs")
    if _has_table("task_center_reviews"):
        if _has_index("task_center_reviews", "ix_task_center_reviews_task_id"):
            op.drop_index("ix_task_center_reviews_task_id", table_name="task_center_reviews")
        op.drop_table("task_center_reviews")
    if _has_table("task_center_results"):
        if _has_index("task_center_results", "ix_task_center_results_task_id"):
            op.drop_index("ix_task_center_results_task_id", table_name="task_center_results")
        op.drop_table("task_center_results")
    if _has_table("task_center_tasks"):
        if _has_index("task_center_tasks", "ix_task_center_tasks_assigned_ai_employee_code"):
            op.drop_index("ix_task_center_tasks_assigned_ai_employee_code", table_name="task_center_tasks")
        if _has_index("task_center_tasks", "ix_task_center_tasks_status"):
            op.drop_index("ix_task_center_tasks_status", table_name="task_center_tasks")
        op.drop_table("task_center_tasks")
