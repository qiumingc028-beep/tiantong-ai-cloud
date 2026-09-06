from __future__ import annotations

import importlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

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
    lease_expired = restarted_module._now() + timedelta(seconds=61)
    monkeypatch.setattr(restarted_module, "_now", lambda: lease_expired)
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
        ("owner_login_ticket", None, "PENDING"),
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
        assert jd_workbench.reconcile_pending_owner_action_audits(db) == (0 if action == "owner_login_ticket" else 1)
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


def test_application_startup_reconciles_pending_owner_audit(
    test_db, monkeypatch, caplog
):
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
            }, separators=(",", ":")),
        ))
        db.commit()
    finally:
        db.close()

    runtime_calls = []
    monkeypatch.setattr(
        jd_workbench,
        "_runtime_call",
        lambda method, path, payload=None: runtime_calls.append((method, path, payload)) or {"status": "ACTIVE"},
    )
    monkeypatch.setattr(backend_main, "SessionLocal", test_db)
    monkeypatch.setattr(backend_main, "ensure_tables", lambda: None)
    monkeypatch.setattr(backend_main, "seed_defaults", lambda _db: None)
    monkeypatch.setattr("backend.alpha_workflow.registry.ensure_default_scenarios", lambda _db: None)
    monkeypatch.setattr("backend.observability.service.ensure_default_alert_rules", lambda _db: None)
    monkeypatch.setattr("backend.observability.service.ensure_default_circuit_breakers", lambda _db: None)

    with TestClient(app):
        pass

    rows = _audit_rows(test_db, "owner_login_session_create")
    assert len(rows) == 1
    assert rows[0][1]["status"] == "SUCCESS"
    assert len(runtime_calls) == 1
    _assert_secret_free(test_db, caplog)


def test_owner_audit_reconciler_claims_once_across_concurrent_workers(
    postgres_database_factory, monkeypatch
):
    from tests.conftest import _alembic, seed_database

    database_url = postgres_database_factory("r297_owner_audit_concurrent")
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    seed_database(sessions)
    db = sessions()
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
            }, separators=(",", ":")),
        ))
        db.commit()
    finally:
        db.close()

    start = threading.Barrier(2)
    both_selects_completed = threading.Event()
    select_count = 0
    select_count_lock = threading.Lock()
    runtime_calls = []
    runtime_calls_lock = threading.Lock()

    def observe_pending_select(_connection, _cursor, statement, _parameters, _context, _executemany):
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT") and "employee_logs" in statement:
            with select_count_lock:
                select_count += 1
                if select_count == 2:
                    both_selects_completed.set()

    def runtime(method, path, payload=None):
        assert both_selects_completed.wait(timeout=5), "both workers must finish the pending-row claim query"
        with runtime_calls_lock:
            runtime_calls.append((method, path, payload))
        return {"status": "ACTIVE"}

    def reconcile():
        worker_db = sessions()
        try:
            start.wait(timeout=5)
            return jd_workbench.reconcile_pending_owner_action_audits(worker_db)
        finally:
            worker_db.close()

    monkeypatch.setattr(jd_workbench, "_owner_saga_reconcile_after_id", 0)
    monkeypatch.setattr(jd_workbench, "_runtime_call", runtime)
    event.listen(engine, "after_cursor_execute", observe_pending_select)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            processed = list(executor.map(lambda _index: reconcile(), range(2)))
        event.remove(engine, "after_cursor_execute", observe_pending_select)
        assert sum(processed) == 1
        assert len(runtime_calls) == 1
        rows = _audit_rows(sessions, "owner_login_session_create")
        assert len(rows) == 1
        assert rows[0][1]["status"] == "SUCCESS"
    finally:
        if event.contains(engine, "after_cursor_execute", observe_pending_select):
            event.remove(engine, "after_cursor_execute", observe_pending_select)
        engine.dispose()


