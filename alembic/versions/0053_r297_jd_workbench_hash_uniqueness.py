"""Normalize R297 pairing and device hash uniqueness.

Revision ID: 0053_r297_jd_workbench_hash_uniqueness
Revises: 0052_r297_postgresql_queue_authority
"""

from alembic import op
import sqlalchemy as sa


revision = "0053_r297_jd_workbench_hash_uniqueness"
down_revision = "0052_r297_postgresql_queue_authority"
branch_labels = None
depends_on = None


_HASH_KEYS = (
    (
        "jd_workbench_pairing_codes",
        "code_hash",
        "uq_jd_workbench_pairing_codes_code_hash",
        "jd_workbench_pairing_codes_code_hash_key",
        "R297_DUPLICATE_PAIRING_CODE_HASH",
    ),
    (
        "jd_workbench_devices",
        "token_hash",
        "uq_jd_workbench_devices_token_hash",
        "jd_workbench_devices_token_hash_key",
        "R297_DUPLICATE_DEVICE_TOKEN_HASH",
    ),
)


def _reject_duplicate_history(table: str, column: str, error: str) -> None:
    op.execute(sa.text(f"""
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM {table}
            WHERE {column} IS NOT NULL
            GROUP BY {column} HAVING COUNT(*) > 1
          ) THEN
            RAISE EXCEPTION '{error}';
          END IF;
        END $$;
    """))


def _rename_constraint(table: str, old_name: str, new_name: str) -> None:
    op.execute(sa.text(f'ALTER TABLE {table} RENAME CONSTRAINT "{old_name}" TO "{new_name}"'))


def upgrade():
    for table, column, constraint, legacy_constraint, error in _HASH_KEYS:
        op.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
        _reject_duplicate_history(table, column, error)
        names = {
            item["name"]
            for item in sa.inspect(op.get_bind()).get_unique_constraints(table)
            if item.get("name") and item.get("column_names") == [column]
        }
        unexpected = names - {constraint, legacy_constraint}
        if unexpected or len(names) != 1:
            raise RuntimeError(f"R297_UNEXPECTED_{column.upper()}_UNIQUENESS={sorted(names)}")
        if legacy_constraint in names:
            _rename_constraint(table, legacy_constraint, constraint)


def downgrade():
    for table, _column, constraint, legacy_constraint, _error in _HASH_KEYS:
        _rename_constraint(table, constraint, legacy_constraint)
