"""Collector contract checks; Runtime responses are controlled, not real JD evidence."""
import json
import threading
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models import Company, JdAccount, JdAd, JdDailyMetric, JdOrder, JdProduct, Store, Tenant
from backend.services import jd_collectors as collectors


DATASETS = {
    "metrics": ("jd_smart", collectors.sync_jd_smart, JdDailyMetric, {"gmv": "1.00"}),
    "orders": ("jd_smart", collectors.sync_jd_orders, JdOrder, {"order_no": "order-1", "paid_amount": 1}),
    "products": ("jd_smart", collectors.sync_jd_products, JdProduct, {"sku_id": "sku-1", "stock_quantity": 1}),
    "ads": ("jzt", collectors.sync_jzt, JdAd, {"campaign_id": "campaign-1", "clicks": 1}),
}


def configure_capture(session, monkeypatch, dataset, rows, **envelope):
    account_type, sync, model, _ = DATASETS[dataset]
    store = session.query(Store).first()
    session.add(JdAccount(store_id=store.id, account_type=account_type, account_name=dataset, active=True))
    session.commit()
    monkeypatch.setenv("JD_BROWSER_CAPTURE_TOKEN", "test-capture-token-at-least-32-bytes")
    monkeypatch.setenv("JD_SESSION_NAMESPACE", "dataset-test")

    class Response:
        def read(self, size=-1):
            return json.dumps({"status": "OK", "data": {
                "store_id": str(store.id), "source": "jd_cloud_playwright",
                "captured_at": "2026-09-06T00:00:00Z", dataset: rows, **envelope,
            }}).encode()[:size]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(collectors, "urlopen", lambda *_args, **_kwargs: Response())
    return store.id, sync, model


@pytest.mark.parametrize("dataset", DATASETS)
@pytest.mark.parametrize("mutation", ("unknown_field", "bool", "nan", "wrong_type"))
def test_invalid_dataset_rejects_entire_batch_before_any_write(test_db, monkeypatch, dataset, mutation):
    row = dict(DATASETS[dataset][3])
    field = {"metrics": "gmv", "orders": "paid_amount", "products": "stock_quantity", "ads": "clicks"}[dataset]
    if mutation == "unknown_field":
        row["unexpected"] = "forbidden"
    else:
        row[field] = {"bool": True, "nan": "NaN", "wrong_type": []}[mutation]
    captured = row if dataset == "metrics" else [dict(DATASETS[dataset][3]), row]
    session = test_db()
    try:
        store_id, sync, model = configure_capture(session, monkeypatch, dataset, captured)
        with pytest.raises(collectors.JdCollectorError):
            sync(session, store_id, date(2026, 9, 6))
        # A caller committing after rejection must still have no partial write.
        session.commit()
        assert session.query(model).count() == 0
    finally:
        session.close()


@pytest.mark.parametrize("dataset", DATASETS)
def test_replay_updates_existing_record_and_counts_unique_saved_rows(test_db, monkeypatch, dataset):
    row = dict(DATASETS[dataset][3])
    captured = row if dataset == "metrics" else [row, row]
    session = test_db()
    try:
        store_id, sync, model = configure_capture(session, monkeypatch, dataset, captured)
        assert sync(session, store_id, date(2026, 9, 6)) == {"saved": 1}
        original_id = session.query(model).one().id
        field = {"metrics": "gmv", "orders": "paid_amount", "products": "stock_quantity", "ads": "clicks"}[dataset]
        row[field] = 2
        assert sync(session, store_id, date(2026, 9, 6)) == {"saved": 1}
        session.expire_all()
        saved = session.query(model).one()
        assert saved.id == original_id
        assert getattr(saved, field) == 2
    finally:
        session.close()


@pytest.mark.parametrize("dataset", DATASETS)
def test_concurrent_dataset_replay_is_atomic(postgres_database_factory, monkeypatch, dataset):
    from tests.conftest import _alembic

    url = postgres_database_factory(f"dataset_{dataset}")
    _alembic(url, "upgrade", "head")
    engine = create_engine(url)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as db:
        tenant = Tenant(tenant_code="dataset", tenant_name="dataset")
        db.add(tenant)
        db.flush()
        company = Company(tenant_id=tenant.id, company_code="dataset", company_name="dataset")
        db.add(company)
        db.flush()
        db.add(Store(tenant_id=tenant.id, company_id=company.id, platform="jd", store_code="dataset", store_name="dataset"))
        db.commit()
        row = dict(DATASETS[dataset][3])
        captured = row if dataset == "metrics" else [row]
        store_id, sync, model = configure_capture(db, monkeypatch, dataset, captured)

    barrier = threading.Barrier(2)
    errors, results = [], []
    # Pause both transactions after fetching so both contend on the same key.
    original = collectors.urlopen

    def capture(*args, **kwargs):
        barrier.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(collectors, "urlopen", capture)

    def write():
        with sessions() as db:
            try:
                results.append(sync(db, store_id, date(2026, 9, 6)))
            except Exception as exc:
                errors.append(type(exc).__name__)
                db.rollback()

    threads = [threading.Thread(target=write) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert results == [{"saved": 1}, {"saved": 1}]
    with sessions() as db:
        assert db.query(model).count() == 1
    engine.dispose()


def test_cross_store_order_collision_rolls_back_the_entire_batch(test_db, monkeypatch):
    with test_db() as db:
        store = db.query(Store).first()
        other = Store(tenant_id=store.tenant_id, company_id=store.company_id, platform="jd",
                      store_code="other-order-store", store_name="other")
        db.add(other)
        db.flush()
        db.add(JdOrder(store_id=other.id, order_no="protected", order_date=date(2026, 9, 6), paid_amount=99))
        db.commit()
        store_id, sync, _ = configure_capture(db, monkeypatch, "orders", [
            {"order_no": "new-order", "paid_amount": 1},
            {"order_no": "protected", "paid_amount": 2},
        ])
        with pytest.raises(collectors.JdCollectorError):
            sync(db, store_id, date(2026, 9, 6))
        db.commit()
        order = db.query(JdOrder).one()
        assert (order.store_id, order.order_no, order.paid_amount) == (other.id, "protected", 99)


@pytest.mark.parametrize("envelope", (
    {"captured_at": None}, {"captured_at": "2026-09-06T00:00:00"},
    {"captured_at": "invalid"}, {"unexpected": "forbidden"},
))
def test_invalid_capture_envelope_is_zero_write(test_db, monkeypatch, envelope):
    with test_db() as db:
        store_id, sync, model = configure_capture(db, monkeypatch, "metrics", {"gmv": "1.00"}, **envelope)
        with pytest.raises(collectors.JdCollectorError):
            sync(db, store_id)
        db.commit()
        assert db.query(model).count() == 0
