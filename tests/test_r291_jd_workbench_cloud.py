from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import time
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from backend.database import Base
from backend.config import get_settings
from backend.models import Permission, Role, Store, User, UserStoreMembership


CLIENT_VERSION = "2.91.0-test"
COLLECTED_AT = "2026-08-29T06:00:00Z"
SOURCE_PERIOD = "2026-08-28"
TEST_RSA_N_B64 = "qqJk2ZH4W5fP8Y2xulfKp_mafykFYNhou5UX35781QJTy5m3Md3fJfCjXEt1Jn1Qpvy9DjFHyjCrJSiOi50idZRhL6SdJvn66JzNS0SP9aXG-53oVGSnqwMedFE2ByxhI67IHI0ndIgnAtLudX2RU1J-vkPo2BjYztSkxXBX9aePJit_d58i6KkZ4Yd-KVQi8QjsNuzytXZNxymZj_TyGxLXFsySeVZhFNR7TySOWbylrziPNFil3DAPzEP7LcALArb6dUdfAxvHWrRmXd7uWqlciTEaTy7q37fNJyvcggS1FlfpGcrpRG_LuwNN58FSWt-_VBeVQf00emDZ60g0xQ"
TEST_RSA_D_B64 = "AYKWaeaE0CqzyGt8my2TuZDX8TAnwAeqRZ64K1541lnC7BZcLLDN_MP4biSs0L5jLFcoRSviesObgCSvvkSRvYCmq4lFasbjlZNtrbDZpU7mR-vJ1pVddoH8jwL4-29FHM-7LaWCJ-HcloXPXnLSCm68eGqZcPAnWw0-uBCadq4VOwZ_xPOpkaqGrvlJICwIyEkqr3lm--N7V-BoGw2SU4QvdTlB8HyjaqOVj_SPERvBiljcc5M3P2tyhlKpj5WVpzCBf08orKIk7BJpW58-hNgcC72HAeqncgubTjdlyM6pj2ssweL8t7iKdze3rnL6k-P7rtpUdd7kxZhkSRLSsQ"


def test_browser_runtime_control_scope_must_match_an_active_database_store(client, test_db, monkeypatch):
    token = "r" * 32
    monkeypatch.setenv("JD_BROWSER_CONTROL_TOKEN", token)
    get_settings.cache_clear()
    with test_db() as db:
        store = db.query(Store).filter(Store.store_code == "JD01").one()
    scope = {
        "tenant_id": store.tenant_id,
        "company_id": store.company_id,
        "store_id": store.id,
        "platform": store.platform,
    }
    try:
        assert client.post(
            "/api/jd-workbench/internal/browser-session-authorize",
            headers={"x-internal-token": token}, json=scope,
        ).status_code == 204
        assert client.post(
            "/api/jd-workbench/internal/browser-session-authorize",
            headers={"x-internal-token": token}, json={**scope, "store_id": store.id + 1000},
        ).status_code == 404
        assert client.post(
            "/api/jd-workbench/internal/browser-session-authorize",
            headers={"x-internal-token": "x" * 32}, json=scope,
        ).status_code == 401
    finally:
        get_settings.cache_clear()


