from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError

import pytest

from backend.config import get_settings
from backend.models import Company, EmployeeLog, Store, Tenant, User, UserStoreMembership
from backend.routers import jd_workbench


OWNER_ROUTES = (
    ("POST", "/api/jd-workbench/stores/1/login-session"),
    ("GET", "/api/jd-workbench/stores/1/login-session"),
    ("DELETE", "/api/jd-workbench/stores/1/login-session"),
    ("POST", "/api/jd-workbench/stores/1/login-ticket"),
)
VIEWER_SIGNING_SETTINGS = (
    "JD_BROWSER_VIEWER_TICKET_SIGNING_KEY",
    "JD_BROWSER_VIEWER_COOKIE_SIGNING_KEY",
)


class _RuntimeResponse:
    def __init__(self, payload: dict[str, object], status: int = 200):
        self.payload = payload
        self.status = status

    def read(self, size: int = -1) -> bytes:
        payload = json.dumps(self.payload).encode("utf-8")
        return payload if size < 0 else payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _RuntimeRecorder:
    def __init__(self):
        self.requests = []

    def __call__(self, request, timeout=None):
        headers = {name.lower(): value for name, value in request.header_items()}
        assert headers.get("x-internal-token") == "control-token-that-is-at-least-32-bytes"
        assert not any("viewer" in name or "signing" in name for name in headers)
        self.requests.append((request, timeout))
        method = request.get_method()
        url = request.full_url
        if method == "POST" and url.endswith("/sessions"):
            return _RuntimeResponse({"session_id": "1:1:1:jd", "expires_in": 600, "restored": False})
        if method == "GET" and "/sessions/" in url:
            return _RuntimeResponse({"status": "ACTIVE"})
        if method == "DELETE" and "/sessions/" in url:
            return _RuntimeResponse({"ok": True})
        if method == "POST" and url.endswith("/tickets"):
            return _RuntimeResponse({"ticket": "viewer-ticket-secret", "expires_in": 60})
        raise AssertionError(f"unexpected runtime request: {method} {url}")


@pytest.fixture()
def runtime_recorder(monkeypatch):
    recorder = _RuntimeRecorder()
    monkeypatch.setenv("JD_BROWSER_CONTROL_TOKEN", "control-token-that-is-at-least-32-bytes")
    monkeypatch.setattr("urllib.request.urlopen", recorder)
    monkeypatch.setattr(jd_workbench, "urlopen", recorder, raising=False)
    get_settings.cache_clear()
    try:
        yield recorder
    finally:
        get_settings.cache_clear()


def _request(client, method: str, path: str, headers: dict[str, str], **kwargs):
    return client.request(method, path, headers=headers, **kwargs)


def _runtime_call(recorder: _RuntimeRecorder, method: str, suffix: str):
    matching = [
        item
        for item in recorder.requests
        if item[0].get_method() == method and item[0].full_url.endswith(suffix)
    ]
    assert len(matching) == 1
    return matching[0][0]


def _add_store(test_db, owner: User, scope_kind: str) -> Store:
    db = test_db()
    try:
        tenant_id = owner.tenant_id
        company_id = owner.company_id
        if scope_kind == "cross_tenant":
            tenant = Tenant(tenant_code="foreign-tenant", tenant_name="Foreign Tenant", active=True)
            db.add(tenant)
            db.flush()
            company = Company(
                tenant_id=tenant.id,
                company_code="foreign-company",
                company_name="Foreign Company",
                active=True,
            )
            db.add(company)
            db.flush()
            tenant_id, company_id = tenant.id, company.id
        elif scope_kind == "cross_company":
            company = Company(
                tenant_id=tenant_id,
                company_code="other-company",
                company_name="Other Company",
                active=True,
            )
            db.add(company)
            db.flush()
            company_id = company.id

        store = Store(
            platform="jd",
            store_code=f"scope-{scope_kind}",
            store_name=f"Scope {scope_kind}",
            tenant_id=tenant_id,
            company_id=company_id,
            active=scope_kind != "inactive",
        )
        db.add(store)
        db.flush()
        if scope_kind != "unassigned":
            db.add(
                UserStoreMembership(
                    user_id=owner.id,
                    store_id=store.id,
                    can_read=True,
                    can_write=True,
                    active=True,
                )
            )
        db.commit()
        db.refresh(store)
        db.expunge(store)
        return store
    finally:
        db.close()


