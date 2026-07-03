"""orchestrator mvp tables

Revision ID: 0010_orchestrator_tables
Revises: 0009_deploy_center_tables
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa


revision = "0010_orchestrator_tables"
down_revision = "0009_deploy_center_tables"
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
    if not _has_table("orchestrator_analysis_records"):
        op.create_table(
            "orchestrator_analysis_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("input_excerpt", sa.Text(), nullable=False),
            sa.Column("input_hash", sa.String(64), nullable=False),
            sa.Column("detected_employee_code", sa.String(100)),
            sa.Column("detected_employee_name", sa.String(100)),
            sa.Column("detected_sprint", sa.String(100)),
            sa.Column("detected_stage", sa.String(50)),
            sa.Column("completion_status", sa.String(50)),
            sa.Column("has_blocker", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("needs_fix", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("confidence", sa.String(50)),
            sa.Column("recommended_codex", sa.String(100)),
            sa.Column("recommended_action", sa.Text()),
            sa.Column("prompt_draft", sa.Text()),
            sa.Column("safety_flags_json", sa.Text()),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_orchestrator_analysis_records_input_hash", "orchestrator_analysis_records", ["input_hash"])
    _create_index_if_missing("ix_orchestrator_analysis_records_employee_code", "orchestrator_analysis_records", ["detected_employee_code"])
    _create_index_if_missing("ix_orchestrator_analysis_records_sprint", "orchestrator_analysis_records", ["detected_sprint"])
    _create_index_if_missing("ix_orchestrator_analysis_records_stage", "orchestrator_analysis_records", ["detected_stage"])
    _create_index_if_missing("ix_orchestrator_analysis_records_completion", "orchestrator_analysis_records", ["completion_status"])
    _create_index_if_missing("ix_orchestrator_analysis_records_recommended_codex", "orchestrator_analysis_records", ["recommended_codex"])

    if not _has_table("orchestrator_prompt_confirmations"):
        op.create_table(
            "orchestrator_prompt_confirmations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "analysis_record_id",
                sa.Integer(),
                sa.ForeignKey("orchestrator_analysis_records.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("confirmed_prompt", sa.Text(), nullable=False),
            sa.Column("target_codex", sa.String(100), nullable=False),
            sa.Column("confirm_status", sa.String(50), nullable=False),
            sa.Column("confirmed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("note", sa.Text()),
        )
    _create_index_if_missing("ix_orchestrator_prompt_confirmations_analysis_record_id", "orchestrator_prompt_confirmations", ["analysis_record_id"])
    _create_index_if_missing("ix_orchestrator_prompt_confirmations_target_codex", "orchestrator_prompt_confirmations", ["target_codex"])


def downgrade():
    if _has_table("orchestrator_prompt_confirmations"):
        if _has_index("orchestrator_prompt_confirmations", "ix_orchestrator_prompt_confirmations_target_codex"):
            op.drop_index("ix_orchestrator_prompt_confirmations_target_codex", table_name="orchestrator_prompt_confirmations")
        if _has_index("orchestrator_prompt_confirmations", "ix_orchestrator_prompt_confirmations_analysis_record_id"):
            op.drop_index("ix_orchestrator_prompt_confirmations_analysis_record_id", table_name="orchestrator_prompt_confirmations")
        op.drop_table("orchestrator_prompt_confirmations")

    if _has_table("orchestrator_analysis_records"):
        for index_name in (
            "ix_orchestrator_analysis_records_recommended_codex",
            "ix_orchestrator_analysis_records_completion",
            "ix_orchestrator_analysis_records_stage",
            "ix_orchestrator_analysis_records_sprint",
            "ix_orchestrator_analysis_records_employee_code",
            "ix_orchestrator_analysis_records_input_hash",
        ):
            if _has_index("orchestrator_analysis_records", index_name):
                op.drop_index(index_name, table_name="orchestrator_analysis_records")
        op.drop_table("orchestrator_analysis_records")
