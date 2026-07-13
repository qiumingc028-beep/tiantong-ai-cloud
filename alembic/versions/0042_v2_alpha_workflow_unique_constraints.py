"""V2 alpha workflow unique constraint repair

Revision ID: 0042_v2_alpha_workflow_unique_constraints
Revises: 0041_v2_alpha_migration_history_repair
Create Date: 2026-07-13 16:40:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0042_v2_alpha_workflow_unique_constraints"
down_revision = "0041_v2_alpha_migration_history_repair"
branch_labels = None
depends_on = None


_UNIQUE_COLUMNS = [
    ("uq_alpha_workflow_runs_root_span_id", "root_span_id"),
    ("uq_alpha_workflow_runs_workflow_id", "workflow_id"),
    ("uq_alpha_workflow_runs_orchestrator_run_id", "orchestrator_run_id"),
    ("uq_alpha_workflow_runs_research_report_id", "research_report_id"),
    ("uq_alpha_workflow_runs_skill_invocation_id", "skill_invocation_id"),
]


def _duplicates_for(column_name: str) -> list[dict[str, object]]:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            f'''
            SELECT "{column_name}" AS value, COUNT(*) AS count
            FROM alpha_workflow_runs
            WHERE "{column_name}" IS NOT NULL
            GROUP BY "{column_name}"
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) DESC, "{column_name}"
            LIMIT 5
            '''
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def _unique_constraint_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {item["name"] for item in inspector.get_unique_constraints("alpha_workflow_runs")}


def _index_names() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {item["name"] for item in inspector.get_indexes("alpha_workflow_runs")}


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    unique_constraints = _unique_constraint_names()
    index_names = _index_names()

    for constraint_name, column_name in _UNIQUE_COLUMNS:
        duplicates = _duplicates_for(column_name)
        if duplicates:
            raise RuntimeError(
                f'alpha_workflow_runs.{column_name} 存在重复值，无法安全创建唯一约束: {duplicates}'
            )

        if constraint_name in unique_constraints:
            continue

        if constraint_name in index_names:
            op.execute(
                sa.text(
                    f'ALTER TABLE "alpha_workflow_runs" '
                    f'ADD CONSTRAINT "{constraint_name}" UNIQUE USING INDEX "{constraint_name}"'
                )
            )
            continue

        op.create_unique_constraint(constraint_name, "alpha_workflow_runs", [column_name])


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    unique_constraints = _unique_constraint_names()

    for constraint_name, column_name in reversed(_UNIQUE_COLUMNS):
        if constraint_name in unique_constraints:
            op.drop_constraint(constraint_name, "alpha_workflow_runs", type_="unique")
        op.create_index(constraint_name, "alpha_workflow_runs", [column_name], unique=True)
