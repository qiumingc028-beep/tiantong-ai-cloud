from datetime import datetime, timedelta, timezone

from backend.models import AiEmployee, TaskCenterTask


def test_daily_summary_requires_login(client):
    response = client.get("/api/ceo-dashboard/daily-summary")

    assert response.status_code == 401


def test_daily_summary_rejects_viewer(client, viewer_headers):
    response = client.get("/api/ceo-dashboard/daily-summary", headers=viewer_headers)

    assert response.status_code == 403


def test_daily_summary_allows_owner_and_admin(client, owner_headers, admin_headers):
    for headers in (owner_headers, admin_headers):
        response = client.get("/api/ceo-dashboard/daily-summary", headers=headers)

        assert response.status_code == 200
        assert response.json()["readonly"] is True


def test_daily_summary_response_shape(client, owner_headers):
    response = client.get("/api/ceo-dashboard/daily-summary", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert {
        "system_status",
        "employee_summary",
        "task_summary",
        "pending_confirmations",
        "risk_alerts",
        "recent_failed_tasks",
    } <= set(data)
    assert {"overall", "backend", "database", "redis", "migration"} <= set(data["system_status"])
    assert {"total", "active", "inactive", "running", "idle", "error"} <= set(data["employee_summary"])
    assert {"today_total", "pending", "assigned", "running", "completed", "failed", "result_submitted"} <= set(data["task_summary"])


def test_daily_summary_counts_operating_metrics(client, owner_headers, test_db):
    db = test_db()
    try:
        old_time = datetime.now(timezone.utc) - timedelta(days=2)
        db.add(TaskCenterTask(title="old task", status="created", created_at=old_time, updated_at=old_time))
        db.add(TaskCenterTask(title="today created", status="created"))
        db.add(TaskCenterTask(title="today split", status="split"))
        db.add(TaskCenterTask(title="today running", status="running", assigned_ai_employee_code="tianwang"))
        db.add(TaskCenterTask(title="today completed", status="summarized", assigned_ai_employee_code="tiantong"))
        db.add(TaskCenterTask(title="today failed", status="rejected", assigned_ai_employee_code="tianwang"))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/ceo-dashboard/daily-summary", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["task_summary"]["today_total"] == 5
    assert data["task_summary"]["completed"] == 1
    assert data["task_summary"]["failed"] == 1
    assert data["employee_summary"]["running"] == 1
    assert data["pending_confirmations"]
    assert data["risk_alerts"]
    assert data["recent_failed_tasks"][0]["title"] == "today failed"


def test_daily_summary_is_readonly(client, owner_headers, test_db):
    db = test_db()
    try:
        before_tasks = db.query(TaskCenterTask).count()
        before_employees = db.query(AiEmployee).count()
    finally:
        db.close()

    response = client.get("/api/ceo-dashboard/daily-summary", headers=owner_headers)
    assert response.status_code == 200

    db = test_db()
    try:
        assert db.query(TaskCenterTask).count() == before_tasks
        assert db.query(AiEmployee).count() == before_employees
    finally:
        db.close()