def _base64url_bytes(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


TEST_RSA_N = int.from_bytes(_base64url_bytes(TEST_RSA_N_B64), "big")
TEST_RSA_D = int.from_bytes(_base64url_bytes(TEST_RSA_D_B64), "big")


def _opaque(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _create_pairing_code(client, owner_headers) -> str:
    response = client.post("/api/jd-workbench/pairing-codes", headers=owner_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("code")
    return payload["code"]


def _pair_device(client, owner_headers) -> tuple[str, str]:
    code = _create_pairing_code(client, owner_headers)
    client.cookies.clear()
    response = client.post(
        "/api/jd-workbench/pair",
        json={
            "code": code,
            "device_name": "R291 test workstation",
            "client_version": CLIENT_VERSION,
            "public_key": {"kty": "RSA", "n": TEST_RSA_N_B64, "e": "AQAB"},
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("device_token")
    return payload["device_token"], code


def _device_headers(device_token: str, method: str, path: str, body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    canonical = "\n".join(
        ("R291", timestamp, nonce, method.upper(), path, hashlib.sha256(body).hexdigest())
    ).encode("utf-8")
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(canonical).digest()
    padding_length = 256 - len(digest_info) - 3
    encoded = b"\x00\x01" + b"\xff" * padding_length + b"\x00" + digest_info
    signature = pow(int.from_bytes(encoded, "big"), TEST_RSA_D, TEST_RSA_N).to_bytes(256, "big")
    return {
        "Authorization": f"Device {device_token}",
        "X-R291-Timestamp": timestamp,
        "X-R291-Nonce": nonce,
        "X-R291-Signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"),
    }


def _device_request(client, method: str, path: str, device_token: str, payload: dict | None = None):
    body = b"" if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = _device_headers(device_token, method, path, body)
    if payload is not None:
        headers["Content-Type"] = "application/json"
    return client.request(method, path, headers=headers, content=body or None)


def _authorized_store(client, device_token: str) -> dict:
    response = _device_request(client, "GET", "/api/jd-workbench/stores", device_token)

    assert response.status_code == 200, response.text
    payload = response.json()
    stores = payload if isinstance(payload, list) else payload.get("stores")
    assert isinstance(stores, list) and stores
    assert all("store_id" in store and "subject_id" in store for store in stores)
    assert all(UUID(store["store_uuid"]).version == 5 for store in stores)
    assert all(store["partition"] == f"persist:jd-{store['store_uuid']}" for store in stores)
    return stores[0]


def _sync_payload(
    store: dict,
    *,
    dataset_type: str = "sales_daily",
    records: list[dict] | None = None,
    idempotency_key: str | None = None,
) -> dict:
    return {
        "store_id": store["store_id"],
        "subject_id": store["subject_id"],
        "dataset_type": dataset_type,
        "source_period": SOURCE_PERIOD,
        "collected_at": COLLECTED_AT,
        "idempotency_key": idempotency_key or f"r291-{uuid4()}",
        "client_version": CLIENT_VERSION,
        "records": records
        or [
            {
                "source_record_key": _opaque(f"sales:{SOURCE_PERIOD}"),
                "sales_amount": 123.45,
                "orders_count": 3,
            }
        ],
    }


def _assert_first_sync(response, expected_accepted: int) -> str:
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ok"] is True
    assert payload["duplicate"] is False
    assert payload["accepted"] == expected_accepted
    assert payload.get("batch_id")
    return payload["batch_id"]


def _assert_duplicate_sync(response, expected_batch_id: str) -> None:
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload == {
        "ok": True,
        "duplicate": True,
        "accepted": 0,
        "batch_id": expected_batch_id,
    }


def _assert_canary_absent(test_db, caplog, canary: str) -> None:
    with test_db() as db:
        for table in Base.metadata.sorted_tables:
            rows = db.execute(table.select()).all()
            assert canary not in repr(rows), f"sensitive canary persisted in {table.name}"

    # Resolve at assertion time so the test_db fixture's isolated Redis override
    # is observed instead of a module-import-time reference.
    from backend import database

    redis_client = database.get_redis()
    assert canary not in repr(getattr(redis_client, "values", {}))
    assert canary not in repr(getattr(redis_client, "lists", {}))
    assert canary not in caplog.text


def test_pairing_code_requires_jd_permission_and_is_single_use(
    client,
    owner_headers,
    viewer_headers,
):
    client.cookies.clear()
    assert client.post("/api/jd-workbench/pairing-codes").status_code == 401
    assert client.post(
        "/api/jd-workbench/pairing-codes",
        headers=viewer_headers,
    ).status_code == 403

    code = _create_pairing_code(client, owner_headers)
    client.cookies.clear()
    request = {
        "code": code,
        "device_name": "R291 one-time pairing test",
        "client_version": CLIENT_VERSION,
        "public_key": {"kty": "RSA", "n": TEST_RSA_N_B64, "e": "AQAB"},
    }
    first = client.post("/api/jd-workbench/pair", json=request)
    assert first.status_code == 200, first.text
    assert first.json().get("device_token")

    reused = client.post("/api/jd-workbench/pair", json=request)
    assert reused.status_code in {400, 409, 410}, reused.text
    assert not reused.json().get("device_token")


def test_device_auth_is_distinct_from_user_bearer_and_supports_heartbeat(
    client,
    owner_headers,
    test_db,
):
    device_token, _ = _pair_device(client, owner_headers)

    assert client.get("/api/jd-workbench/stores").status_code == 401
    assert client.get(
        "/api/jd-workbench/stores",
        headers={"Authorization": f"Bearer {device_token}"},
    ).status_code == 401
    assert client.get(
        "/api/jd-workbench/stores",
        headers={"Authorization": f"Device {device_token}"},
    ).status_code == 401
    signed_headers = _device_headers(device_token, "GET", "/api/jd-workbench/stores", b"")
    stores = client.get("/api/jd-workbench/stores", headers=signed_headers)
    assert stores.status_code == 200, stores.text
    assert client.get("/api/jd-workbench/stores", headers=signed_headers).status_code == 401

    heartbeat = _device_request(
        client,
        "POST",
        "/api/jd-workbench/heartbeat",
        device_token,
        {"client_version": CLIENT_VERSION, "status": "ONLINE"},
    )
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["ok"] is True

    with test_db() as db:
        owner_role = db.query(Role).filter(Role.code == "owner").one()
        ingest_permission = db.query(Permission).filter(Permission.code == "jd_workbench.ingest").one()
        owner_role.permissions.remove(ingest_permission)
        db.commit()
    assert _device_request(
        client, "GET", "/api/jd-workbench/stores", device_token
    ).status_code == 401


def test_device_sync_accepts_all_p0_datasets(client, owner_headers):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    datasets = {
        "sales_daily": {
            "source_record_key": _opaque(f"sales:{SOURCE_PERIOD}"),
            "sales_amount": 123.45,
            "orders_count": 3,
        },
        "orders": {
            "source_record_key": _opaque("orders:2026-08-28"),
            "order_count": 1,
            "paid_amount": 88.80,
        },
        "refunds": {
            "source_record_key": _opaque("refunds:2026-08-28"),
            "refund_order_count": 1,
            "refund_amount": 18.80,
        },
        "products": {
            "source_record_key": _opaque("product:JD-R291-SKU-001"),
            "sku_key": _opaque("sku:JD-R291-SKU-001"),
            "product_name": "R291 test product",
        },
        "inventory": {
            "source_record_key": _opaque("inventory:JD-R291-SKU-001"),
            "sku_key": _opaque("sku:JD-R291-SKU-001"),
            "stock_quantity": 12,
        },
        "promotion_costs": {
            "source_record_key": _opaque(f"promotion:jingzhuntong:{SOURCE_PERIOD}"),
            "channel": "jingzhuntong",
            "ad_spend": 20.00,
            "roi": 4.44,
        },
    }

    for dataset_type, record in datasets.items():
        payload = _sync_payload(
            store,
            dataset_type=dataset_type,
            records=[record],
            idempotency_key=f"r291-{dataset_type}-{uuid4()}",
        )
        response = _device_request(
            client,
            "POST",
            "/api/jd-workbench/sync",
            device_token,
            payload,
        )
        _assert_first_sync(response, 1)


def test_cloud_dashboard_uses_explicit_no_data_state_instead_of_mock_zeroes(
    client,
    owner_headers,
):
    response = client.get("/api/jd-workbench/dashboard", headers=owner_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["summary"]
    assert all(value is None for value in payload["summary"].values())
    assert payload["ready_stores"] == 0
    assert all(store["empty_message"] == "暂无数据" for store in payload["stores"])
    assert all(store["store_code"] for store in payload["stores"])


def test_cloud_dashboard_reports_only_accepted_normalized_values(client, owner_headers):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    payload = _sync_payload(store)
    _assert_first_sync(
        _device_request(
            client,
            "POST",
            "/api/jd-workbench/sync",
            device_token,
            payload,
        ),
        1,
    )

    response = client.get(
        f"/api/jd-workbench/dashboard?store_id={store['store_id']}",
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["source"] == "jd_workbench_readonly"
    assert result["summary"]["sales_amount"] == "123.45"
    assert result["summary"]["orders_count"] == 3
    assert result["summary"]["ad_spend"] is None
    assert result["stores"][0]["datasets"]["sales_daily"]["source"] == "jd_workbench_readonly"


def test_r295_page_metrics_sync_is_store_scoped_and_dashboard_uses_latest_batch(
    client,
    owner_headers,
):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    first = _sync_payload(
        store,
        dataset_type="operating_metrics",
        records=[
            {
                "source_record_key": _opaque("r295-page-snapshot-first"),
                "visitors": 304,
                "page_views": 583,
                "ad_spend": 345.70,
                "ad_ctr": 3.65,
            }
        ],
        idempotency_key=f"r295-operating-first-{uuid4()}",
    )
    _assert_first_sync(
        _device_request(client, "POST", "/api/jd-workbench/sync", device_token, first),
        1,
    )

    second = deepcopy(first)
    second["collected_at"] = "2026-08-29T06:05:00Z"
    second["idempotency_key"] = f"r295-operating-second-{uuid4()}"
    second["records"] = [
        {
            "source_record_key": _opaque("r295-page-snapshot-second"),
            "visitors": 310,
            "page_views": 600,
            "pending_shipments": 0,
            "ad_spend": 350.25,
        }
    ]
    _assert_first_sync(
        _device_request(client, "POST", "/api/jd-workbench/sync", device_token, second),
        1,
    )

    response = client.get(
        f"/api/jd-workbench/dashboard?store_id={store['store_id']}",
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    dataset = response.json()["stores"][0]["datasets"]["operating_metrics"]
    assert dataset["record_count"] == 1
    assert dataset["records"] == [
        {"ad_spend": "350.25", "page_views": 600, "pending_shipments": 0, "visitors": 310}
    ]
    assert response.json()["summary"]["ad_spend"] == "350.25"


def test_r296_dashboard_filters_periods_and_aggregates_operating_metrics(
    client,
    owner_headers,
):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    daily_records = [
        (
            "2026-08-29",
            "2026-08-29T06:00:00Z",
            {
                "source_record_key": _opaque("r296-operating-2026-08-29"),
                "visitors": 100,
                "page_views": 200,
                "sales_orders": 10,
                "pending_shipments": 4,
                "ad_spend": 100.00,
                "ad_impressions": 1000,
                "ad_clicks": 50,
            },
        ),
        (
            "2026-08-29",
            "2026-08-29T16:30:00Z",
            {
                "source_record_key": _opaque("r296-operating-2026-08-30"),
                "visitors": 200,
                "page_views": 400,
                "sales_orders": 20,
                "pending_shipments": 7,
                "ad_spend": 200.00,
                "ad_impressions": 2000,
                "ad_clicks": 100,
            },
        ),
    ]
    for source_period, collected_at, record in daily_records:
        payload = _sync_payload(
            store,
            dataset_type="operating_metrics",
            records=[record],
            idempotency_key=f"r296-{source_period}-{uuid4()}",
        )
        payload["source_period"] = source_period
        payload["collected_at"] = collected_at
        _assert_first_sync(
            _device_request(client, "POST", "/api/jd-workbench/sync", device_token, payload),
            1,
        )

    today = client.get(
        f"/api/jd-workbench/dashboard?store_id={store['store_id']}&period=today&anchor_date=2026-08-30",
        headers=owner_headers,
    )
    assert today.status_code == 200, today.text
    today_payload = today.json()
    assert today_payload["period_start"] == "2026-08-30"
    assert today_payload["period_end"] == "2026-08-30"
    assert today_payload["summary"]["visitors"] == 200
    assert today_payload["summary"]["page_views"] == 400
    assert today_payload["summary"]["ad_spend"] == "200.00"
    assert today_payload["summary"]["ad_ctr"] == "5.0000"
    assert today_payload["summary"]["ad_cpc"] == "2.00"

    yesterday = client.get(
        f"/api/jd-workbench/dashboard?store_id={store['store_id']}&period=yesterday&anchor_date=2026-08-30",
        headers=owner_headers,
    )
    assert yesterday.status_code == 200, yesterday.text
    assert yesterday.json()["summary"]["visitors"] == 100
    assert yesterday.json()["period_start"] == "2026-08-29"

    seven_days = client.get(
        f"/api/jd-workbench/dashboard?store_id={store['store_id']}&period=7d&anchor_date=2026-08-30",
        headers=owner_headers,
    )
    assert seven_days.status_code == 200, seven_days.text
    seven_payload = seven_days.json()
    assert seven_payload["period_start"] == "2026-08-24"
    assert seven_payload["period_end"] == "2026-08-30"
    assert seven_payload["summary"]["visitors"] == 300
    assert seven_payload["summary"]["page_views"] == 600
    assert seven_payload["summary"]["sales_orders"] == 30
    assert seven_payload["summary"]["pending_shipments"] == 7
    assert seven_payload["summary"]["ad_spend"] == "300.00"
    assert seven_payload["stores"][0]["datasets"]["operating_metrics"]["source_periods"] == [
        "2026-08-29",
        "2026-08-30",
    ]


def test_r296_dashboard_keeps_store_totals_isolated_and_supports_all_store_summary(
    client,
    owner_headers,
    test_db,
):
    with test_db() as db:
        owner = db.query(User).filter(User.username == "owner").one()
        second_store = Store(
            platform="jd",
            store_code="JD02",
            store_name="JD Store 02",
            tenant_id=owner.tenant_id,
            company_id=owner.company_id,
            active=True,
        )
        db.add(second_store)
        db.flush()
        db.add(
            UserStoreMembership(
                user_id=owner.id,
                store_id=second_store.id,
                can_read=True,
                can_write=True,
                active=True,
            )
        )
        db.commit()

    device_token, _ = _pair_device(client, owner_headers)
    stores_response = _device_request(client, "GET", "/api/jd-workbench/stores", device_token)
    assert stores_response.status_code == 200, stores_response.text
    stores = stores_response.json()
    assert len(stores) == 2
    for index, store in enumerate(stores, start=1):
        payload = _sync_payload(
            store,
            dataset_type="operating_metrics",
            records=[
                {
                    "source_record_key": _opaque(f"r296-store-{store['store_id']}"),
                    "visitors": index * 100,
                    "page_views": index * 200,
                    "ad_spend": index * 10,
                    "ad_impressions": index * 1000,
                    "ad_clicks": index * 50,
                }
            ],
            idempotency_key=f"r296-store-{store['store_id']}-{uuid4()}",
        )
        payload["source_period"] = "2026-08-30"
        payload["collected_at"] = "2026-08-30T08:00:00Z"
        _assert_first_sync(
            _device_request(client, "POST", "/api/jd-workbench/sync", device_token, payload),
            1,
        )

    all_stores = client.get(
        "/api/jd-workbench/dashboard?period=today&anchor_date=2026-08-30",
        headers=owner_headers,
    )
    assert all_stores.status_code == 200, all_stores.text
    all_payload = all_stores.json()
    assert all_payload["total"] == 2
    assert all_payload["ready_stores"] == 2
    assert all_payload["summary"]["visitors"] == 300
    assert all_payload["summary"]["page_views"] == 600
    assert all_payload["summary"]["ad_spend"] == "30.00"
    assert {item["summary"]["visitors"] for item in all_payload["stores"]} == {100, 200}

    second = stores[1]
    filtered = client.get(
        f"/api/jd-workbench/dashboard?store_id={second['store_id']}&period=today&anchor_date=2026-08-30",
        headers=owner_headers,
    )
    assert filtered.status_code == 200, filtered.text
    filtered_payload = filtered.json()
    assert filtered_payload["total"] == 1
    assert filtered_payload["stores"][0]["store_id"] == second["store_id"]
    assert filtered_payload["summary"]["visitors"] == 200
    assert filtered_payload["summary"]["ad_spend"] == "20.00"


def test_r297_dashboard_page_exposes_tasks_search_drilldown_and_auto_refresh():
    page = (
        Path(__file__).resolve().parents[1] / "frontend" / "jd-dashboard.html"
    ).read_text(encoding="utf-8")

    assert "R297" in page
    assert "30000" in page
    assert "30秒自动刷新" in page
    assert page.count("data-period=") == 3
    assert 'id="storeSearch"' in page
    assert 'data-filter="pending_shipments"' in page
    assert 'data-filter="pending_refunds"' in page
    assert 'id="detailDrawer"' in page
    assert 'src="/r297-store-view.js"' in page
    assert "R297StoreView.loadStoreDirectory(api)" in page
    assert "api('/api/stores')" not in page
    assert 'id="platformFilter"' in page
    assert 'id="enabledFilter"' in page
    assert 'id="loginFilter"' in page
    assert "自动同步中" in page
    assert "暂无真实数据" in page
    for metric in (
        "sales_amount",
        "sales_customers",
        "product_units",
        "visitors",
        "page_views",
        "sales_orders",
        "pending_shipments",
        "pending_refunds",
        "ad_spend",
        "ad_impressions",
        "ad_clicks",
        "ad_ctr",
        "ad_cpc",
    ):
        assert metric in page
    assert "模拟数据" not in page
    assert "Cookie" in page


def test_r295_page_metrics_rejects_empty_or_unknown_fields(client, owner_headers):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    for record in (
        {"source_record_key": _opaque("r295-empty")},
        {"source_record_key": _opaque("r295-unknown"), "cookie": "forbidden"},
    ):
        response = _device_request(
            client,
            "POST",
            "/api/jd-workbench/sync",
            device_token,
            _sync_payload(
                store,
                dataset_type="operating_metrics",
                records=[record],
                idempotency_key=f"r295-rejected-{uuid4()}",
            ),
        )
        assert response.status_code in {400, 422}, response.text


@pytest.mark.parametrize(
    "required_field",
    [
        "store_id",
        "subject_id",
        "dataset_type",
        "source_period",
        "collected_at",
        "idempotency_key",
        "client_version",
        "records",
    ],
)
def test_sync_rejects_missing_required_envelope_fields(
    client,
    owner_headers,
    required_field,
):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    payload = _sync_payload(store)
    payload.pop(required_field)

    response = _device_request(
        client,
        "POST",
        "/api/jd-workbench/sync",
        device_token,
        payload,
    )

    assert response.status_code in {400, 422}, response.text


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "password",
        "cookie",
        "access_token",
        "refresh_token",
        "token",
        "session",
        "session_id",
        "phone",
        "mobile",
        "receiver_phone",
        "address",
        "receiver_address",
        "buyer_name",
        "receiver_name",
        "consignee_name",
        "买家姓名",
        "收货人",
        "手机号",
        "地址",
    ],
)
def test_sync_rejects_sensitive_or_personal_fields_without_claiming_idempotency(
    client,
    owner_headers,
    test_db,
    caplog,
    forbidden_key,
):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    idempotency_key = f"r291-sensitive-{_opaque(forbidden_key)}-{uuid4()}"
    valid = _sync_payload(store, idempotency_key=idempotency_key)
    rejected = deepcopy(valid)
    canary = f"R291-SECRET-CANARY-{uuid4()}"
    rejected["records"][0][forbidden_key] = canary

    response = _device_request(
        client,
        "POST",
        "/api/jd-workbench/sync",
        device_token,
        rejected,
    )

    assert response.status_code in {400, 422}, response.text
    assert canary not in response.text

    top_level = deepcopy(valid)
    top_level[forbidden_key] = canary
    response = _device_request(
        client,
        "POST",
        "/api/jd-workbench/sync",
        device_token,
        top_level,
    )
    assert response.status_code in {400, 422}, response.text
    assert canary not in response.text
    _assert_canary_absent(test_db, caplog, canary)

    accepted = _device_request(
        client,
        "POST",
        "/api/jd-workbench/sync",
        device_token,
        valid,
    )
    batch_id = _assert_first_sync(accepted, 1)
    _assert_duplicate_sync(
        _device_request(
            client,
            "POST",
            "/api/jd-workbench/sync",
            device_token,
            valid,
        ),
        batch_id,
    )


def test_device_cannot_sync_store_outside_pairing_user_scope(
    client,
    owner_headers,
    test_db,
):
    device_token, _ = _pair_device(client, owner_headers)
    authorized = _authorized_store(client, device_token)
    with test_db() as db:
        owner = db.query(User).filter(User.username == "owner").one()
        unauthorized = Store(
            platform="jd",
            store_code="R291-NO-MEMBERSHIP",
            store_name="R291 Unauthorized Store",
            tenant_id=owner.tenant_id,
            company_id=owner.company_id,
            active=True,
        )
        db.add(unauthorized)
        db.flush()
        db.add(
            UserStoreMembership(
                user_id=owner.id,
                store_id=unauthorized.id,
                can_read=True,
                can_write=False,
                active=True,
            )
        )
        db.commit()
        unauthorized_store_id = unauthorized.id

    stores = _device_request(
        client, "GET", "/api/jd-workbench/stores", device_token
    ).json()
    stores = stores if isinstance(stores, list) else stores["stores"]
    assert unauthorized_store_id not in {store["store_id"] for store in stores}

    payload = _sync_payload(authorized)
    payload["store_id"] = unauthorized_store_id
    response = _device_request(
        client,
        "POST",
        "/api/jd-workbench/sync",
        device_token,
        payload,
    )

    assert response.status_code == 403, response.text


def test_subject_id_is_derived_from_authorized_store(client, owner_headers):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    payload = _sync_payload(store)
    payload["subject_id"] = store["subject_id"] + 1

    response = _device_request(
        client,
        "POST",
        "/api/jd-workbench/sync",
        device_token,
        payload,
    )

    assert response.status_code == 403, response.text


def test_same_idempotency_key_is_accepted_once(client, owner_headers):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    payload = _sync_payload(
        store,
        idempotency_key=f"r291-idempotency-{uuid4()}",
    )

    first = _device_request(
        client,
        "POST",
        "/api/jd-workbench/sync",
        device_token,
        payload,
    )
    batch_id = _assert_first_sync(first, len(payload["records"]))

    duplicate = _device_request(
        client,
        "POST",
        "/api/jd-workbench/sync",
        device_token,
        payload,
    )
    _assert_duplicate_sync(duplicate, batch_id)


def test_same_scoped_source_record_is_not_inserted_by_a_new_batch_key(client, owner_headers):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    first_payload = _sync_payload(store, idempotency_key=f"r291-record-first-{uuid4()}")
    _assert_first_sync(
        _device_request(
            client,
            "POST",
            "/api/jd-workbench/sync",
            device_token,
            first_payload,
        ),
        1,
    )
    second_payload = deepcopy(first_payload)
    second_payload["idempotency_key"] = f"r291-record-second-{uuid4()}"
    response = _device_request(
        client,
        "POST",
        "/api/jd-workbench/sync",
        device_token,
        second_payload,
    )

    assert response.status_code == 200, response.text
    assert response.json()["duplicate"] is False
    assert response.json()["accepted"] == 0


def test_same_idempotency_key_with_different_payload_conflicts_and_preserves_original(
    client,
    owner_headers,
):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    payload = _sync_payload(
        store,
        idempotency_key=f"r291-idempotency-conflict-{uuid4()}",
    )
    first = _device_request(
        client,
        "POST",
        "/api/jd-workbench/sync",
        device_token,
        payload,
    )
    batch_id = _assert_first_sync(first, len(payload["records"]))

    changed = deepcopy(payload)
    changed["records"][0]["sales_amount"] = 999999.99
    conflict = _device_request(
        client,
        "POST",
        "/api/jd-workbench/sync",
        device_token,
        changed,
    )
    assert conflict.status_code == 409, conflict.text

    # The conflicting request must neither replace the original batch nor consume
    # a second idempotency record. Replaying the original still resolves to it.
    original_replay = _device_request(
        client,
        "POST",
        "/api/jd-workbench/sync",
        device_token,
        payload,
    )
    _assert_duplicate_sync(original_replay, batch_id)


@pytest.mark.parametrize("reason_code", ["LOGIN_EXPIRED", "CAPTCHA_REQUIRED", "RISK_CONTROL"])
def test_human_action_required_can_be_reported_without_login_material(
    client,
    owner_headers,
    test_db,
    caplog,
    reason_code,
):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    report = {
        "client_version": CLIENT_VERSION,
        "status": "HUMAN_ACTION_REQUIRED",
        "store_id": store["store_id"],
        "reason_code": reason_code,
    }

    response = _device_request(
        client,
        "POST",
        "/api/jd-workbench/heartbeat",
        device_token,
        report,
    )

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert response.json()["status"] == "HUMAN_ACTION_REQUIRED"

    canary = f"R291-LOGIN-CANARY-{uuid4()}"
    for forbidden in (
        {"password": canary},
        {"cookie": canary},
        {"token": canary},
        {"session": canary},
        {"login_html": canary},
        {"screenshot": canary},
    ):
        rejected = _device_request(
            client,
            "POST",
            "/api/jd-workbench/heartbeat",
            device_token,
            {**report, **forbidden},
        )
        assert rejected.status_code in {400, 422}, rejected.text
        assert canary not in rejected.text
    _assert_canary_absent(test_db, caplog, canary)


def test_collected_at_must_be_an_aware_iso8601_timestamp(client, owner_headers):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    payload = _sync_payload(store)
    payload["collected_at"] = datetime.now().replace(microsecond=0).isoformat()

    naive = _device_request(
        client,
        "POST",
        "/api/jd-workbench/sync",
        device_token,
        payload,
    )
    assert naive.status_code in {400, 422}, naive.text

    payload["collected_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    aware = _device_request(
        client,
        "POST",
        "/api/jd-workbench/sync",
        device_token,
        payload,
    )
    _assert_first_sync(aware, len(payload["records"]))


def test_revoked_device_token_is_rejected_immediately(client, owner_headers):
    device_token, _ = _pair_device(client, owner_headers)
    devices = client.get("/api/jd-workbench/devices", headers=owner_headers)
    assert devices.status_code == 200, devices.text
    device_id = devices.json()[0]["device_id"]

    revoked = client.post(
        f"/api/jd-workbench/devices/{device_id}/revoke",
        headers=owner_headers,
    )
    assert revoked.status_code == 200, revoked.text
    assert _device_request(
        client, "GET", "/api/jd-workbench/stores", device_token
    ).status_code == 401


def test_r297_default_policy_is_persisted_and_pause_resume_is_cloud_owned(
    client,
    owner_headers,
    operator_headers,
):
    client.cookies.clear()
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    assert store["sync_policy"] == {
        "enabled": True,
        "interval_seconds": 300,
        "updated_at": store["sync_policy"]["updated_at"],
    }

    paused = client.patch(
        f"/api/jd-workbench/sync-policies/{store['store_id']}",
        headers=operator_headers,
        json={"enabled": False, "interval_seconds": 300},
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["next_sync_at"] is None
    cloud_store = _authorized_store(client, device_token)
    assert cloud_store["sync_policy"]["enabled"] is False

    resumed = client.patch(
        f"/api/jd-workbench/sync-policies/{store['store_id']}",
        headers=owner_headers,
        json={"enabled": True, "interval_seconds": 900},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["next_sync_at"]
    cloud_store = _authorized_store(client, device_token)
    assert cloud_store["sync_policy"]["enabled"] is True
    assert cloud_store["sync_policy"]["interval_seconds"] == 900


def test_r297_failure_retry_runtime_survives_store_refresh(client, owner_headers):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    next_sync = "2026-09-01T08:02:00Z"
    failed = _device_request(
        client,
        "POST",
        "/api/jd-workbench/heartbeat",
        device_token,
        {
            "client_version": CLIENT_VERSION,
            "status": "ERROR",
            "store_id": store["store_id"],
            "reason_code": "COLLECTOR_PAGE_LOAD_FAILED",
            "last_attempt_at": "2026-09-01T08:00:00Z",
            "next_sync_at": next_sync,
            "retry_count": 2,
        },
    )
    assert failed.status_code == 200, failed.text
    refreshed = _authorized_store(client, device_token)
    assert refreshed["status"] == "ERROR"
    assert refreshed["reason_code"] == "COLLECTOR_PAGE_LOAD_FAILED"
    assert refreshed["retry_count"] == 2
    assert refreshed["next_sync_at"].startswith("2026-09-01T08:02:00")
    assert refreshed["last_error_at"]


def test_r297_manual_handling_success_report_makes_store_due_for_automatic_resume(client, owner_headers):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    blocked = _device_request(
        client,
        "POST",
        "/api/jd-workbench/heartbeat",
        device_token,
        {
            "client_version": CLIENT_VERSION,
            "status": "HUMAN_ACTION_REQUIRED",
            "store_id": store["store_id"],
            "reason_code": "RISK_CONTROL",
        },
    )
    assert blocked.status_code == 200, blocked.text
    assert _authorized_store(client, device_token)["status"] == "HUMAN_ACTION_REQUIRED"

    resumed = _device_request(
        client,
        "POST",
        "/api/jd-workbench/heartbeat",
        device_token,
        {
            "client_version": CLIENT_VERSION,
            "status": "ONLINE",
            "store_id": store["store_id"],
        },
    )
    assert resumed.status_code == 200, resumed.text
    refreshed = _authorized_store(client, device_token)
    assert refreshed["status"] == "ONLINE"
    assert refreshed["reason_code"] is None
    assert refreshed["next_sync_at"], "人工处理成功后必须自动恢复为立即可调度状态"


def test_r297_device_session_policy_and_status_survive_backend_client_recreation(
    client,
    owner_headers,
):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    policy = client.patch(
        f"/api/jd-workbench/sync-policies/{store['store_id']}",
        headers=owner_headers,
        json={"enabled": True, "interval_seconds": 900},
    )
    assert policy.status_code == 200, policy.text
    failed = _device_request(
        client,
        "POST",
        "/api/jd-workbench/heartbeat",
        device_token,
        {
            "client_version": CLIENT_VERSION,
            "status": "ERROR",
            "store_id": store["store_id"],
            "reason_code": "COLLECTOR_PAGE_LOAD_FAILED",
            "next_sync_at": "2026-09-01T08:02:00Z",
            "retry_count": 2,
        },
    )
    assert failed.status_code == 200, failed.text

    restarted_client = TestClient(client.app)
    try:
        restored = _authorized_store(restarted_client, device_token)
    finally:
        restarted_client.close()

    assert restored["store_id"] == store["store_id"]
    assert restored["sync_policy"]["interval_seconds"] == 900
    assert restored["status"] == "ERROR"
    assert restored["retry_count"] == 2
    assert restored["next_sync_at"].startswith("2026-09-01T08:02:00")


def test_r297_fulfillment_aftersale_and_abnormal_details_are_clickable_safe_records(client, owner_headers):
    device_token, _ = _pair_device(client, owner_headers)
    store = _authorized_store(client, device_token)
    datasets = {
        "fulfillment_orders": {
            "source_record_key": _opaque("order:jd-sensitive-order-number"),
            "order_state": "待发货",
            "product_name": "商务机械表",
            "quantity": 1,
            "paid_amount": "1280.00",
            "ordered_at": "2026-09-01T07:30:00Z",
            "promised_ship_at": "2026-09-02T07:30:00Z",
        },
        "aftersale_orders": {
            "source_record_key": _opaque("service:jd-sensitive-service-number"),
            "aftersale_state": "待审核",
            "product_name": "女士石英表",
            "quantity": 1,
            "refund_amount": "688.00",
            "requested_at": "2026-09-01T07:45:00Z",
            "reason_category": "商品问题",
        },
        "abnormal_orders": {
            "source_record_key": _opaque("abnormal:jd-sensitive-order-number"),
            "abnormal_state": "物流异常",
            "product_name": "运动电子表",
            "quantity": 1,
            "detected_at": "2026-09-01T07:50:00Z",
            "reason_category": "物流停滞",
        },
    }
    for dataset_type, record in datasets.items():
        response = _device_request(
            client,
            "POST",
            "/api/jd-workbench/sync",
            device_token,
            _sync_payload(
                store,
                dataset_type=dataset_type,
                records=[record],
                idempotency_key=f"r297-{dataset_type}-{uuid4()}",
            ),
        )
        _assert_first_sync(response, 1)

    fulfillment = client.get(
        f"/api/jd-workbench/dashboard/stores/{store['store_id']}/fulfillment",
        headers=owner_headers,
    )
    aftersales = client.get(
        f"/api/jd-workbench/dashboard/stores/{store['store_id']}/aftersales",
        headers=owner_headers,
    )
    abnormal = client.get(
        f"/api/jd-workbench/dashboard/stores/{store['store_id']}/abnormal",
        headers=owner_headers,
    )
    assert fulfillment.status_code == 200, fulfillment.text
    assert aftersales.status_code == 200, aftersales.text
    assert abnormal.status_code == 200, abnormal.text
    assert fulfillment.json()["records"][0]["order_state"] == "待发货"
    assert aftersales.json()["records"][0]["aftersale_state"] == "待审核"
    assert abnormal.json()["records"][0]["abnormal_state"] == "物流异常"
    for response in (fulfillment, aftersales, abnormal):
        assert "source_record_key" not in response.text
        assert "order_no" not in response.text
        assert "buyer" not in response.text
        assert "phone" not in response.text
        assert "address" not in response.text
        assert "cookie" not in response.text.lower()
        assert "token" not in response.text.lower()
        assert "password" not in response.text.lower()

    dashboard = client.get("/api/jd-workbench/dashboard", headers=owner_headers).json()
    assert dashboard["summary"]["pending_shipment_count"] == 1
    assert dashboard["summary"]["aftersale_count"] == 1
