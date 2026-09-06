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
from backend import main as backend_main
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


def test_owner_audit_saga_keeps_unknown_runtime_outcome_pending_without_secret(
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
    assert rows[0][1]["status"] == "PENDING"
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
    monkeypatch.setattr(backend_main, "SessionLocal", test_db)
    monkeypatch.setattr(backend_main, "seed_defaults", lambda _db: None)
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

    restarted_db = test_db()
    try:
        observed_reconciler(restarted_db)
    finally:
        restarted_db.close()
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


@pytest.mark.parametrize(
    ("action", "runtime_status", "expected_status"),
    (
        ("owner_login_session_create", "ACTIVE", "SUCCESS"),
        ("owner_login_session_status", "LOGIN_REQUIRED", "SUCCESS"),
        ("owner_login_session_revoke", "REVOKED", "SUCCESS"),
        ("owner_login_ticket", None, "FAILED"),
    ),
)
def test_owner_audit_saga_reconciles_every_owner_operation(
    test_db, monkeypatch, action, runtime_status, expected_status
):
    db = test_db()
    try:
        db.add(EmployeeLog(
            user_id=1,
            store_id=1,
            action=action,
            detail=json.dumps({
                "status": "PENDING",
                "namespace": VECTORS["namespace"],
                "tenant_id": "1",
                "company_id": "1",
                "store_id": "1",
                "platform": VECTORS["valid_scope"]["platform"],
                "operation": action,
            }),
        ))
        db.commit()
    finally:
        db.close()

    calls = []

    def runtime(method, path, payload=None):
        calls.append((method, path, payload))
        return {"status": runtime_status}

    monkeypatch.setattr(jd_workbench, "_runtime_call", runtime)
    db = test_db()
    try:
        assert jd_workbench.reconcile_pending_owner_action_audits(db) == 1
    finally:
        db.close()

    assert _audit_rows(test_db, action)[-1][1]["status"] == expected_status
    assert len(calls) == (0 if action == "owner_login_ticket" else 1)


def test_worker_periodic_maintenance_runs_owner_audit_reconciler(monkeypatch):
    from backend import worker

    calls = []
    monkeypatch.setattr(worker, "reconcile_completed_jd_workbench_tasks", lambda: calls.append("terminal"))
    monkeypatch.setattr(worker, "reap_jd_workbench_tasks", lambda: calls.append("reaper"))
    monkeypatch.setattr(worker, "run_jd_workbench_scheduler", lambda: calls.append("scheduler"))
    monkeypatch.setattr(worker, "reconcile_owner_action_audits", lambda: calls.append("owner_audit"))

    worker.run_jd_workbench_maintenance()

    assert calls == ["terminal", "reaper", "scheduler", "owner_audit"]


def test_owner_audit_reconciler_keeps_transient_runtime_failure_pending(test_db, monkeypatch):
    db = test_db()
    try:
        db.add(EmployeeLog(
            user_id=1,
            store_id=1,
            action="owner_login_session_create",
            detail=json.dumps({
                "status": "PENDING",
                "namespace": VECTORS["namespace"],
                "tenant_id": "1",
                "company_id": "1",
                "store_id": "1",
                "platform": VECTORS["valid_scope"]["platform"],
                "operation": "owner_login_session_create",
            }),
        ))
        db.commit()
    finally:
        db.close()

    def unavailable(*_args, **_kwargs):
        raise jd_workbench.HTTPException(status_code=503, detail="temporary")

    monkeypatch.setattr(jd_workbench, "_runtime_call", unavailable)
    db = test_db()
    try:
        assert jd_workbench.reconcile_pending_owner_action_audits(db) == 0
    finally:
        db.close()
    assert _audit_rows(test_db, "owner_login_session_create")[-1][1]["status"] == "PENDING"


def test_owner_audit_reconciler_processes_a_bounded_batch(test_db, monkeypatch):
    monkeypatch.setattr(jd_workbench, "_owner_saga_reconcile_after_id", 0)
    db = test_db()
    try:
        for _ in range(jd_workbench.OWNER_SAGA_RECONCILE_BATCH_SIZE + 3):
            db.add(EmployeeLog(
                user_id=1,
                store_id=1,
                action="owner_login_session_status",
                detail=json.dumps({
                    "status": "PENDING",
                    "namespace": VECTORS["namespace"],
                    "tenant_id": "1",
                    "company_id": "1",
                    "store_id": "1",
                    "platform": VECTORS["valid_scope"]["platform"],
                    "operation": "owner_login_session_status",
                }, separators=(",", ":")),
            ))
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(jd_workbench, "_runtime_call", lambda *_args: {"status": "ACTIVE"})
    db = test_db()
    try:
        assert jd_workbench.reconcile_pending_owner_action_audits(db) == jd_workbench.OWNER_SAGA_RECONCILE_BATCH_SIZE
    finally:
        db.close()
    statuses = [detail["status"] for _, detail in _audit_rows(test_db, "owner_login_session_status")]
    assert statuses.count("PENDING") == 3


def test_owner_status_invalid_runtime_response_finishes_audit_failed(
    client, owner_headers, test_db, monkeypatch
):
    monkeypatch.setattr(jd_workbench, "urlopen", lambda *_args, **_kwargs: _Response({"status": "UNKNOWN"}))

    response = client.get("/api/jd-workbench/stores/1/login-session", headers=owner_headers)

    assert response.status_code == 503
    assert _audit_rows(test_db, "owner_login_session_status")[-1][1]["status"] == "FAILED"


def test_invalid_owner_ticket_request_does_not_create_pending_audit(
    client, owner_headers, test_db, monkeypatch
):
    monkeypatch.setattr(
        jd_workbench,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("invalid request must not reach runtime"),
    )

    response = client.post(
        "/api/jd-workbench/stores/1/login-ticket", headers=owner_headers, json={"unexpected": True}
    )

    assert response.status_code == 400
    assert _audit_rows(test_db, "owner_login_ticket") == []