@pytest.mark.parametrize(("method", "path"), OWNER_ROUTES)
def test_owner_login_routes_reject_non_owner_even_with_store_manage_permission(
    client, admin_headers, method, path
):
    response = _request(client, method, path, admin_headers)

    assert response.status_code == 403


@pytest.mark.parametrize("scope_kind", ("cross_tenant", "cross_company", "unassigned", "inactive"))
@pytest.mark.parametrize(("method", "route"), OWNER_ROUTES)
def test_owner_login_routes_reject_store_outside_exact_active_scope(
    client, owner_headers, test_db, method, route, scope_kind
):
    db = test_db()
    try:
        owner = db.query(User).filter(User.username == "owner").one()
        db.expunge(owner)
    finally:
        db.close()
    store = _add_store(test_db, owner, scope_kind)

    response = _request(client, method, route.replace("/1/", f"/{store.id}/"), owner_headers)

    assert response.status_code == 403


@pytest.mark.parametrize("path", ("login-session", "login-ticket"))
def test_owner_post_routes_reject_client_supplied_session_id(client, owner_headers, runtime_recorder, path):
    response = client.post(
        f"/api/jd-workbench/stores/1/{path}",
        headers=owner_headers,
        json={"session_id": "attacker-controlled"},
    )

    assert response.status_code == 400
    assert runtime_recorder.requests == []


def test_owner_create_session_delegates_server_derived_scope_to_runtime(client, owner_headers, runtime_recorder):
    response = client.post("/api/jd-workbench/stores/1/login-session", headers=owner_headers, json={})

    assert response.status_code == 200
    request = _runtime_call(runtime_recorder, "POST", "/internal/jd-browser/sessions")
    assert json.loads(request.data) == {"tenant_id": "1", "company_id": "1", "store_id": "1", "platform": "jd"}


def test_controlled_canary_uses_explicit_loopback_runtime(monkeypatch, client, owner_headers, runtime_recorder):
    monkeypatch.setenv("R297_CONTROLLED_CANARY", "1")
    monkeypatch.setenv(
        "JD_BROWSER_RUNTIME_BASE_URL",
        "http://127.0.0.1:18787/internal/jd-browser",
    )

    response = client.post("/api/jd-workbench/stores/1/login-session", headers=owner_headers, json={})

    assert response.status_code == 200
    assert runtime_recorder.requests[-1][0].full_url.startswith("http://127.0.0.1:18787/")
    assert response.json()["session_id"] == "1:1:1:jd"


def test_runtime_override_fails_closed_outside_controlled_loopback(monkeypatch, client, owner_headers, runtime_recorder):
    monkeypatch.setenv("R297_CONTROLLED_CANARY", "1")
    monkeypatch.setenv("JD_BROWSER_RUNTIME_BASE_URL", "https://example.invalid/internal/jd-browser")

    response = client.post("/api/jd-workbench/stores/1/login-session", headers=owner_headers, json={})

    assert response.status_code == 503
    assert response.json() == {"detail": "云端登录运行时配置无效"}
    assert runtime_recorder.requests == []


def test_owner_session_status_is_read_from_runtime(client, owner_headers, runtime_recorder):
    response = client.get("/api/jd-workbench/stores/1/login-session", headers=owner_headers)

    assert response.status_code == 200
    _runtime_call(runtime_recorder, "GET", "/internal/jd-browser/sessions/1:1:1:jd")
    assert response.json() == {"store_id": 1, "status": "ACTIVE"}


