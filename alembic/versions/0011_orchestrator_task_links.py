"""orchestrator task links

Revision ID: 0011_orchestrator_task_links
Revises: 0010_orchestrator_tables
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa


revision = "0011_orchestrator_task_links"
down_revision = "0010_orchestrator_tables"
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
    if not _has_table("orchestrator_task_links"):
        op.create_table(
            "orchestrator_task_links",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "analysis_record_id",
                sa.Integer(),
                sa.ForeignKey("orchestrator_analysis_records.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "task_id",
                sa.Integer(),
                sa.ForeignKey("task_center_tasks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("link_type", sa.String(50), nullable=False),
            sa.Column("recommended_codex", sa.String(100)),
            sa.Column("recommended_action", sa.String(100)),
            sa.Column("source_stage", sa.String(50)),
            sa.Column("confidence", sa.String(50)),
            sa.Column("note", sa.Text()),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_orchestrator_task_links_analysis_record_id", "orchestrator_task_links", ["analysis_record_id"])
    _create_index_if_missing("ix_orchestrator_task_links_task_id", "orchestrator_task_links", ["task_id"])
    _create_index_if_missing("ix_orchestrator_task_links_link_type", "orchestrator_task_links", ["link_type"])
    _create_index_if_missing("ix_orchestrator_task_links_recommended_codex", "orchestrator_task_links", ["recommended_codex"])
    _create_index_if_missing("ix_orchestrator_task_links_source_stage", "orchestrator_task_links", ["source_stage"])


def downgrade():
    if _has_table("orchestrator_task_links"):
        for index_name in (
            "ix_orchestrator_task_links_source_stage",
            "ix_orchestrator_task_links_recommended_codex",
            "ix_orchestrator_task_links_link_type",
            "ix_orchestrator_task_links_task_id",
            "ix_orchestrator_task_links_analysis_record_id",
        ):
            if _has_index("orchestrator_task_links", index_name):
                op.drop_index(index_name, table_name="orchestrator_task_links")
        op.drop_table("orchestrator_task_links")
