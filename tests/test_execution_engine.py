from __future__ import annotations

import json

import pytest
from redis.exceptions import TimeoutError as RedisTimeoutError

import backend.execution_engine as execution_engine
from backend.execution_engine import (
    EXECUTION_QUEUE_NAME,
    ExecutionSafetyError,
    acquire_execution_lock,
    pop_execution_task,
    process_next_execution_task,
    release_execution_lock,
)
from backend.dispatch_models import EmployeeExecutionLog
from backend.main import app
from backend.models import TaskCenterTask


def create_assigned_task(test_db, title="分析近期爆款手表趋势", description="分析京东男表市场趋势"):
    db = test_db()
    try:
        task = TaskCenterTask(
            title=title,
            description=description,
            status="assigned",
            priority="normal",
            source="task_center",
            assigned_ai_employee_code="tianshang",
            assigned_ai_employee_name="天商：商品中心",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task.id
    finally:
        db.close()


def get_task(test_db, task_id):
    db = test_db()
    try:
        return db.get(TaskCenterTask, task_id)
    finally:
        db.close()


def test_execution_routes_are_registered():
    routes = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}

    assert routes["/api/execution/tasks/{task_id}/claim"] == {"POST"}
    assert routes["/api/execution/tasks/{task_id}/start"] == {"POST"}
    assert routes["/api/execution/tasks/{task_id}/complete"] == {"POST"}
    assert routes["/api/execution/tasks/{task_id}/fail"] == {"POST"}
    assert routes["/api/execution/logs"] == {"GET"}


def test_assigned_task_enters_worker_queue_and_completes(client, owner_headers, test_db):
    task_id = create_assigned_task(test_db)

    claim = client.post(f"/api/execution/tasks/{task_id}/claim", headers=owner_headers)
    assert claim.status_code == 200
    assert claim.json()["queue_item"]["task_id"] == task_id

    db = test_db()
    try:
        assert process_next_execution_task(db, timeout=1, worker_id="test-worker") is True
        task = db.get(TaskCenterTask, task_id)
        assert task.status == "completed"
        logs = db.query(EmployeeExecutionLog).filter(EmployeeExecutionLog.task_id == task_id).order_by(EmployeeExecutionLog.id.asc()).all()
        assert [row.status for row in logs] == ["assigned", "running", "completed"]
        assert logs[-1].tool_used
        assert "mock_execution" in (logs[-1].output_data or "")
    finally:
        db.close()


def test_execution_lock_prevents_duplicate_running(client, owner_headers, test_db):
    task_id = create_assigned_task(test_db)
    assert acquire_execution_lock(task_id, "worker-a") is True
    try:
        start = client.post(f"/api/execution/tasks/{task_id}/start", headers=owner_headers, json={"worker_id": "worker-b"})
        assert start.status_code == 409
        task = get_task(test_db, task_id)
        assert task.status == "assigned"
    finally:
        release_execution_lock(task_id, "worker-a")


def test_execution_complete_sets_completed_and_writes_log(client, owner_headers, test_db):
    task_id = create_assigned_task(test_db)
    start = client.post(f"/api/execution/tasks/{task_id}/start", headers=owner_headers)
    assert start.status_code == 200

    complete = client.post(
        f"/api/execution/tasks/{task_id}/complete",
        headers=owner_headers,
        json={"output_data": {"summary": "执行完成"}, "tool_used": ["mock_executor"]},
    )
    assert complete.status_code == 200
    assert complete.json()["task"]["status"] == "completed"

    db = test_db()
    try:
        task = db.get(TaskCenterTask, task_id)
        assert task.status == "completed"
        log = db.query(EmployeeExecutionLog).filter(EmployeeExecutionLog.task_id == task_id, EmployeeExecutionLog.status == "completed").one()
        assert "执行完成" in (log.output_data or "")
    finally:
        db.close()


def test_execution_fail_sets_failed_and_redacts_sensitive_error(client, owner_headers, test_db):
    task_id = create_assigned_task(test_db)
    start = client.post(f"/api/execution/tasks/{task_id}/start", headers=owner_headers)
    assert start.status_code == 200

    failed = client.post(
        f"/api/execution/tasks/{task_id}/fail",
        headers=owner_headers,
        json={"error_message": "token leaked in upstream payload"},
    )
    assert failed.status_code == 200
    assert failed.json()["task"]["status"] == "failed"
    assert failed.json()["log"]["error_message"] == "[REDACTED]"


