from __future__ import annotations

import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


FINAL_REVISION = "0054_r297_jd_business_uniqueness"


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _seed_store(connection) -> int:
    tenant_id = connection.execute(text(
        "INSERT INTO tenants (tenant_code, tenant_name, active) "
        "VALUES ('r297-business-key', 'R297 business key', true) RETURNING id"
    )).scalar_one()
    company_id = connection.execute(text(
        "INSERT INTO companies (tenant_id, company_code, company_name, active) "
        "VALUES (:tenant, 'r297-business-key', 'R297 business key', true) RETURNING id"
    ), {"tenant": tenant_id}).scalar_one()
    return connection.execute(text(
        "INSERT INTO stores (tenant_id, company_id, platform, store_code, store_name, active) "
        "VALUES (:tenant, :company, 'jd', 'r297-business-key', 'R297 business key', true) RETURNING id"
    ), {"tenant": tenant_id, "company": company_id}).scalar_one()


def _insert_product(connection, store_id: int, name: str = "one") -> None:
    connection.execute(text(
        "INSERT INTO jd_products "
        "(store_id, stat_date, sku_id, product_name, stock_quantity, sales_amount, sales_quantity, "
        "visitors_count, conversion_rate) VALUES "
        "(:store, DATE '2026-09-06', 'sku-1', :name, 0, 0, 0, 0, 0)"
    ), {"store": store_id, "name": name})


def _insert_ad(connection, store_id: int, name: str = "one") -> None:
    connection.execute(text(
        "INSERT INTO jd_ads "
        "(store_id, stat_date, campaign_id, campaign_name, ad_spend, clicks, impressions, roi, cpa, deal_amount) "
        "VALUES (:store, DATE '2026-09-06', 'campaign-1', :name, 0, 0, 0, 0, 0, 0)"
    ), {"store": store_id, "name": name})


def test_business_uniqueness_migration_roundtrip_and_postgresql_behavior(postgres_database_factory):
    database_url = postgres_database_factory("r297_business_unique")
    upgraded = _alembic(database_url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr[-2000:]
    checked = _alembic(database_url, "check")
    assert checked.returncode == 0, checked.stderr[-2000:]

    engine = create_engine(database_url)
    with engine.begin() as connection:
        inspector = inspect(connection)
        assert {item["name"] for item in inspector.get_unique_constraints("jd_products")} >= {
            "uq_jd_products_store_date_sku"
        }
        assert {item["name"] for item in inspector.get_unique_constraints("jd_ads")} >= {
            "uq_jd_ads_store_date_campaign"
        }
        assert {item["name"] for item in inspector.get_check_constraints("jd_products")} >= {
            "ck_jd_products_sku_id_not_blank"
        }
        assert {item["name"] for item in inspector.get_check_constraints("jd_ads")} >= {
            "ck_jd_ads_campaign_id_not_blank"
        }
        store_id = _seed_store(connection)
        _insert_product(connection, store_id)
        _insert_ad(connection, store_id)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_product(connection, store_id, "duplicate")
    with pytest.raises(IntegrityError), engine.begin() as connection:
        _insert_ad(connection, store_id, "duplicate")
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO jd_ads "
            "(store_id, stat_date, campaign_id, campaign_name, ad_spend, clicks, impressions, roi, cpa, deal_amount) "
            "VALUES (:store, DATE '2026-09-07', NULL, 'missing key', 0, 0, 0, 0, 0, 0)"
        ), {"store": store_id})

    downgraded = _alembic(database_url, "downgrade", "0053_r297_jd_workbench_hash_uniqueness")
    assert downgraded.returncode == 0, downgraded.stderr[-2000:]
    reupgraded = _alembic(database_url, "upgrade", "head")
    assert reupgraded.returncode == 0, reupgraded.stderr[-2000:]
    rechecked = _alembic(database_url, "check")
    assert rechecked.returncode == 0, rechecked.stderr[-2000:]
    current = _alembic(database_url, "current")
    assert current.returncode == 0 and FINAL_REVISION in current.stdout
    engine.dispose()


@pytest.mark.parametrize(
    ("target", "expected_error"),
    (
        ("product", "R297_DUPLICATE_PRODUCT_BUSINESS_KEY"),
        ("ad", "R297_DUPLICATE_AD_BUSINESS_KEY"),
    ),
)
def test_business_uniqueness_migration_rejects_historical_duplicates(
    postgres_database_factory, target, expected_error
):
    database_url = postgres_database_factory(f"r297_business_duplicate_{target}")
    assert _alembic(database_url, "upgrade", "0053_r297_jd_workbench_hash_uniqueness").returncode == 0
    engine = create_engine(database_url)
    with engine.begin() as connection:
        store_id = _seed_store(connection)
        insert = _insert_product if target == "product" else _insert_ad
        insert(connection, store_id, "one")
        insert(connection, store_id, "two")
    upgraded = _alembic(database_url, "upgrade", "head")
    assert upgraded.returncode != 0
    assert expected_error in upgraded.stderr
    engine.dispose()
