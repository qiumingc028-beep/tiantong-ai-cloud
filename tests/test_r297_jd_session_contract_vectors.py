from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.config import get_settings
from backend.routers import jd_workbench


ROOT = Path(__file__).resolve().parents[1]
VECTOR_PATH = ROOT / "tests" / "fixtures" / "r297_jd_session_contract_vectors.json"
VECTORS = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
CONTROL_TOKEN = "control-token-that-is-at-least-32-bytes"


class _Response:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def read(self, size: int = -1) -> bytes:
        content = json.dumps(self.payload).encode("utf-8")
        return content[:size] if size >= 0 else content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _runtime(monkeypatch, responder):
    requests = []

    def urlopen(request, timeout=None):
        requests.append((request, timeout))
        return _Response(responder(request))

    monkeypatch.setenv("JD_BROWSER_CONTROL_TOKEN", CONTROL_TOKEN)
    monkeypatch.setenv("JD_SESSION_NAMESPACE", VECTORS["namespace"])
    monkeypatch.setattr(jd_workbench, "urlopen", urlopen)
    get_settings.cache_clear()
    return requests


@pytest.fixture(autouse=True)
def _settings_cache_guard():
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def test_shared_contract_vector_schema_covers_required_cases():
    assert VECTORS["valid_session_id"].split(":") == [
        VECTORS["namespace"],
        VECTORS["valid_scope"]["tenant_id"],
        VECTORS["valid_scope"]["company_id"],
        VECTORS["valid_scope"]["store_id"],
        VECTORS["valid_scope"]["platform"],
    ]
    assert {case["name"] for case in VECTORS["invalid_scope_cases"]} == {
        "namespace_missing",
        "namespace_mismatch",
        "non_jd_platform",
        "dataset_mixed_into_scope",
        "unicode_scope_value",
        "store_id_missing",
        "scope_extra_field",
        "store_id_wrong_type",
        "store_id_zero",
    }
    assert {case["name"]: case["expected_status"] for case in VECTORS["invalid_scope_cases"]} == {
        "namespace_missing": 400,
        "namespace_mismatch": 403,
        "non_jd_platform": 400,
        "dataset_mixed_into_scope": 400,
        "unicode_scope_value": 400,
        "store_id_missing": 400,
        "scope_extra_field": 400,
        "store_id_wrong_type": 400,
        "store_id_zero": 400,
    }
    assert VECTORS["store_id_normalization"] == {"canonical": "1", "equivalent_inputs": ["1", 1]}
    assert VECTORS["ticket_ttl_rejections"] == [True, 0, -1, 121]
    assert VECTORS["max_ticket_ttl_seconds"] == 120
    assert {case["name"] for case in VECTORS["claim_type_misuse"]} == {
        "ticket_used_as_cookie",
        "cookie_used_as_ticket",
    }
    assert {case["name"] for case in VECTORS["capture_cases"]} == {
        "valid_metrics",
        "unknown_dataset",
        "dataset_mixed_into_scope",
    }
    assert {case["name"] for case in VECTORS["invalid_capture_request_cases"]} == {
        "dataset_missing",
        "dataset_wrong_type",
        "capture_extra_field",
    }


@pytest.mark.parametrize("expires_in", VECTORS["ticket_ttl_rejections"], ids=lambda value: f"ttl-{value!r}")
def test_owner_rejects_ticket_ttl_outside_shared_contract(
    client, owner_headers, monkeypatch, expires_in
):
    _runtime(
        monkeypatch,
        lambda _request: {"ticket": "viewer-ticket-secret", "expires_in": expires_in},
    )

    response = client.post("/api/jd-workbench/stores/1/login-ticket", headers=owner_headers, json={})

    assert response.status_code == 503
    assert "viewer-ticket-secret" not in response.text


def test_owner_rejects_runtime_response_extra_fields_from_shared_contract(
    client, owner_headers, monkeypatch
):
    invalid = VECTORS["invalid_runtime_response_cases"][0]["response"]
    _runtime(monkeypatch, lambda _request: invalid)

    response = client.post("/api/jd-workbench/stores/1/login-ticket", headers=owner_headers, json={})

    assert response.status_code == 503
    assert "must-not-leak" not in response.text


def test_owner_accepts_shared_ticket_ttl_upper_boundary(client, owner_headers, monkeypatch):
    _runtime(
        monkeypatch,
        lambda _request: {
            "ticket": "viewer-ticket-secret",
            "expires_in": VECTORS["max_ticket_ttl_seconds"],
        },
    )

    response = client.post("/api/jd-workbench/stores/1/login-ticket", headers=owner_headers, json={})

    assert response.status_code == 200
    assert response.json()["expires_in"] == 120


def test_owner_rejects_legacy_runtime_session_id(client, owner_headers, monkeypatch):
    _runtime(
        monkeypatch,
        lambda _request: {
            "session_id": VECTORS["legacy_session_id"],
            "expires_in": 600,
            "restored": False,
        },
    )

    response = client.post("/api/jd-workbench/stores/1/login-session", headers=owner_headers, json={})

    assert response.status_code == 503
    assert "session_id" not in response.text


def test_owner_runtime_path_uses_encoded_server_derived_session_id(client, owner_headers, monkeypatch):
    requests = _runtime(monkeypatch, lambda _request: {"status": "ACTIVE"})

    response = client.get("/api/jd-workbench/stores/1/login-session", headers=owner_headers)

    expected = "%3A".join((VECTORS["namespace"], "1", "1", "1", VECTORS["valid_scope"]["platform"]))
    assert response.status_code == 200
    assert requests[0][0].full_url.endswith(f"/sessions/{expected}")
