"""Enforce JD product and advertising business keys.

Revision ID: 0054_r297_jd_business_uniqueness
Revises: 0053_r297_jd_workbench_hash_uniqueness
"""

from alembic import op
import sqlalchemy as sa


revision = "0054_r297_jd_business_uniqueness"
down_revision = "0053_r297_jd_workbench_hash_uniqueness"
branch_labels = None
depends_on = None


_BUSINESS_KEYS = (
    (
        "jd_products",
        ("store_id", "stat_date", "sku_id"),
        "uq_jd_products_store_date_sku",
        "R297_DUPLICATE_PRODUCT_BUSINESS_KEY",
        "sku_id",
        "ck_jd_products_sku_id_not_blank",
        "R297_INCOMPLETE_PRODUCT_BUSINESS_KEY",
    ),
    (
        "jd_ads",
        ("store_id", "stat_date", "campaign_id"),
        "uq_jd_ads_store_date_campaign",
        "R297_DUPLICATE_AD_BUSINESS_KEY",
        "campaign_id",
        "ck_jd_ads_campaign_id_not_blank",
        "R297_INCOMPLETE_AD_BUSINESS_KEY",
    ),
)


def _reject_duplicate_history(table: str, columns: tuple[str, ...], error: str) -> None:
    key = ", ".join(columns)
    op.execute(sa.text(f"""
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM {table}
            GROUP BY {key} HAVING COUNT(*) > 1
          ) THEN
            RAISE EXCEPTION '{error}';
          END IF;
        END $$;
    """))


def upgrade():
    op.execute(sa.text("LOCK TABLE jd_products, jd_ads IN ACCESS EXCLUSIVE MODE"))
    for table, columns, constraint, error, identity, check_constraint, incomplete_error in _BUSINESS_KEYS:
        op.execute(sa.text(f"""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM {table} WHERE {identity} IS NULL OR btrim({identity}) = '') THEN
                RAISE EXCEPTION '{incomplete_error}';
              END IF;
            END $$;
        """))
        _reject_duplicate_history(table, columns, error)
        op.create_unique_constraint(constraint, table, list(columns))
        op.create_check_constraint(check_constraint, table, f"length(trim({identity})) > 0")
    op.alter_column("jd_ads", "campaign_id", existing_type=sa.String(100), nullable=False)


def downgrade():
    op.alter_column("jd_ads", "campaign_id", existing_type=sa.String(100), nullable=True)
    for table, _columns, constraint, _error, _identity, check_constraint, _incomplete_error in reversed(_BUSINESS_KEYS):
        op.drop_constraint(check_constraint, table, type_="check")
        op.drop_constraint(constraint, table, type_="unique")