def test_worker_main_repeats_owner_audit_reconciliation_on_poll_interval(monkeypatch):
    from backend import worker

    class StopWorkerLoop(Exception):
        pass

    heartbeat_count = 0
    maintenance_calls = []
    monotonic_values = iter([
        0.0,
        float(worker.JD_SCHEDULER_POLL_SECONDS),
        float(worker.JD_SCHEDULER_POLL_SECONDS),
        float(worker.JD_SCHEDULER_POLL_SECONDS * 2),
        float(worker.JD_SCHEDULER_POLL_SECONDS * 2),
    ])

    def heartbeat():
        nonlocal heartbeat_count
        heartbeat_count += 1
        if heartbeat_count == 4:
            raise StopWorkerLoop

    monkeypatch.setattr(worker, "require_service_role", lambda _role: None)
    monkeypatch.setattr(worker, "update_worker_heartbeat", heartbeat)
    monkeypatch.setattr(worker.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(worker.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(worker, "run_jd_workbench_maintenance", lambda: maintenance_calls.append("run"))
    monkeypatch.setattr(worker, "run_daily_scheduler", lambda: None)
    monkeypatch.setattr(worker, "process_next_tian_shang_worker_execution", lambda: False)
    monkeypatch.setattr(worker, "process_next_employee_execution", lambda: False)
    monkeypatch.setattr(worker, "process_next_brain_runtime_execution", lambda: False)
    monkeypatch.setattr(worker, "process_next_task", lambda: False)

    with pytest.raises(StopWorkerLoop):
        worker.main()

    assert maintenance_calls == ["run", "run"]



def test_owner_audit_reconciler_retries_transient_runtime_failure(test_db, monkeypatch):
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

    runtime_calls = []

    def unavailable(*_args, **_kwargs):
        runtime_calls.append("unavailable")
        raise jd_workbench.HTTPException(status_code=503, detail="temporary")

    monkeypatch.setattr(jd_workbench, "_runtime_call", unavailable)
    db = test_db()
    try:
        assert jd_workbench.reconcile_pending_owner_action_audits(db) == 0
    finally:
        db.close()
    assert _audit_rows(test_db, "owner_login_session_create")[-1][1]["status"] == "PENDING"

    monkeypatch.setattr(
        jd_workbench,
        "_runtime_call",
        lambda *_args, **_kwargs: runtime_calls.append("success") or {"status": "ACTIVE"},
    )
    db = test_db()
    try:
        assert jd_workbench.reconcile_pending_owner_action_audits(db) == 1
    finally:
        db.close()
    assert _audit_rows(test_db, "owner_login_session_create")[-1][1]["status"] == "SUCCESS"
    assert runtime_calls == ["unavailable", "success"]


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


@pytest.mark.parametrize("method,path", (("post", "login-session"), ("get", "login-session"),
                                         ("delete", "login-session"), ("post", "login-ticket")))
def test_every_owner_unknown_outcome_stays_pending(client, owner_headers, test_db, monkeypatch, method, path):
    def unavailable(*_args, **_kwargs):
        raise URLError("temporary")

    monkeypatch.setattr(jd_workbench, "urlopen", unavailable)
    response = getattr(client, method)(f"/api/jd-workbench/stores/1/{path}", headers=owner_headers,
                                       **({"json": {}} if method == "post" else {}))
    assert response.status_code == 503
    action = {("post", "login-session"): "owner_login_session_create",
              ("get", "login-session"): "owner_login_session_status",
              ("delete", "login-session"): "owner_login_session_revoke",
              ("post", "login-ticket"): "owner_login_ticket"}[(method, path)]
    assert _audit_rows(test_db, action)[0][1]["status"] == "PENDING"


def test_recovery_does_not_take_over_an_inflight_owner_request(client, owner_headers, test_db, monkeypatch):
    def runtime(*_args, **_kwargs):
        with test_db() as db:
            assert jd_workbench.reconcile_pending_owner_action_audits(db) == 0
        return _Response({"session_id": SESSION_ID, "expires_in": 600, "restored": False})

    monkeypatch.setattr(jd_workbench, "urlopen", runtime)
    response = client.post("/api/jd-workbench/stores/1/login-session", headers=owner_headers, json={})
    assert response.status_code == 200
    assert _audit_rows(test_db, "owner_login_session_create")[0][1]["status"] == "SUCCESS"


@pytest.mark.parametrize("reclaim", (False, True))
def test_postgresql_owner_recovery_claim_and_stale_writer_fencing(postgres_database_factory, monkeypatch, reclaim):
    from tests.conftest import _alembic

    url = postgres_database_factory("owner_claim")
    _alembic(url, "upgrade", "head")
    engine = create_engine(url)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as db:
        row = EmployeeLog(action="owner_login_session_create", detail=json.dumps({
            "status": "PENDING", "namespace": VECTORS["namespace"], "tenant_id": "1",
            "company_id": "1", "store_id": "1", "platform": "jd", "operation": "owner_login_session_create",
        }))
        db.add(row)
        db.commit()
        row_id = row.id
    entered, release = threading.Event(), threading.Event()
    outcomes, calls = [], []
    current_time = [jd_workbench._now()]
    monkeypatch.setattr(jd_workbench, "_now", lambda: current_time[0])
    monkeypatch.setattr(jd_workbench, "_owner_saga_reconcile_after_id", 0)

    def runtime(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
            return {"status": "ACTIVE"}
        raise jd_workbench.HTTPException(status_code=503, detail="unknown")

    monkeypatch.setattr(jd_workbench, "_runtime_call", runtime)

    def recover():
        with sessions() as db:
            try:
                outcomes.append(jd_workbench.reconcile_pending_owner_action_audits(db))
            except jd_workbench.HTTPException as exc:
                outcomes.append(exc.status_code)

    thread = threading.Thread(target=recover)
    thread.start()
    try:
        assert entered.wait(5)
        if reclaim:
            current_time[0] += timedelta(seconds=61)
        with sessions() as db:
            assert jd_workbench.reconcile_pending_owner_action_audits(db) == 0
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive()
    assert len(calls) == (2 if reclaim else 1)
    assert outcomes == ([503] if reclaim else [1])
    with sessions() as db:
        assert json.loads(db.get(EmployeeLog, row_id).detail)["status"] == ("PENDING" if reclaim else "SUCCESS")
    engine.dispose()


def test_worker_startup_runs_maintenance_before_consuming_tasks(monkeypatch):
    from backend import worker

    monkeypatch.setattr(worker, "require_service_role", lambda *_args: None)
    monkeypatch.setattr(worker, "update_worker_heartbeat", lambda: None)
    monkeypatch.setattr(worker.time, "monotonic", lambda: 100000.0)

    def maintenance():
        raise RuntimeError("startup maintenance reached")

    monkeypatch.setattr(worker, "run_jd_workbench_maintenance", maintenance)
    with pytest.raises(RuntimeError, match="startup maintenance reached"):
        worker.main()
