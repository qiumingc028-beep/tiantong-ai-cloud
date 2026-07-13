"""V2 alpha workflow knowledge asset identity repair

Revision ID: 0043_v2_alpha_workflow_knowledge_asset_identity_repair
Revises: 0042_v2_alpha_workflow_unique_constraints
Create Date: 2026-07-13 17:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0043_v2_alpha_workflow_knowledge_asset_identity_repair"
down_revision = "0042_v2_alpha_workflow_unique_constraints"
branch_labels = None
depends_on = None


_UNIQUE_NAME = "uq_alpha_workflow_runs_knowledge_asset_id"
_NON_UNIQUE_NAME = "ix_alpha_workflow_runs_knowledge_asset_id"


def _has_unique_constraint() -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(item["name"] == _UNIQUE_NAME for item in inspector.get_unique_constraints("alpha_workflow_runs"))


def _has_index(index_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(item["name"] == index_name for item in inspector.get_indexes("alpha_workflow_runs"))


def upgrade():
    if op.get_bind().dialect.name == "sqlite":
        return

    if _has_unique_constraint():
        op.drop_constraint(_UNIQUE_NAME, "alpha_workflow_runs", type_="unique")
    if _has_index(_UNIQUE_NAME):
        op.drop_index(_UNIQUE_NAME, table_name="alpha_workflow_runs")
    if not _has_index(_NON_UNIQUE_NAME):
        op.create_index(_NON_UNIQUE_NAME, "alpha_workflow_runs", ["knowledge_asset_id"], unique=False)


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        return

    if _has_index(_NON_UNIQUE_NAME):
        op.drop_index(_NON_UNIQUE_NAME, table_name="alpha_workflow_runs")
    if not _has_index(_UNIQUE_NAME):
        op.create_index(_UNIQUE_NAME, "alpha_workflow_runs", ["knowledge_asset_id"], unique=True)
