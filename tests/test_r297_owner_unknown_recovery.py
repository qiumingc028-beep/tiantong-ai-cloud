import json
import secrets
from datetime import timedelta

import pytest

from backend.models import EmployeeLog
from backend.routers import jd_workbench as api
from tests.test_r297_owner_operation_causality import OPERATIONS, SCOPE, SID, settings


@pytest.mark.parametrize("method,path,operation,result", OPERATIONS)
def test_unknown_retry_keeps_one_durable_operation_and_never_reexecutes(client, owner_headers, test_db, monkeypatch, method, path, operation, result):
    calls = []
    key = secrets.token_hex(16)

    def uncertain(*args, **kwargs):
        calls.append(kwargs.get("operation_id"))
        raise api.HTTPException(status_code=503)

    monkeypatch.setattr(api, "_runtime_call", uncertain)
    headers = {**owner_headers, "x-owner-operation-id": key}
    request = lambda: getattr(client, method)(f"/api/jd-workbench/stores/1/{path}", headers=headers,
                                              **({"json": {}} if method == "post" else {}))
    assert request().status_code == 503
    retry = request()
    assert retry.status_code == 409
    assert retry.json()["detail"]["operation_id"] == key
    assert retry.json()["detail"]["status"] == "UNKNOWN"
    assert calls == [key]
    with test_db() as db:
        rows = db.query(EmployeeLog).filter_by(action=operation).all()
        assert len(rows) == 1
        detail = json.loads(rows[0].detail)
        assert detail["status"] == "PENDING"
        assert detail["operation_id"] == key
    query = client.get(f"/api/jd-workbench/stores/1/login-operations/{key}", headers=owner_headers)
    assert query.status_code == 200
    assert query.json()["status"] == "UNKNOWN"


def test_unknown_recovery_backs_off_stops_at_deadline_and_manual_check_reuses_receipt(client, owner_headers, test_db, monkeypatch):
    clock = api._now()
    monkeypatch.setattr(api, "_now", lambda: clock)
    key = secrets.token_hex(16)
    with test_db() as db:
        db.add(EmployeeLog(user_id=1, store_id=1, action=OPERATIONS[0][2], detail=json.dumps({
            **SCOPE, "operation": OPERATIONS[0][2], "operation_id": key, "status": "PENDING",
            "created_at": clock.isoformat(), "recovery_deadline": (clock + timedelta(minutes=15)).isoformat(),
        })))
        db.commit()
    calls = []
    success = False

    def receipt(method, path, payload=None, **kwargs):
        calls.append((method, path))
        if success:
            with test_db() as concurrent:
                assert api.reconcile_pending_owner_action_audits(concurrent) == 0
        return {"operation_id": key, "operation": OPERATIONS[0][2], "session_id": SID,
                "status": "SUCCESS" if success else "PENDING", "response_sha256": "a" * 64 if success else None}

    monkeypatch.setattr(api, "_runtime_call", receipt)
    with test_db() as db:
        assert api.reconcile_pending_owner_action_audits(db) == 0
        assert api.reconcile_pending_owner_action_audits(db) == 0
        assert len(calls) == 1
        clock += timedelta(minutes=16)
        assert api.reconcile_pending_owner_action_audits(db) == 0
        detail = json.loads(db.query(EmployeeLog).filter_by(action=OPERATIONS[0][2]).one().detail)
        assert detail["status"] == "UNKNOWN"
        assert detail["manual_review_required"] is True
        assert len(calls) == 1
    success = True
    result = client.post(f"/api/jd-workbench/stores/1/login-operations/{key}/reconcile", headers=owner_headers, json={})
    assert result.status_code == 200
    assert result.json()["status"] == "SUCCESS"
    assert calls == [("GET", f"/operations/{key}")] * 2


@pytest.mark.parametrize("method,path,operation,result", OPERATIONS)
def test_lost_success_response_then_reload_requires_confirming_old_operation_before_new_effect(client, owner_headers, monkeypatch, method, path, operation, result):
    calls = []
    old_key = secrets.token_hex(16)
    monkeypatch.setattr(api, "_runtime_call", lambda *args, **kwargs: calls.append(kwargs["operation_id"]) or result)
    def send(key, acknowledged=None):
        headers = {**owner_headers, "x-owner-operation-id": key}
        if acknowledged:
            headers["x-owner-ack-operation-id"] = acknowledged
        return getattr(client, method)(f"/api/jd-workbench/stores/1/{path}", headers=headers,
                                       **({"json": {}} if method == "post" else {}))
    assert send(old_key).status_code == 200  # Delivered on server, then response is lost to browser.
    new_key = secrets.token_hex(16)  # Simulate refresh losing the in-memory client map.
    uncertain_retry = send(new_key)
    assert uncertain_retry.status_code == 409
    assert uncertain_retry.json()["detail"]["operation_id"] == old_key
    assert uncertain_retry.json()["detail"]["status"] == "SUCCESS"
    assert calls == [old_key]
    assert send(new_key, acknowledged=old_key).status_code == 200  # Explicit next intent after old result confirmation.
    assert calls == [old_key, new_key]


def test_browser_retry_retains_the_logical_operation_key_without_secret_storage():
    import subprocess

    script = r"""
const assert = require('node:assert/strict');
const {createClient} = require('./frontend/r297-owner-login.js');
const keys = [];
const request = async (_path, options) => { keys.push(options.headers['x-owner-operation-id']); throw new Error('lost response'); };
const client = createClient(request);
await assert.rejects(client.create(1), /网络连接失败/);
await assert.rejects(client.create(1), /网络连接失败/);
assert.match(keys[0], /^[0-9a-f]{32}$/);
assert.equal(keys[0], keys[1]);
await assert.rejects(createClient(async (_path, options) => ({status: 409, json: async () => ({detail: {
  operation_id: options.headers['x-owner-operation-id'], status: 'UNKNOWN', message: '结果未知，需人工核查'
}})})).create(1), /结果未知/);
"""
    result = subprocess.run(["node", "-e", f"(async()=>{{{script}}})().catch(e=>{{console.error(e);process.exit(1)}})"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
