from backend.brain_execution.models import BrainExecutionRun, BrainWorkerStatus
from backend.models import AiEmployee, TaskCenterTask


V2_ENDPOINTS = [
    "/api/ceo-dashboard/v2/system-health",
    "/api/ceo-dashboard/v2/task-summary",
    "/api/ceo-dashboard/v2/employee-status",
    "/api/ceo-dashboard/v2/execution-status",
    "/api/ceo-dashboard/v2/daily-operations",
    "/api/ceo-dashboard/v2/overview",
]


def test_ceo_dashboard_v2_requires_login(client):
    client.cookies.clear()

    for path in V2_ENDPOINTS:
        response = client.get(path)

        assert response.status_code == 401


def test_ceo_dashboard_v2_rejects_viewer(client, viewer_headers):
    for path in V2_ENDPOINTS:
        response = client.get(path, headers=viewer_headers)

        assert response.status_code == 403


def test_ceo_dashboard_v2_allows_boss_owner_admin(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        for path in V2_ENDPOINTS:
            response = client.get(path, headers=headers)

            assert response.status_code == 200
            assert response.json()["readonly"] is True


def test_ceo_dashboard_v2_system_health_shape(client, owner_headers):
    response = client.get("/api/ceo-dashboard/v2/system-health", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["readonly"] is True
    assert {"checked_at", "overall_status", "services", "deploy_summary", "alerts"} <= set(data)
    assert {"backend", "database", "redis", "migration"} <= set(data["services"])
    assert {
        "overall_status",
        "alembic_version",
        "expected_version",
        "last_deploy_status",
        "last_health_check_status",
        "last_health_check_time",
        "service_stability_score",
    } <= set(data["deploy_summary"])


def test_ceo_dashboard_v2_task_summary_uses_task_center_data(client, owner_headers, test_db):
    db = test_db()
    try:
        for status in [
            "created",
            "split",
            "assigned",
            "running",
            "result_submitted",
            "accepted",
            "rejected",
            "audited",
            "summarized",
        ]:
            db.add(TaskCenterTask(title=f"{status} task", status=status))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/ceo-dashboard/v2/task-summary", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["readonly"] is True
    assert data["total"] == 9
    assert data["today_total"] == 9
    assert data["pending_count"] == 8
    for status in [
        "created",
        "split",
        "assigned",
        "running",
        "result_submitted",
        "accepted",
        "rejected",
        "audited",
        "summarized",
    ]:
        assert data["status_counts"][status] == 1
    assert data["today"]["completed"] == 3
    assert data["today"]["failed"] == 1
    assert data["recent_failed_tasks"][0]["title"] == "rejected task"


def test_ceo_dashboard_v2_employee_status_uses_ai_employee_data(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add(TaskCenterTask(title="running task", status="running", assigned_ai_employee_code="tiantong"))
        db.query(AiEmployee).filter(AiEmployee.employee_code == "tianwang").one().status = "inactive"
        db.commit()
    finally:
        db.close()

    response = client.get("/api/ceo-dashboard/v2/employee-status", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["readonly"] is True
    assert data["total"] == 3
    assert data["active"] == 2
    assert data["inactive"] == 1
    assert data["working"] == 1
    employees = {row["employee_code"]: row for row in data["employees"]}
    assert employees["tiantong"]["runtime_status"] == "working"
    assert employees["tianwang"]["runtime_status"] == "offline"
    assert "legacy_operator" not in employees


def test_ceo_dashboard_v2_execution_status_uses_execution_engine_data(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add(BrainExecutionRun(goal="running execution", status="RUNNING", risk_level="low"))
        db.add(BrainExecutionRun(goal="queued execution", status="QUEUED", risk_level="low"))
        db.add(BrainExecutionRun(goal="success execution", status="SUCCESS", risk_level="low"))
        db.add(BrainExecutionRun(goal="failed execution", status="FAILED", risk_level="high", last_error="blocked by safety"))
        db.add(BrainWorkerStatus(worker_id="brain-worker-1", status="running", current_task="dry-run task"))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/ceo-dashboard/v2/execution-status", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["readonly"] is True
    assert data["mode"] == "simulation"
    assert data["current_execution_count"] == 1
    assert data["queued_count"] >= 1
    assert data["worker_count"] == 1
    assert data["failed_count"] == 1
    assert data["status_counts"]["RUNNING"] == 1
    assert data["status_counts"]["SUCCESS"] == 1
    assert data["recent_failures"][0]["last_error"] == "blocked by safety"
    assert "shell" in data["forbidden_actions"]


def test_ceo_dashboard_v2_daily_operations_shape(client, owner_headers):
    response = client.get("/api/ceo-dashboard/v2/daily-operations", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["readonly"] is True
    assert {
        "checked_at",
        "system_status",
        "employee_summary",
        "task_summary",
        "pending_confirmations",
        "risk_alerts",
        "recent_failed_tasks",
        "forbidden_actions",
    } <= set(data)
    assert "auto_deploy" in data["forbidden_actions"]


def test_ceo_dashboard_v2_overview_aggregates_core_sections(client, owner_headers):
    response = client.get("/api/ceo-dashboard/v2/overview", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["readonly"] is True
    assert {
        "checked_at",
        "overall_status",
        "system_health",
        "daily_operations",
        "employee_status",
        "task_summary",
        "execution_status",
        "pending_action_summary",
        "risk_summary",
    } <= set(data)
    assert data["system_health"]["readonly"] is True
    assert data["daily_operations"]["readonly"] is True
    assert data["employee_status"]["readonly"] is True
    assert data["task_summary"]["readonly"] is True
    assert data["execution_status"]["readonly"] is True
    assert "pending_count" in data["pending_action_summary"]
    assert "risk_count" in data["risk_summary"]


def test_ceo_dashboard_v2_is_readonly(client, owner_headers, test_db):
    db = test_db()
    try:
        before_tasks = db.query(TaskCenterTask).count()
        before_employees = db.query(AiEmployee).count()
        before_executions = db.query(BrainExecutionRun).count()
    finally:
        db.close()

    for path in V2_ENDPOINTS:
        response = client.get(path, headers=owner_headers)

        assert response.status_code == 200

    db = test_db()
    try:
        assert db.query(TaskCenterTask).count() == before_tasks
        assert db.query(AiEmployee).count() == before_employees
        assert db.query(BrainExecutionRun).count() == before_executions
    finally:
        db.close()
