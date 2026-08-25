"""V2 alpha workflow unique constraint repair

Revision ID: 0042_v2_alpha_workflow_unique_constraints
Revises: 0041_v2_alpha_migration_history_repair
Create Date: 2026-07-13 16:40:00.000000
"""

from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa


revision = "0042_v2_alpha_workflow_unique_constraints"
down_revision = "0041_v2_alpha_migration_history_repair"
branch_labels = None
depends_on = None

_KNOWLEDGE_ASSET_UNIQUE_NAME = "uq_alpha_workflow_runs_knowledge_asset_id"
_KNOWLEDGE_ASSET_INDEX_NAME = "ix_alpha_workflow_runs_knowledge_asset_id"


_UNIQUE_COLUMNS = [
    ("uq_alpha_workflow_runs_root_span_id", "root_span_id"),
    ("uq_alpha_workflow_runs_workflow_id", "workflow_id"),
    ("uq_alpha_workflow_runs_orchestrator_run_id", "orchestrator_run_id"),
    ("uq_alpha_workflow_runs_research_report_id", "research_report_id"),
    ("uq_alpha_workflow_runs_skill_invocation_id", "skill_invocation_id"),
]


def _offline_upgrade() -> None:
    """Emit PostgreSQL guards that are evaluated when the SQL is applied."""
    op.execute(
        sa.text(
            f'''
            DO $migration$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conrelid = CAST('alpha_workflow_runs' AS regclass)
                      AND conname = '{_KNOWLEDGE_ASSET_UNIQUE_NAME}'
                      AND contype = 'u'
                ) THEN
                    ALTER TABLE "alpha_workflow_runs"
                    DROP CONSTRAINT "{_KNOWLEDGE_ASSET_UNIQUE_NAME}";
                ELSIF EXISTS (
                    SELECT 1
                    FROM pg_class idx
                    JOIN pg_index pi ON pi.indexrelid = idx.oid
                    WHERE pi.indrelid = CAST('alpha_workflow_runs' AS regclass)
                      AND idx.relname = '{_KNOWLEDGE_ASSET_UNIQUE_NAME}'
                ) THEN
                    DROP INDEX "{_KNOWLEDGE_ASSET_UNIQUE_NAME}";
                END IF;

                IF EXISTS (
                    SELECT 1
                    FROM pg_class idx
                    JOIN pg_index pi ON pi.indexrelid = idx.oid
                    WHERE pi.indrelid = CAST('alpha_workflow_runs' AS regclass)
                      AND idx.relname = '{_KNOWLEDGE_ASSET_INDEX_NAME}'
                      AND pi.indisunique
                ) THEN
                    DROP INDEX "{_KNOWLEDGE_ASSET_INDEX_NAME}";
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_class idx
                    JOIN pg_index pi ON pi.indexrelid = idx.oid
                    WHERE pi.indrelid = CAST('alpha_workflow_runs' AS regclass)
                      AND idx.relname = '{_KNOWLEDGE_ASSET_INDEX_NAME}'
                ) THEN
                    CREATE INDEX "{_KNOWLEDGE_ASSET_INDEX_NAME}"
                    ON "alpha_workflow_runs" ("knowledge_asset_id");
                END IF;
            END
            $migration$
            '''
        )
    )

    for constraint_name, column_name in _UNIQUE_COLUMNS:
        op.execute(
            sa.text(
                f'''
                DO $migration$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM "alpha_workflow_runs"
                        WHERE "{column_name}" IS NOT NULL
                        GROUP BY "{column_name}"
                        HAVING COUNT(*) > 1
                    ) THEN
                        RAISE EXCEPTION
                            'alpha_workflow_runs.{column_name} 存在重复值，无法安全创建唯一约束';
                    END IF;

                    IF EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conrelid = CAST('alpha_workflow_runs' AS regclass)
                          AND conname = '{constraint_name}'
                          AND contype = 'u'
                    ) THEN
                        NULL;
                    ELSIF EXISTS (
                        SELECT 1
                        FROM pg_class idx
                        JOIN pg_index pi ON pi.indexrelid = idx.oid
                        WHERE pi.indrelid = CAST('alpha_workflow_runs' AS regclass)
                          AND idx.relname = '{constraint_name}'
                          AND pi.indisunique
                          AND pi.indisvalid
                    ) THEN
                        ALTER TABLE "alpha_workflow_runs"
                        ADD CONSTRAINT "{constraint_name}"
                        UNIQUE USING INDEX "{constraint_name}";
                    ELSIF EXISTS (
                        SELECT 1
                        FROM pg_class idx
                        JOIN pg_index pi ON pi.indexrelid = idx.oid
                        WHERE pi.indrelid = CAST('alpha_workflow_runs' AS regclass)
                          AND idx.relname = '{constraint_name}'
                    ) THEN
                        DROP INDEX "{constraint_name}";
                        ALTER TABLE "alpha_workflow_runs"
                        ADD CONSTRAINT "{constraint_name}" UNIQUE ("{column_name}");
                    ELSE
                        ALTER TABLE "alpha_workflow_runs"
                        ADD CONSTRAINT "{constraint_name}" UNIQUE ("{column_name}");
                    END IF;
                END
                $migration$
                '''
            )
        )


