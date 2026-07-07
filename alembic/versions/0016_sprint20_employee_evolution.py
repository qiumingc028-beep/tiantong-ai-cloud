"""sprint20 employee evolution

Revision ID: 0016_sprint20_employee_evolution
Revises: 0015_sprint19_review_learning
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0016_sprint20_employee_evolution"
down_revision = "0015_sprint19_review_learning"
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
    if not _has_table("employee_growth"):
        op.create_table(
            "employee_growth",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL")),
            sa.Column("score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("growth_level", sa.String(50), nullable=False, server_default="starter"),
            sa.Column("success_rate", sa.Float(), nullable=False, server_default="0"),
            sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("improvement_summary", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_employee_growth_employee_code", "employee_growth", ["employee_code"])
    _create_index_if_missing("ix_employee_growth_task_id", "employee_growth", ["task_id"])
    _create_index_if_missing("ix_employee_growth_created_at", "employee_growth", ["created_at"])

    if not _has_table("review_analysis"):
        op.create_table(
            "review_analysis",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("analysis_type", sa.String(50), nullable=False),
            sa.Column("reason", sa.Text()),
            sa.Column("suggestion", sa.Text()),
            sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_review_analysis_task_id", "review_analysis", ["task_id"])
    _create_index_if_missing("ix_review_analysis_employee_code", "review_analysis", ["employee_code"])
    _create_index_if_missing("ix_review_analysis_analysis_type", "review_analysis", ["analysis_type"])
    _create_index_if_missing("ix_review_analysis_status", "review_analysis", ["status"])

    if not _has_table("skill_suggestions"):
        op.create_table(
            "skill_suggestions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("skill_name", sa.String(120), nullable=False),
            sa.Column("suggestion", sa.Text()),
            sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_skill_suggestions_employee_code", "skill_suggestions", ["employee_code"])
    _create_index_if_missing("ix_skill_suggestions_status", "skill_suggestions", ["status"])

    if not _has_table("risk_events"):
        op.create_table(
            "risk_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("risk_level", sa.String(50), nullable=False, server_default="low"),
            sa.Column("description", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_risk_events_employee_code", "risk_events", ["employee_code"])
    _create_index_if_missing("ix_risk_events_event_type", "risk_events", ["event_type"])
    _create_index_if_missing("ix_risk_events_risk_level", "risk_events", ["risk_level"])


def downgrade():
    for table_name in ("risk_events", "skill_suggestions", "review_analysis", "employee_growth"):
        if _has_table(table_name):
            op.drop_table(table_name)
