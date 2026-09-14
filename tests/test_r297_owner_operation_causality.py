import hashlib
import json
import secrets

import pytest

from backend.config import get_settings
from backend.models import EmployeeLog
from backend.routers import jd_workbench

SCOPE = {"namespace": "causal-test", "tenant_id": "1", "company_id": "1", "store_id": "1", "platform": "jd"}
SID = ":".join(SCOPE.values())
OPERATIONS = (
    ("post", "login-session", "owner_login_session_create", {"session_id": SID, "expires_in": 600, "restored": False}),
    ("get", "login-session", "owner_login_session_status", {"status": "ACTIVE"}),
    ("post", "login-ticket", "owner_login_ticket", {"ticket": "synthetic-fixture", "expires_in": 60}),
    ("delete", "login-session", "owner_login_session_revoke", {"ok": True}),
)


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("JD_SESSION_NAMESPACE", SCOPE["namespace"])
    monkeypatch.setenv("JD_BROWSER_CONTROL_TOKEN", secrets.token_hex(32))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class Response:
    def __init__(self, result, operation_id):
        self.body = json.dumps(result).encode()
        self.headers = {"x-owner-operation-id": operation_id,
                        "x-owner-result-sha256": hashlib.sha256(self.body).hexdigest()}

    def read(self, size=-1):
        return self.body[:size] if size >= 0 else self.body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


@pytest.mark.parametrize("method,path,operation,result", OPERATIONS)
def test_owner_response_is_bound_to_the_already_durable_operation(client, owner_headers, test_db, monkeypatch, method, path, operation, result):
    def runtime(request, **_kwargs):
        with test_db() as db:
            row = db.query(EmployeeLog).filter_by(action=operation).one()
            detail = json.loads(row.detail)
            assert detail["status"] == "PENDING"
            assert request.get_header("X-owner-operation-id") == detail["operation_id"]
        return Response(result, detail["operation_id"])

    monkeypatch.setattr(jd_workbench, "urlopen", runtime)
    response = getattr(client, method)(f"/api/jd-workbench/stores/1/{path}", headers=owner_headers,
                                       **({"json": {}} if method == "post" else {}))
    assert response.status_code == 200
    with test_db() as db:
        assert json.loads(db.query(EmployeeLog).filter_by(action=operation).one().detail)["status"] == "SUCCESS"


@pytest.mark.parametrize("mutation", ("operation_id", "response_sha256", "missing"))
def test_uncorrelated_success_response_stays_pending(client, owner_headers, test_db, monkeypatch, mutation):
    def runtime(request, **_kwargs):
        response = Response(OPERATIONS[0][3], request.get_header("X-owner-operation-id"))
        if mutation == "missing":
            response.headers = {}
        else:
            response.headers[{"operation_id": "x-owner-operation-id", "response_sha256": "x-owner-result-sha256"}[mutation]] = "invalid"
        return response

    monkeypatch.setattr(jd_workbench, "urlopen", runtime)
    assert client.post("/api/jd-workbench/stores/1/login-session", headers=owner_headers, json={}).status_code == 503
    with test_db() as db:
        assert json.loads(db.query(EmployeeLog).filter_by(action=OPERATIONS[0][2]).one().detail)["status"] == "PENDING"


@pytest.mark.parametrize("operation,status", (("owner_login_session_create", "ACTIVE"), ("owner_login_session_revoke", "REVOKED")))
def test_current_session_state_cannot_prove_a_legacy_operation(test_db, monkeypatch, operation, status):
    with test_db() as db:
        db.add(EmployeeLog(action=operation, store_id=1, detail=json.dumps({**SCOPE, "operation": operation, "status": "PENDING"})))
        db.commit()
    monkeypatch.setattr(jd_workbench, "_runtime_call", lambda *_args, **_kwargs: {"status": status})
    with test_db() as db:
        assert jd_workbench.reconcile_pending_owner_action_audits(db) == 0
        assert json.loads(db.query(EmployeeLog).filter_by(action=operation).one().detail)["status"] == "PENDING"


@pytest.mark.parametrize("operation", [item[2] for item in OPERATIONS])
@pytest.mark.parametrize("outcome", ("SUCCESS", "PENDING", "503", "wrong_id", "wrong_scope", "wrong_action"))
def test_recovery_requires_the_exact_operation_receipt(test_db, monkeypatch, operation, outcome):
    operation_id = secrets.token_hex(16)
    with test_db() as db:
        db.add(EmployeeLog(action=operation, store_id=1, detail=json.dumps({**SCOPE, "operation": operation,
            "operation_id": operation_id, "status": "PENDING"})))
        db.commit()

    def runtime(method, path, payload=None):
        assert (method, path, payload) == ("GET", f"/operations/{operation_id}", None)
        if outcome == "503":
            raise jd_workbench.HTTPException(status_code=503)
        return {"operation_id": operation_id if outcome != "wrong_id" else "0" * 32,
                "operation": operation if outcome != "wrong_action" else "different",
                "session_id": SID if outcome != "wrong_scope" else SID.replace(":1:jd", ":2:jd"),
                "status": "PENDING" if outcome == "PENDING" else "SUCCESS", "response_sha256": "a" * 64}

    monkeypatch.setattr(jd_workbench, "_runtime_call", runtime)
    with test_db() as db:
        assert jd_workbench.reconcile_pending_owner_action_audits(db) == (1 if outcome == "SUCCESS" else 0)
        assert json.loads(db.query(EmployeeLog).filter_by(action=operation).one().detail)["status"] == ("SUCCESS" if outcome == "SUCCESS" else "PENDING")
