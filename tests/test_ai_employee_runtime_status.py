from datetime import datetime, timedelta, timezone

from backend.models import AiEmployee, TaskCenterTask
from backend.tool_router.models import ToolRoute


def test_ai_employee_runtime_status_requires_login(client):
    response = client.get("/api/ai-employees/runtime-status")

    assert response.status_code == 401


def test_ai_employee_runtime_status_rejects_low_permission(client, operator_headers):
    response = client.get("/api/ai-employees/runtime-status", headers=operator_headers)

    assert response.status_code == 403


def test_ai_employee_runtime_status_allows_owner_and_admin(client, owner_headers, admin_headers):
    for headers in (owner_headers, admin_headers):
        response = client.get("/api/ai-employees/runtime-status", headers=headers)

        assert response.status_code == 200
        assert response.json()["readonly"] is True


def test_ai_employee_runtime_status_schema_and_counts(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add(
            ToolRoute(
                employee_code="tiantong",
                tool_name="database_read",
                priority=10,
                risk_level="low",
                enabled=True,
            )
        )
        db.add(TaskCenterTask(title="Current assigned task", status="assigned", assigned_ai_employee_code="tiantong"))
        db.add(TaskCenterTask(title="Current running task", status="running", assigned_ai_employee_code="tianwang"))
        db.add(TaskCenterTask(title="Recent rejected task", status="rejected", assigned_ai_employee_code="tianwang"))
        db.add(TaskCenterTask(title="Today completed task", status="summarized", assigned_ai_employee_code="tiantong"))
        old_time = datetime.now(timezone.utc) - timedelta(days=2)
        db.add(
            TaskCenterTask(
                title="Old completed task",
                status="summarized",
                assigned_ai_employee_code="tiantong",
                created_at=old_time,
                updated_at=old_time,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/ai-employees/runtime-status", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert {"readonly", "checked_at", "summary", "employees"} <= set(data)
    assert data["summary"]["total_employees"] == 2
    assert data["summary"]["online_count"] == 2
    assert data["summary"]["working_count"] == 1
    assert data["summary"]["error_count"] == 1
    assert data["summary"]["idle_count"] == 0

    rows = {row["employee_code"]: row for row in data["employees"]}
    assert rows["tiantong"]["runtime_status"] == "working"
    assert rows["tiantong"]["current_task"]["title"] == "Current assigned task"
    assert rows["tiantong"]["today_completed_tasks"] == 1
    assert rows["tiantong"]["tools"][0]["tool_name"] == "database_read"
    assert rows["tianwang"]["runtime_status"] == "error"
    assert rows["tianwang"]["recent_error"]["title"] == "Recent rejected task"


def test_ai_employee_runtime_status_is_readonly(client, owner_headers, test_db):
    db = test_db()
    try:
        before_tasks = db.query(TaskCenterTask).count()
        before_employees = db.query(AiEmployee).count()
        before_routes = db.query(ToolRoute).count()
    finally:
        db.close()

    response = client.get("/api/ai-employees/runtime-status", headers=owner_headers)
    assert response.status_code == 200

    db = test_db()
    try:
        assert db.query(TaskCenterTask).count() == before_tasks
        assert db.query(AiEmployee).count() == before_employees
        assert db.query(ToolRoute).count() == before_routes
    finally:
        db.close()
