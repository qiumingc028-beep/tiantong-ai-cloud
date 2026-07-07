from pathlib import Path

from sqlalchemy import event, text

from backend.deploy_models import DeployHealthCheck, DeployRecord, HealthCheckRecord
from backend.models import AiEmployee, TaskCenterTask


def auth_headers(client, username: str):
    response = client.post("/api/login", json={"username": username, "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_index_html_serves_ceo_dashboard_page(client):
    response = client.get("/index.html")
    assert response.status_code == 200
    assert "老板驾驶舱" in response.text
    assert "/api/ceo-dashboard/summary" in response.text


def test_ceo_dashboard_requires_login(client):
    response = client.get("/api/ceo-dashboard/summary")
    assert response.status_code == 401


def test_ceo_dashboard_rejects_non_privileged_roles(client):
    for username in ["operator", "customer_service", "designer", "editor", "viewer"]:
        response = client.get("/api/ceo-dashboard/summary", headers=auth_headers(client, username))
        assert response.status_code == 403


def test_ceo_dashboard_allows_boss_owner_admin(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        response = client.get("/api/ceo-dashboard/summary", headers=headers)
        assert response.status_code == 200


def test_ceo_dashboard_response_shape(client, owner_headers):
    response = client.get("/api/ceo-dashboard/summary", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert {
        "overall_status",
        "checked_at",
        "system_health",
        "task_summary",
        "pending_actions",
        "employee_summary",
        "deploy_summary",
        "alerts",
    } <= set(data)


def test_ceo_dashboard_task_summary_matches_task_center_data(client, owner_headers, test_db):
    db = test_db()
    try:
        for status in ["created", "split", "assigned", "running", "result_submitted", "accepted", "rejected", "audited", "summarized"]:
            db.add(TaskCenterTask(title=f"{status} task", status=status))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/ceo-dashboard/summary", headers=owner_headers)
    assert response.status_code == 200
    task_summary = response.json()["task_summary"]
    assert task_summary["total"] == 9
    for status in ["created", "split", "assigned", "running", "result_submitted", "accepted", "rejected", "audited", "summarized"]:
        assert task_summary[status] == 1
    assert task_summary["pending_count"] == 8
    assert len(task_summary["recent_pending_tasks"]) == 8


def test_ceo_dashboard_employee_summary_matches_registry_data(client, owner_headers, test_db):
    db = test_db()
    try:
        db.query(AiEmployee).filter(AiEmployee.employee_code == "tianwang").one().status = "inactive"
        db.commit()
    finally:
        db.close()

    response = client.get("/api/ceo-dashboard/summary", headers=owner_headers)
    assert response.status_code == 200
    employee_summary = response.json()["employee_summary"]
    assert employee_summary["total"] == 3
    assert employee_summary["active"] == 2
    assert employee_summary["inactive"] == 1
    assert employee_summary["legions"] >= 1
    assert all(item["status"] == "active" for item in employee_summary["active_employees"])


def test_ceo_dashboard_deploy_summary_returns_alembic_version(client, owner_headers, test_db):
    db = test_db()
    try:
        db.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        db.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0012_sprint16_ceo_deploy_loop')"))
        db.add(DeployRecord(deploy_version="Sprint 4", status="success"))
        db.add(DeployHealthCheck(check_type="database", target="database", status="healthy"))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/ceo-dashboard/summary", headers=owner_headers)
    assert response.status_code == 200
    deploy_summary = response.json()["deploy_summary"]
    assert deploy_summary["alembic_version"] == "0012_sprint16_ceo_deploy_loop"
    assert deploy_summary["expected_version"] == "0012_sprint16_ceo_deploy_loop"
    assert deploy_summary["last_deploy_status"] == "success"
    assert deploy_summary["last_health_check_status"] == "healthy"


def test_ceo_dashboard_sprint16_deploy_loop_fields(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add(
            DeployRecord(
                deploy_id="deploy-sprint16-001",
                version="Sprint 16",
                commit_id="abc1234",
                deploy_status="success",
                operator="tiandun",
            )
        )
        db.add(HealthCheckRecord(service="backend", status="healthy", latency=15))
        db.add(HealthCheckRecord(service="redis", status="healthy", latency=6))
        db.add(HealthCheckRecord(service="worker", status="unhealthy", latency=120))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/ceo-dashboard/summary", headers=owner_headers)
    assert response.status_code == 200
    deploy_summary = response.json()["deploy_summary"]
    assert deploy_summary["latest_deploy"]["deploy_id"] == "deploy-sprint16-001"
    assert deploy_summary["latest_deploy"]["version"] == "Sprint 16"
    assert deploy_summary["latest_deploy"]["commit_id"] == "abc1234"
    assert deploy_summary["latest_deploy"]["deploy_time"] is not None
    assert deploy_summary["latest_deploy"]["deploy_status"] == "success"
    assert deploy_summary["latest_deploy"]["operator"] == "tiandun"
    assert deploy_summary["deployment_history"][0]["deploy_id"] == "deploy-sprint16-001"
    assert deploy_summary["last_health_check_status"] == "unhealthy"
    assert deploy_summary["last_health_check_time"] is not None
    assert deploy_summary["service_stability_score"] == 67


def test_ceo_dashboard_pending_actions_detect_task_states(client, owner_headers, test_db):
    db = test_db()
    try:
        for status in ["created", "split", "result_submitted", "accepted", "audited", "rejected"]:
            db.add(TaskCenterTask(title=f"{status} task", status=status))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/ceo-dashboard/summary", headers=owner_headers)
    assert response.status_code == 200
    action_types = [item["type"] for item in response.json()["pending_actions"]]
    assert action_types.index("rejected") < action_types.index("result_submitted")
    for action_type in ["created", "split", "result_submitted", "accepted", "audited", "rejected"]:
        assert action_type in action_types


def test_ceo_dashboard_alerts_detect_health_and_task_warnings(client, owner_headers, test_db, monkeypatch):
    db = test_db()
    try:
        db.add(TaskCenterTask(title="rejected task", status="rejected"))
        db.add(TaskCenterTask(title="submitted task", status="result_submitted"))
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        "backend.routers.ceo_dashboard.deploy_center.check_redis",
        lambda: {"target": "redis", "status": "unhealthy", "message": "simulated"},
    )

    response = client.get("/api/ceo-dashboard/summary", headers=owner_headers)
    assert response.status_code == 200
    alert_types = {item["type"] for item in response.json()["alerts"]}
    assert {"redis", "rejected_tasks", "result_submitted"} <= alert_types


def test_ceo_dashboard_does_not_write_database(client, owner_headers, test_db):
    db = test_db()
    engine = db.get_bind()
    statements = []

    def capture_write(_conn, _cursor, statement, _parameters, _context, _executemany):
        verb = statement.strip().split(maxsplit=1)[0].upper()
        if verb in {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"}:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_write)
    try:
        response = client.get("/api/ceo-dashboard/summary", headers=owner_headers)
        assert response.status_code == 200
        assert statements == []
    finally:
        event.remove(engine, "before_cursor_execute", capture_write)
        db.close()


def test_ceo_dashboard_does_not_add_unexpected_alembic_migration():
    versions = {path.name for path in Path("alembic/versions").glob("*.py")}
    assert "0009_deploy_center_tables.py" in versions
    assert "0010_orchestrator_tables.py" in versions
    assert "0011_orchestrator_task_links.py" in versions
    assert "0012_sprint16_ceo_deploy_loop.py" in versions
