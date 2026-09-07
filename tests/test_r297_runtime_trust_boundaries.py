import json
import secrets
from types import SimpleNamespace

import pytest

from backend.services import jd_collectors


@pytest.mark.parametrize("endpoint", (
    "https://example.invalid/internal/jd-browser", "http://jd-browser-runtime:8787.evil/internal/jd-browser",
    "http://127.0.0.1:8787/internal/jd-browser", "http://localhost:8787/internal/jd-browser",
    "http://jd-browser-runtime:8787/internal/jd-browser?next=evil",
    "http://jd-browser-runtime:8787/internal/jd-browser#fragment",
))
def test_capture_credentials_never_leave_the_fixed_runtime(monkeypatch, endpoint):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JD_BROWSER_CAPTURE_BASE_URL", endpoint)
    monkeypatch.setenv("JD_BROWSER_CAPTURE_TOKEN", secrets.token_hex(32))
    monkeypatch.setenv("JD_SESSION_NAMESPACE", "r297-" + secrets.token_hex(12))
    calls = []
    monkeypatch.setattr(jd_collectors, "urlopen", lambda *_args, **_kwargs: calls.append("sent"))
    with pytest.raises(jd_collectors.JdCollectorError):
        jd_collectors.JdSmartCollector()._capture(None, "metrics", SimpleNamespace(id=1, tenant_id=1, company_id=1))
    assert calls == [], "reject the destination before any credential-bearing I/O"


@pytest.mark.parametrize("namespace", ("default", "production", "prod", "development", "ci", "test", "r297"))
def test_deployed_owner_namespace_rejects_generic_placeholders(monkeypatch, namespace):
    from backend.config import get_settings
    from backend.routers import jd_workbench

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JD_SESSION_NAMESPACE", namespace)
    monkeypatch.setattr(jd_workbench, "get_settings", lambda: SimpleNamespace(JD_SESSION_NAMESPACE=namespace))
    try:
        with pytest.raises(jd_workbench.HTTPException):
            jd_workbench._runtime_session_id(SimpleNamespace(id=1, tenant_id=1, company_id=1, platform="jd"))
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("revocation", ("owner_inactive", "owner_role", "membership", "write_permission", "tenant", "company"))
def test_runtime_continuously_authorizes_the_original_owner_grant(client, test_db, monkeypatch, revocation):
    from backend.config import get_settings
    from backend.models import Company, EmployeeLog, Store, Tenant, User, UserStoreMembership

    token, operation_id = secrets.token_hex(32), secrets.token_hex(16)
    monkeypatch.setenv("JD_BROWSER_CONTROL_TOKEN", token)
    monkeypatch.setenv("JD_SESSION_NAMESPACE", "grant-test")
    get_settings.cache_clear()
    scope = {"namespace": "grant-test", "tenant_id": "1", "company_id": "1", "store_id": "1", "platform": "jd"}
    with test_db() as db:
        db.add(EmployeeLog(user_id=1, store_id=1, action="owner_login_session_create",
                           detail=json.dumps({**scope, "operation_id": operation_id, "status": "SUCCESS"})))
        db.commit()
    headers = {"x-internal-token": token, "x-owner-session-operation-id": operation_id}
    path = "/api/jd-workbench/internal/browser-session-authorize"
    assert client.post(path, headers=headers, json=scope).status_code == 204
    with test_db() as db:
        if revocation == "owner_inactive":
            db.get(User, 1).active = False
        elif revocation == "owner_role":
            db.get(User, 1).role = "employee"
        elif revocation in {"membership", "write_permission"}:
            member = db.query(UserStoreMembership).filter_by(user_id=1, store_id=1).one()
            if revocation == "membership":
                member.active = False
            else:
                member.can_write = False
        elif revocation == "tenant":
            db.get(Tenant, 1).active = False
        else:
            db.get(Company, 1).active = False
        db.commit()
    assert client.post(path, headers=headers, json=scope).status_code == 403
    get_settings.cache_clear()


def test_credential_transport_rejects_redirects_and_environment_proxies(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.error import HTTPError
    from urllib.request import Request, ProxyHandler
    from backend.routers import jd_workbench

    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/credential-sink")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setenv("http_proxy", "http://example.invalid:12345")
    monkeypatch.setenv("HTTP_PROXY", "http://example.invalid:12345")
    monkeypatch.setenv("no_proxy", "")
    try:
        for transport in (jd_collectors.urlopen, jd_workbench.urlopen):
            assert not any(isinstance(handler, ProxyHandler) and handler.proxies for handler in transport.__self__.handlers)
            with pytest.raises(HTTPError) as failure:
                transport(Request(f"http://127.0.0.1:{server.server_port}/start",
                                  headers={"x-internal-token": secrets.token_hex(32)}), timeout=2)
            assert failure.value.code == 302
        assert hits == ["/start", "/start"]
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


def test_production_runtime_enables_namespace_pin():
    from pathlib import Path

    runtime = Path("docker-compose.prod.yml").read_text().split("\n  postgres:\n", 1)[0]
    assert "\n    environment:\n      APP_ENV: production\n" in runtime