def _offline_downgrade() -> None:
    for constraint_name, column_name in reversed(_UNIQUE_COLUMNS):
        op.execute(
            sa.text(
                f'''
                DO $migration$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conrelid = CAST('alpha_workflow_runs' AS regclass)
                          AND conname = '{constraint_name}'
                          AND contype = 'u'
                    ) THEN
                        ALTER TABLE "alpha_workflow_runs"
                        DROP CONSTRAINT "{constraint_name}";
                    END IF;

                    IF EXISTS (
                        SELECT 1
                        FROM pg_class idx
                        JOIN pg_index pi ON pi.indexrelid = idx.oid
                        WHERE pi.indrelid = CAST('alpha_workflow_runs' AS regclass)
                          AND idx.relname = '{constraint_name}'
                          AND NOT pi.indisunique
                    ) THEN
                        DROP INDEX "{constraint_name}";
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_class idx
                        JOIN pg_index pi ON pi.indexrelid = idx.oid
                        WHERE pi.indrelid = CAST('alpha_workflow_runs' AS regclass)
                          AND idx.relname = '{constraint_name}'
                    ) THEN
                        CREATE UNIQUE INDEX "{constraint_name}"
                        ON "alpha_workflow_runs" ("{column_name}");
                    END IF;
                END
                $migration$
                '''
            )
        )


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


def _reconcile_knowledge_asset_identity() -> None:
    unique_constraints = _unique_constraint_names()
    index_names = _index_names()

    if _KNOWLEDGE_ASSET_UNIQUE_NAME in unique_constraints:
        op.drop_constraint(_KNOWLEDGE_ASSET_UNIQUE_NAME, "alpha_workflow_runs", type_="unique")
        unique_constraints.discard(_KNOWLEDGE_ASSET_UNIQUE_NAME)
        index_names.discard(_KNOWLEDGE_ASSET_UNIQUE_NAME)
    elif _KNOWLEDGE_ASSET_UNIQUE_NAME in index_names:
        op.drop_index(_KNOWLEDGE_ASSET_UNIQUE_NAME, table_name="alpha_workflow_runs")
        index_names.discard(_KNOWLEDGE_ASSET_UNIQUE_NAME)

    if _KNOWLEDGE_ASSET_INDEX_NAME not in index_names:
        op.create_index(_KNOWLEDGE_ASSET_INDEX_NAME, "alpha_workflow_runs", ["knowledge_asset_id"], unique=False)


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    if context.is_offline_mode():
        _offline_upgrade()
        return

    _reconcile_knowledge_asset_identity()

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

    if context.is_offline_mode():
        _offline_downgrade()
        return

    unique_constraints = _unique_constraint_names()

    for constraint_name, column_name in reversed(_UNIQUE_COLUMNS):
        if constraint_name in unique_constraints:
            op.drop_constraint(constraint_name, "alpha_workflow_runs", type_="unique")
        op.create_index(constraint_name, "alpha_workflow_runs", [column_name], unique=True)
