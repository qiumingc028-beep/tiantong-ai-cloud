"""sprint19 review learning center

Revision ID: 0015_sprint19_review_learning
Revises: 0014_sprint18_execution_engine
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa


revision = "0015_sprint19_review_learning"
down_revision = "0014_sprint18_execution_engine"
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


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade():
    if not _has_table("task_reviews"):
        op.create_table(
            "task_reviews",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("problem_reason", sa.Text()),
            sa.Column("improvement", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_task_reviews_task_id", "task_reviews", ["task_id"])
    _create_index_if_missing("ix_task_reviews_employee_code", "task_reviews", ["employee_code"])
    _create_index_if_missing("ix_task_reviews_success", "task_reviews", ["success"])
    _create_index_if_missing("ix_task_reviews_created_at", "task_reviews", ["created_at"])

    if not _has_table("employee_scores"):
        op.create_table(
            "employee_scores",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("task_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("success_rate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("average_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("skill_growth", sa.Float(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_employee_scores_employee_code", "employee_scores", ["employee_code"], unique=True)
    _create_index_if_missing("ix_employee_scores_updated_at", "employee_scores", ["updated_at"])

    if not _has_table("knowledge_feedback"):
        op.create_table(
            "knowledge_feedback",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_task", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("problem", sa.Text()),
            sa.Column("solution", sa.Text()),
            sa.Column("skill_update", sa.Text()),
            sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_knowledge_feedback_source_task", "knowledge_feedback", ["source_task"])
    _create_index_if_missing("ix_knowledge_feedback_status", "knowledge_feedback", ["status"])
    _create_index_if_missing("ix_knowledge_feedback_created_at", "knowledge_feedback", ["created_at"])


def downgrade():
    for table_name in ("knowledge_feedback", "employee_scores", "task_reviews"):
        if _has_table(table_name):
            op.drop_table(table_name)
