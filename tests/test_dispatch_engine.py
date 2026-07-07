from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.dispatch_models import DispatchRecord, EmployeeExecutionLog
from backend.models import TaskCenterTask


def create_task(client, headers, title="实现后端 API", description="新增 backend api 并补 pytest", priority="normal"):
    response = client.post(
        "/api/task-center/tasks",
        headers=headers,
        json={"title": title, "description": description, "priority": priority},
    )
    assert response.status_code == 200
    return response.json()["task"]["id"]


def test_auto_dispatch_requires_login_and_rejects_low_permission(client, viewer_headers):
    client.cookies.clear()
    assert client.post("/api/auto-dispatch/analyze", json={"title": "实现后端 API"}).status_code == 401
    assert client.post("/api/auto-dispatch/analyze", headers=viewer_headers, json={"title": "实现后端 API"}).status_code == 403


def test_auto_dispatch_recommends_backend_employee(client, owner_headers):
    response = client.post(
        "/api/auto-dispatch/analyze",
        headers=owner_headers,
        json={"title": "实现后端 API", "description": "数据库和 pytest 也要完成"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["task_type"] == "backend"
    assert data["risk_level"] == "low"
    assert data["can_auto_execute"] is True
    assert data["recommended_employees"][0]["employee_code"] == "tianwang"


def test_auto_dispatch_detects_high_risk_deploy_and_blocks_auto_execute(client, owner_headers):
    response = client.post(
        "/api/auto-dispatch/analyze",
        headers=owner_headers,
        json={"title": "部署生产环境", "description": "docker compose up and deploy"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["task_type"] == "deploy"
    assert data["risk_level"] == "critical"
    assert data["requires_boss_confirmation"] is True
    assert data["requires_security_audit"] is True
    assert data["can_auto_execute"] is False
    assert data["recommended_employees"][0]["employee_code"] == "tiandun"


def test_auto_dispatch_match_returns_best_employee(client, owner_headers):
    response = client.post(
        "/api/auto-dispatch/match",
        headers=owner_headers,
        json={"task_type": "strategy", "keywords": ["新品", "推广", "方案"], "capability_tags": ["strategy"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["best_employee"]["employee_code"] == "tiance"


def test_auto_dispatch_plan_writes_dispatch_records(client, owner_headers, test_db):
    task_id = create_task(client, owner_headers, title="前端页面优化", description="dashboard ui 页面")

    response = client.post(f"/api/auto-dispatch/tasks/{task_id}/plan", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["dispatch_plan"]["task_id"] == task_id
    assert data["dispatch_plan"]["employees"][0]["employee_code"] == "tianyan"
    db = test_db()
    try:
        records = db.query(DispatchRecord).filter(DispatchRecord.task_id == task_id).all()
        assert records
        assert records[0].employee_code == "tianyan"
    finally:
        db.close()


def test_high_risk_confirm_requires_boss_confirmation_and_security_audit(client, owner_headers):
    task_id = create_task(client, owner_headers, title="部署生产环境", description="deploy docker production")

    missing_boss = client.post(f"/api/auto-dispatch/tasks/{task_id}/confirm", headers=owner_headers, json={"employee_code": "tiandun"})
    assert missing_boss.status_code == 400
    assert "boss confirmation" in missing_boss.json()["detail"]

    missing_audit = client.post(
        f"/api/auto-dispatch/tasks/{task_id}/confirm",
        headers=owner_headers,
        json={"employee_code": "tiandun", "boss_confirmed": True},
    )
    assert missing_audit.status_code == 400
    assert "security audit" in missing_audit.json()["detail"]


def test_low_risk_confirm_assigns_task_without_changing_status_flow(client, owner_headers, test_db):
    task_id = create_task(client, owner_headers, title="前端页面优化", description="dashboard ui 页面")

    response = client.post(f"/api/auto-dispatch/tasks/{task_id}/confirm", headers=owner_headers, json={"employee_code": "tianyan"})

    assert response.status_code == 200
    data = response.json()
    assert data["task"]["status"] == "assigned"
    assert data["task"]["assigned_ai_employee_code"] == "tianyan"
    db = test_db()
    try:
        task = db.get(TaskCenterTask, task_id)
        assert task.status == "assigned"
        assert task.assigned_ai_employee_code == "tianyan"
        record = db.query(DispatchRecord).filter(DispatchRecord.task_id == task_id, DispatchRecord.dispatch_status == "confirmed").one()
        assert record.employee_code == "tianyan"
    finally:
        db.close()


def test_execution_tracking_records_start_complete_and_failure(client, owner_headers, test_db):
    task_id = create_task(client, owner_headers)
    for action in ["start", "execute", "complete", "fail"]:
        response = client.post(
            f"/api/auto-dispatch/tasks/{task_id}/tracking",
            headers=owner_headers,
            json={"employee_code": "tianwang", "action": action, "result": f"{action} ok"},
        )
        assert response.status_code == 200

    response = client.get(f"/api/auto-dispatch/tasks/{task_id}/tracking", headers=owner_headers)
    assert response.status_code == 200
    assert [row["action"] for row in response.json()["execution_logs"]] == ["start", "execute", "complete", "fail"]
    db = test_db()
    try:
        assert db.query(EmployeeExecutionLog).filter(EmployeeExecutionLog.task_id == task_id).count() == 4
    finally:
        db.close()


def test_auto_dispatch_overview_and_reference_data(client, owner_headers):
    overview = client.get("/api/auto-dispatch/overview", headers=owner_headers)
    assert overview.status_code == 200
    assert overview.json()["readonly_safety"]["auto_deploy_allowed"] is False

    capabilities = client.get("/api/auto-dispatch/employee-capabilities", headers=owner_headers)
    assert capabilities.status_code == 200
    assert any(item["employee_code"] == "tianwang" for item in capabilities.json())
    assert any(
        item["employee_code"] == "tianshang" and item["department"] == "电商经营军团" and item["capability"]
        for item in capabilities.json()
    )

    rules = client.get("/api/auto-dispatch/routing-rules", headers=owner_headers)
    assert rules.status_code == 200
    assert any(item["recommended_employee"] == "tiandun" for item in rules.json())


def test_auto_dispatch_migration_is_single_head():
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0014_sprint18_execution_engine"]
