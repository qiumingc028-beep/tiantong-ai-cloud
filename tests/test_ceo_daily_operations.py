from datetime import datetime, timedelta, timezone

from backend.models import AiEmployee, TaskCenterTask


def test_daily_operations_requires_login(client):
    response = client.get("/api/ceo-dashboard/daily-operations")
    assert response.status_code == 401


def test_daily_operations_rejects_viewer(client, viewer_headers):
    response = client.get("/api/ceo-dashboard/daily-operations", headers=viewer_headers)
    assert response.status_code == 403


def test_daily_operations_allows_owner_and_admin(client, owner_headers, admin_headers):
    for headers in [owner_headers, admin_headers]:
        response = client.get("/api/ceo-dashboard/daily-operations", headers=headers)
        assert response.status_code == 200
        assert response.json()["readonly"] is True


def test_daily_operations_response_shape(client, owner_headers):
    response = client.get("/api/ceo-dashboard/daily-operations", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert {
        "checked_at",
        "readonly",
        "system_status",
        "employee_summary",
        "task_summary",
        "pending_confirmations",
        "risk_alerts",
        "recent_failed_tasks",
        "forbidden_actions",
    } <= set(data)
    assert {"overall", "backend", "database", "redis", "migration"} <= set(data["system_status"])
    assert {"total", "active", "inactive", "running", "idle", "error"} <= set(data["employee_summary"])
    assert {"today_total", "pending", "assigned", "running", "completed", "failed"} <= set(data["task_summary"])


def test_daily_operations_counts_today_tasks_and_running_employees(client, owner_headers, test_db):
    db = test_db()
    try:
        old_time = datetime.now(timezone.utc) - timedelta(days=2)
        db.add(TaskCenterTask(title="old task", status="created", created_at=old_time, updated_at=old_time))
        db.add(TaskCenterTask(title="created task", status="created"))
        db.add(TaskCenterTask(title="split task", status="split"))
        db.add(TaskCenterTask(title="assigned task", status="assigned", assigned_ai_employee_code="tiance"))
        db.add(TaskCenterTask(title="running task", status="running", assigned_ai_employee_code="tianshang"))
        db.add(TaskCenterTask(title="done task", status="summarized", assigned_ai_employee_code="tiantong"))
        db.add(TaskCenterTask(title="failed task", status="rejected", assigned_ai_employee_code="tianwang"))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/ceo-dashboard/daily-operations", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    tasks = data["task_summary"]
    assert tasks["today_total"] == 6
    assert tasks["pending"] == 2
    assert tasks["assigned"] == 1
    assert tasks["running"] == 1
    assert tasks["completed"] == 1
    assert tasks["failed"] == 1
    assert data["employee_summary"]["running"] == 1
    assert data["recent_failed_tasks"][0]["title"] == "failed task"


def test_daily_operations_is_readonly(client, owner_headers, test_db):
    db = test_db()
    try:
        before_tasks = db.query(TaskCenterTask).count()
        before_employees = db.query(AiEmployee).count()
    finally:
        db.close()

    response = client.get("/api/ceo-dashboard/daily-operations", headers=owner_headers)
    assert response.status_code == 200

    db = test_db()
    try:
        assert db.query(TaskCenterTask).count() == before_tasks
        assert db.query(AiEmployee).count() == before_employees
    finally:
        db.close()
