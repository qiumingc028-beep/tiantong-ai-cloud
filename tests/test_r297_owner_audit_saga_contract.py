from __future__ import annotations

import importlib
import json
from pathlib import Path
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.main import app
from backend.models import EmployeeLog
from backend.routers import jd_workbench


VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "r297_jd_session_contract_vectors.json").read_text(encoding="utf-8")
)
SESSION_ID = ":".join((VECTORS["namespace"], "1", "1", "1", VECTORS["valid_scope"]["platform"]))
CONTROL_TOKEN = "control-token-that-is-at-least-32-bytes"
SENSITIVE_VALUES = (CONTROL_TOKEN, "viewer-ticket-secret", "cookie-canary-secret")


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


@pytest.fixture(autouse=True)
def _runtime_settings(monkeypatch):
    monkeypatch.setenv("JD_BROWSER_CONTROL_TOKEN", CONTROL_TOKEN)
    monkeypatch.setenv("JD_SESSION_NAMESPACE", VECTORS["namespace"])
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _audit_rows(test_db, action: str) -> list[tuple[EmployeeLog, dict[str, object]]]:
    db = test_db()
    try:
        result = []
        for row in db.query(EmployeeLog).filter(EmployeeLog.store_id == 1, EmployeeLog.action == action).all():
            try:
                detail = json.loads(row.detail or "")
            except (TypeError, ValueError):
                continue
            if isinstance(detail, dict) and detail.get("status") in {"PENDING", "SUCCESS", "FAILED"}:
                db.expunge(row)
                result.append((row, detail))
        return result
    finally:
        db.close()


def _assert_secret_free(test_db, caplog) -> None:
    db = test_db()
    try:
        serialized = "\n".join(row.detail or "" for row in db.query(EmployeeLog).all()) + caplog.text
    finally:
        db.close()
    assert all(secret not in serialized for secret in SENSITIVE_VALUES)


def test_owner_audit_saga_commits_pending_before_runtime_then_success(
    client, owner_headers, test_db, monkeypatch, caplog
):
    observed = []

    def runtime(request, timeout=None):
        rows = _audit_rows(test_db, "owner_login_session_create")
        assert len(rows) == 1
        assert rows[0][1]["status"] == "PENDING"
        observed.append((request, timeout))
        return _Response({"session_id": SESSION_ID, "expires_in": 600, "restored": False})

    monkeypatch.setattr(jd_workbench, "urlopen", runtime)
    response = client.post("/api/jd-workbench/stores/1/login-session", headers=owner_headers, json={})

    assert response.status_code == 200
    assert len(observed) == 1
    rows = _audit_rows(test_db, "owner_login_session_create")
    assert len(rows) == 1
    assert rows[0][1]["status"] == "SUCCESS"
    _assert_secret_free(test_db, caplog)


def test_owner_audit_saga_records_failed_runtime_without_secret(
    client, owner_headers, test_db, monkeypatch, caplog
):
    def unavailable(_request, timeout=None):
        rows = _audit_rows(test_db, "owner_login_session_create")
        assert len(rows) == 1
        assert rows[0][1]["status"] == "PENDING"
        raise URLError(CONTROL_TOKEN)

    monkeypatch.setattr(jd_workbench, "urlopen", unavailable)
    response = client.post("/api/jd-workbench/stores/1/login-session", headers=owner_headers, json={})

    assert response.status_code == 503
    rows = _audit_rows(test_db, "owner_login_session_create")
    assert len(rows) == 1
    assert rows[0][1]["status"] == "FAILED"
    _assert_secret_free(test_db, caplog)


def test_owner_audit_saga_reconciles_after_success_update_commit_crash(
    client, owner_headers, test_db, monkeypatch, caplog
):
    runtime_calls = []

    def runtime(request, timeout=None):
        runtime_calls.append((request, timeout))
        if request.get_method() == "POST":
            return _Response({"session_id": SESSION_ID, "expires_in": 600, "restored": False})
        return _Response({"status": "ACTIVE"})

    def fail_success_update(session, _flush_context, _instances):
        for row in session.dirty:
            if not isinstance(row, EmployeeLog):
                continue
            try:
                detail = json.loads(row.detail or "")
            except (TypeError, ValueError):
                continue
            if detail.get("status") == "SUCCESS":
                raise RuntimeError("audit update commit failed")

    monkeypatch.setattr(jd_workbench, "urlopen", runtime)
    event.listen(Session, "before_flush", fail_success_update)
    try:
        safe_client = TestClient(app, raise_server_exceptions=False)
        response = safe_client.post("/api/jd-workbench/stores/1/login-session", headers=owner_headers, json={})
    finally:
        event.remove(Session, "before_flush", fail_success_update)

    assert response.status_code == 503
    assert "audit update commit failed" not in response.text
    assert len(runtime_calls) == 1
    rows = _audit_rows(test_db, "owner_login_session_create")
    assert len(rows) == 1
    assert rows[0][1]["status"] == "PENDING"

    restarted_module = importlib.reload(jd_workbench)
    monkeypatch.setattr(restarted_module, "urlopen", runtime)
    reconciler = getattr(restarted_module, "reconcile_pending_owner_action_audits", None)
    assert callable(reconciler), "owner audit Saga needs a restart-safe reconciler"
    reconciliation_results = []

    def observed_reconciler(db):
        result = reconciler(db)
        reconciliation_results.append(result)
        return result

    monkeypatch.setattr(restarted_module, "reconcile_pending_owner_action_audits", observed_reconciler)
    with TestClient(app):
        pass
    assert reconciliation_results == [1]

    restarted_db = test_db()
    try:
        assert reconciler(restarted_db) == 0
    finally:
        restarted_db.close()

    rows = _audit_rows(test_db, "owner_login_session_create")
    assert len(rows) == 1
    assert rows[0][1]["status"] == "SUCCESS"
    assert len(runtime_calls) == 2
    _assert_secret_free(test_db, caplog)