def test_owner_login_ticket_is_runtime_issued_and_never_placed_in_a_url(client, owner_headers, runtime_recorder):
    response = client.post("/api/jd-workbench/stores/1/login-ticket", headers=owner_headers, json={})

    assert response.status_code == 200
    request = _runtime_call(runtime_recorder, "POST", "/internal/jd-browser/tickets")
    assert json.loads(request.data) == {"session_id": "1:1:1:jd"}
    assert all("viewer-ticket-secret" not in item[0].full_url for item in runtime_recorder.requests)
    assert "viewer-ticket-secret" not in str(response.url)
    assert response.headers.get("location") is None
    assert response.json() == {"ticket": "viewer-ticket-secret", "expires_in": 60}


@pytest.mark.parametrize("path", ("login-session", "login-ticket"))
def test_owner_runtime_unavailable_fails_closed_without_secret_detail(
    client, owner_headers, runtime_recorder, monkeypatch, caplog, path
):
    calls = []

    def unavailable(*_args, **_kwargs):
        calls.append(1)
        raise URLError("control-token-that-is-at-least-32-bytes")

    monkeypatch.setattr("urllib.request.urlopen", unavailable)
    monkeypatch.setattr(jd_workbench, "urlopen", unavailable, raising=False)
    response = client.post(f"/api/jd-workbench/stores/1/{path}", headers=owner_headers, json={})

    assert response.status_code == 503
    assert len(calls) == 1
    assert "control-token" not in response.text
    assert "control-token" not in caplog.text


@pytest.mark.parametrize("headers", ({}, {"Authorization": "Bearer invalid-token"}))
def test_delete_session_rejects_missing_or_invalid_authentication(client, headers):
    response = client.delete("/api/jd-workbench/stores/1/login-session", headers=headers)

    assert response.status_code == 401


def test_owner_delete_session_is_authenticated_runtime_idempotent(client, owner_headers, runtime_recorder):
    responses = [
        client.delete("/api/jd-workbench/stores/1/login-session", headers=owner_headers),
        client.delete("/api/jd-workbench/stores/1/login-session", headers=owner_headers),
    ]

    assert [response.status_code for response in responses] == [200, 200]
    calls = [
        item for item in runtime_recorder.requests
        if item[0].get_method() == "DELETE" and item[0].full_url.endswith("/internal/jd-browser/sessions/1:1:1:jd")
    ]
    assert len(calls) == 2
    assert all(response.json()["status"] == "REVOKED" for response in responses)


def test_backend_settings_do_not_expose_runtime_viewer_signing_keys():
    settings = get_settings()
    backend_root = Path(jd_workbench.__file__).resolve().parents[1]
    backend_source = "\n".join(path.read_text(encoding="utf-8") for path in backend_root.rglob("*.py"))

    assert all(not hasattr(settings, name) for name in VIEWER_SIGNING_SETTINGS)
    assert all(name not in backend_source for name in VIEWER_SIGNING_SETTINGS)


def test_owner_session_audit_records_are_scoped_and_secret_free(
    client, owner_headers, test_db, runtime_recorder, caplog
):
    responses = (
        client.post("/api/jd-workbench/stores/1/login-session", headers=owner_headers, json={}),
        client.post("/api/jd-workbench/stores/1/login-ticket", headers=owner_headers, json={}),
        client.delete("/api/jd-workbench/stores/1/login-session", headers=owner_headers),
    )
    assert all(response.status_code == 200 for response in responses)

    db = test_db()
    try:
        owner = db.query(User).filter(User.username == "owner").one()
        rows = db.query(EmployeeLog).filter(EmployeeLog.user_id == owner.id, EmployeeLog.store_id == 1).all()
    finally:
        db.close()

    assert len(rows) == 3
    serialized = "\n".join(f"{row.action} {row.detail or ''}" for row in rows) + "\n" + caplog.text
    for secret in ("viewer-ticket-secret", "control-token-that-is-at-least-32-bytes"):
        assert secret not in serialized
