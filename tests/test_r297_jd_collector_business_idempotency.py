from datetime import date, timedelta
import threading

import pytest
from tests.test_r297_dataset_required_fields import complete_row
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Company, JdAccount, JdAd, JdProduct, Store, Tenant
from backend.services import jd_collectors
from backend.services.jd_collectors import JdCollectorError


def _account(session, account_type: str) -> JdAccount:
    store = session.query(Store).first()
    account = JdAccount(
        store_id=store.id,
        account_type=account_type,
        account_name=f"R297 {account_type}",
        active=True,
    )
    session.add(account)
    session.commit()
    return account


def test_product_replay_updates_one_business_row(test_db, monkeypatch):
    session = test_db()
    account = _account(session, "jd_smart")
    rows = [complete_row("products", sku_id="sku-1", product_name="first", stock_quantity=1)]
    monkeypatch.setattr(jd_collectors.JdSmartCollector, "fetch_products_today", lambda *_args: rows)

    jd_collectors.sync_jd_products(session, account.store_id, date(2026, 9, 6))
    first_synced_at = session.query(JdProduct).one().synced_at
    original_datetime = jd_collectors.datetime

    class LaterDateTime(original_datetime):
        @classmethod
        def now(cls, tz=None):
            return original_datetime.now(tz) + timedelta(days=1)

    monkeypatch.setattr(jd_collectors, "datetime", LaterDateTime)
    rows[0] = complete_row("products", sku_id="sku-1", product_name="updated", stock_quantity=2)
    jd_collectors.sync_jd_products(session, account.store_id, date(2026, 9, 6))

    products = session.query(JdProduct).all()
    assert len(products) == 1
    assert (products[0].product_name, products[0].stock_quantity) == ("updated", 2)
    assert products[0].synced_at > first_synced_at
    session.close()


def test_ad_replay_updates_one_business_row(test_db, monkeypatch):
    session = test_db()
    account = _account(session, "jzt")
    rows = [complete_row("ads", campaign_id="campaign-1", campaign_name="first", clicks=1)]
    monkeypatch.setattr(jd_collectors.JztCollector, "fetch_ads_today", lambda *_args: rows)

    jd_collectors.sync_jzt(session, account.store_id, date(2026, 9, 6))
    first_synced_at = session.query(JdAd).one().synced_at
    original_datetime = jd_collectors.datetime

    class LaterDateTime(original_datetime):
        @classmethod
        def now(cls, tz=None):
            return original_datetime.now(tz) + timedelta(days=1)

    monkeypatch.setattr(jd_collectors, "datetime", LaterDateTime)
    rows[0] = complete_row("ads", campaign_id="campaign-1", campaign_name="updated", clicks=2)
    jd_collectors.sync_jzt(session, account.store_id, date(2026, 9, 6))

    ads = session.query(JdAd).all()
    assert len(ads) == 1
    assert (ads[0].campaign_name, ads[0].clicks) == ("updated", 2)
    assert ads[0].synced_at > first_synced_at
    session.close()


@pytest.mark.parametrize("target", ("product", "ad"))
def test_duplicate_business_key_in_one_collection_batch_is_idempotent(test_db, monkeypatch, target):
    session = test_db()
    account_type = "jd_smart" if target == "product" else "jzt"
    account = _account(session, account_type)
    key = "sku_id" if target == "product" else "campaign_id"
    value_key = "stock_quantity" if target == "product" else "clicks"
    dataset = "products" if target == "product" else "ads"
    rows = [complete_row(dataset, **{key: "same-key", value_key: 1}), complete_row(dataset, **{key: "same-key", value_key: 2})]
    if target == "product":
        monkeypatch.setattr(jd_collectors.JdSmartCollector, "fetch_products_today", lambda *_args: rows)
        call = jd_collectors.sync_jd_products
        model = JdProduct
    else:
        monkeypatch.setattr(jd_collectors.JztCollector, "fetch_ads_today", lambda *_args: rows)
        call = jd_collectors.sync_jzt
        model = JdAd

    call(session, account.store_id, date(2026, 9, 6))

    assert session.query(model).count() == 1
    session.close()


@pytest.mark.parametrize(
    ("account_type", "collector", "rows"),
    (
        ("jd_smart", "product", [{"sku_id": "", "product_name": "missing"}]),
        ("jd_smart", "product", [{"sku_id": None, "product_name": "missing"}]),
        ("jzt", "ad", [{"campaign_id": "", "campaign_name": "missing"}]),
        ("jzt", "ad", [{"campaign_id": None, "campaign_name": "missing"}]),
    ),
)
def test_collection_rejects_empty_business_key(test_db, monkeypatch, account_type, collector, rows):
    session = test_db()
    account = _account(session, account_type)
    if collector == "product":
        monkeypatch.setattr(jd_collectors.JdSmartCollector, "fetch_products_today", lambda *_args: rows)
        call = jd_collectors.sync_jd_products
    else:
        monkeypatch.setattr(jd_collectors.JztCollector, "fetch_ads_today", lambda *_args: rows)
        call = jd_collectors.sync_jzt

    with pytest.raises(JdCollectorError, match="缺少"):
        call(session, account.store_id, date(2026, 9, 6))
    session.rollback()
    assert session.query(JdProduct if collector == "product" else JdAd).count() == 0
    session.close()


@pytest.mark.parametrize("target", ("product", "ad"))
def test_concurrent_business_key_replay_is_atomic(postgres_database_factory, target):
    from tests.conftest import _alembic

    database_url = postgres_database_factory(f"r297_collector_upsert_{target}")
    assert _alembic(database_url, "upgrade", "head").returncode == 0
    engine = create_engine(database_url)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = sessions()
    tenant = Tenant(tenant_code=f"UP-{target}", tenant_name="upsert")
    db.add(tenant)
    db.flush()
    company = Company(tenant_id=tenant.id, company_code=f"UP-{target}", company_name="upsert")
    db.add(company)
    db.flush()
    store = Store(
        tenant_id=tenant.id,
        company_id=company.id,
        platform="jd",
        store_code=f"UP-{target}",
        store_name="upsert",
        active=True,
    )
    db.add(store)
    db.commit()
    store_id = store.id
    db.close()

    barrier = threading.Barrier(2)
    errors = []

    def write(label: str):
        session = sessions()
        try:
            barrier.wait(timeout=5)
            if target == "product":
                jd_collectors.save_product(session, store_id, complete_row("products", **{
                    "sku_id": "sku-concurrent",
                    "stat_date": "2026-09-06",
                    "product_name": label,
                }))
            else:
                jd_collectors.save_ad(session, store_id, None, date(2026, 9, 6), complete_row("ads", **{
                    "campaign_id": "campaign-concurrent",
                    "campaign_name": label,
                }))
            session.commit()
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)
            session.rollback()
        finally:
            session.close()

    threads = [threading.Thread(target=write, args=(label,)) for label in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    db = sessions()
    assert db.query(JdProduct if target == "product" else JdAd).count() == 1
    db.close()
    engine.dispose()
