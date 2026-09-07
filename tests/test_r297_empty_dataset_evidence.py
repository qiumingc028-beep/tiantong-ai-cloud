from datetime import date

import pytest

from backend.models import JdAccount
from backend.services import jd_collectors as collectors
from tests.test_r297_dataset_validation import configure_capture


def proof(dataset):
    return {"dataset": dataset, "store_id": "1", "range_start": "2026-09-06", "range_end": "2026-09-06",
            "authenticated": True, "permission_granted": True, "empty_state": True,
            "total_count": 0, "pagination_complete": True, "source": "authenticated_network_response"}


@pytest.mark.parametrize("dataset", ("orders", "products", "ads"))
@pytest.mark.parametrize("mutation", ("missing", "authenticated", "permission_granted", "range_start", "range_end",
                                     "store_id", "dataset", "empty_state", "total_count", "pagination_complete"))
def test_unproven_empty_never_writes_rows_or_success_timestamp(test_db, monkeypatch, dataset, mutation):
    evidence = proof(dataset)
    if mutation == "missing":
        envelope = {}
    else:
        evidence[mutation] = {"authenticated": False, "permission_granted": False, "range_start": "2026-09-05",
                              "range_end": "2026-09-07", "store_id": "2", "dataset": "metrics", "empty_state": False,
                              "total_count": 1, "pagination_complete": False}[mutation]
        envelope = {"empty_evidence": evidence}
    with test_db() as db:
        store_id, sync, model = configure_capture(db, monkeypatch, dataset, [], **envelope)
        with pytest.raises(collectors.JdCollectorError):
            sync(db, store_id, date(2026, 9, 6))
        db.commit()
        assert db.query(model).count() == 0
        assert db.query(JdAccount).one().last_sync_at is None


@pytest.mark.parametrize("dataset", ("orders", "products", "ads"))
def test_verified_real_zero_range_is_a_legal_success(test_db, monkeypatch, dataset):
    with test_db() as db:
        store_id, sync, model = configure_capture(db, monkeypatch, dataset, [], empty_evidence=proof(dataset))
        assert sync(db, store_id, date(2026, 9, 6)) == {"saved": 0}
        assert db.query(model).count() == 0
        assert db.query(JdAccount).one().last_sync_at is not None


@pytest.mark.parametrize("dataset", ("orders", "products", "ads"))
def test_bare_empty_adapter_result_is_not_verified_evidence(dataset):
    with pytest.raises(collectors.JdCollectorError):
        collectors.validate_dataset(dataset, [])