def test_execution_claim_requires_login_and_permission(client, viewer_headers, test_db):
    task_id = create_assigned_task(test_db)
    client.cookies.clear()
    unauthorized = client.post(f"/api/execution/tasks/{task_id}/claim")
    assert unauthorized.status_code == 401

    forbidden = client.post(f"/api/execution/tasks/{task_id}/claim", headers=viewer_headers)
    assert forbidden.status_code == 403


def test_high_risk_execution_requires_boss_and_security_audit(client, owner_headers, test_db):
    task_id = create_assigned_task(test_db, title="部署生产环境", description="docker deploy production")

    blocked = client.post(f"/api/execution/tasks/{task_id}/claim", headers=owner_headers)
    assert blocked.status_code == 403

    allowed = client.post(
        f"/api/execution/tasks/{task_id}/claim",
        headers=owner_headers,
        json={"boss_confirmed": True, "security_audited": True},
    )
    assert allowed.status_code == 200
    assert allowed.json()["queue_item"]["boss_confirmed"] is True
    assert allowed.json()["queue_item"]["security_audited"] is True


def test_high_risk_start_requires_boss_confirmation_and_security_audit(client, owner_headers, test_db):
    no_confirmation = create_assigned_task(test_db, title="部署生产环境", description="docker deploy production")
    blocked = client.post(f"/api/execution/tasks/{no_confirmation}/start", headers=owner_headers)
    assert blocked.status_code == 403
    assert get_task(test_db, no_confirmation).status == "assigned"

    boss_only = create_assigned_task(test_db, title="部署生产环境", description="docker deploy production")
    blocked_without_audit = client.post(
        f"/api/execution/tasks/{boss_only}/start",
        headers=owner_headers,
        json={"boss_confirmed": True, "security_audited": False},
    )
    assert blocked_without_audit.status_code == 403
    assert get_task(test_db, boss_only).status == "assigned"

    double_confirmed = create_assigned_task(test_db, title="部署生产环境", description="docker deploy production")
    allowed = client.post(
        f"/api/execution/tasks/{double_confirmed}/start",
        headers=owner_headers,
        json={"boss_confirmed": True, "security_audited": True},
    )
    assert allowed.status_code == 200
    assert allowed.json()["task"]["status"] == "running"


def test_worker_rechecks_high_risk_approval_before_running(test_db):
    task_id = create_assigned_task(test_db, title="部署生产环境", description="docker deploy production")
    execution_engine.get_redis().rpush(
        EXECUTION_QUEUE_NAME,
        json.dumps(
            {
                "queue_item_id": "unsafe-fixture",
                "task_id": task_id,
                "employee_code": "tianshang",
                "risk_level": "critical",
                "boss_confirmed": False,
                "security_audited": False,
            }
        ),
    )

    db = test_db()
    try:
        with pytest.raises(ExecutionSafetyError):
            process_next_execution_task(db, timeout=1, worker_id="test-worker")
        task = db.get(TaskCenterTask, task_id)
        assert task.status == "failed"
        failed_log = (
            db.query(EmployeeExecutionLog)
            .filter(EmployeeExecutionLog.task_id == task_id, EmployeeExecutionLog.status == "failed")
            .one()
        )
        assert "high risk execution requires boss confirmation and security audit" in failed_log.error_message
    finally:
        db.close()


def test_execution_logs_api_returns_safe_rows(client, owner_headers, test_db):
    task_id = create_assigned_task(test_db)
    assert client.post(f"/api/execution/tasks/{task_id}/start", headers=owner_headers).status_code == 200

    logs = client.get("/api/execution/logs", headers=owner_headers)
    assert logs.status_code == 200
    assert logs.json()["logs"]
    first = logs.json()["logs"][0]
    assert {"task_id", "employee_code", "status", "input_data", "output_data", "tool_used"} <= set(first)


def test_execution_queue_handles_redis_timeout(monkeypatch):
    class TimeoutRedis:
        def blpop(self, key, timeout=0):
            raise RedisTimeoutError("timeout")

    monkeypatch.setattr("backend.execution_engine.get_redis", lambda: TimeoutRedis())
    assert pop_execution_task(timeout=1) is None
