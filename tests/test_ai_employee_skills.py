from pathlib import Path

from backend.models import TaskCenterTask, User


BASE = "/api/ai-employee-skills"
ROUTER_FILE = Path("backend/routers/ai_employee_skills.py")
SERVICE_FILE = Path("backend/services/ai_employee_skills.py")


def test_ai_employee_skills_requires_login(client):
    response = client.get(f"{BASE}/skills")

    assert response.status_code == 401


def test_ai_employee_skills_permissions(client, owner_headers, admin_headers, boss_headers, viewer_headers, operator_headers):
    for headers in [owner_headers, admin_headers, boss_headers]:
        client.cookies.clear()
        response = client.get(f"{BASE}/skills", headers=headers)
        assert response.status_code == 200

    for headers in [viewer_headers, operator_headers]:
        client.cookies.clear()
        response = client.get(f"{BASE}/skills", headers=headers)
        assert response.status_code == 403


def test_ai_employee_skills_list_returns_readonly_structure(client, owner_headers):
    response = client.get(f"{BASE}/skills", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "readonly"
    assert {"skill_total", "employee_with_skill_count", "high_risk_skill_count", "average_success_rate", "last_updated"} <= set(data["summary"])
    assert isinstance(data["skills"], list)
    assert data["skills"]
    row = data["skills"][0]
    assert {
        "skill_id",
        "skill_name",
        "skill_version",
        "employee_id",
        "usage_count",
        "success_rate",
        "risk_level",
        "created_time",
        "updated_time",
    } <= set(row)
    assert data["security"]["readonly"] is True
    assert data["security"]["auto_skill_call_enabled"] is False
    assert data["security"]["execution_engine_called"] is False
    assert data["security"]["openclaw_connected"] is False
    assert data["security"]["n8n_connected"] is False


def test_ai_employee_skills_detail_returns_skill(client, owner_headers):
    response = client.get(f"{BASE}/skills/skill_market_analysis", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "readonly"
    assert data["skill"]["skill_id"] == "skill_market_analysis"
    assert "skill_name" in data["skill"]
    assert isinstance(data["employees"], list)
    assert "task_usage" in data
    assert "audit_refs" in data
    assert data["security"]["auto_skill_call_enabled"] is False


def test_ai_employee_skills_employee_relations(client, owner_headers):
    response = client.get(f"{BASE}/employees/tianshang/skills", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "readonly"
    assert data["employee"]["employee_id"] == "tianshang"
    assert {"skill_total", "high_risk_skill_count", "average_success_rate"} <= set(data["summary"])
    assert isinstance(data["skills"], list)
    assert any(row["employee_id"] == "tianshang" for row in data["skills"])


def test_ai_employee_skills_aggregates_task_stats(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add_all(
            [
                TaskCenterTask(title="success task", status="accepted", assigned_ai_employee_code="tianshang", assigned_ai_employee_name="天商"),
                TaskCenterTask(title="failed task", status="failed", assigned_ai_employee_code="tianshang", assigned_ai_employee_name="天商"),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get(f"{BASE}/employees/tianshang/skills", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["skills"]
    row = data["skills"][0]
    assert row["usage_count"] == 2
    assert row["success_count"] == 1
    assert row["failure_count"] == 1
    assert row["success_rate"] == 0.5
    assert row["risk_level"] == "high"


def test_ai_employee_skills_query_filters(client, owner_headers):
    response = client.get(f"{BASE}/skills?q=市场", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["skills"]
    assert all("市场" in row["skill_name"] or "市场" in row["employee_name"] for row in data["skills"])


def test_ai_employee_skills_is_readonly(client, owner_headers, test_db):
    db = test_db()
    try:
        before_task_count = db.query(TaskCenterTask).count()
        before_owner_role = db.query(User).filter(User.username == "owner").first().role
    finally:
        db.close()

    response = client.get(f"{BASE}/skills", headers=owner_headers)

    assert response.status_code == 200
    db = test_db()
    try:
        assert db.query(TaskCenterTask).count() == before_task_count
        assert db.query(User).filter(User.username == "owner").first().role == before_owner_role
    finally:
        db.close()


def test_ai_employee_skills_static_safety_boundaries():
    combined = ROUTER_FILE.read_text(encoding="utf-8") + SERVICE_FILE.read_text(encoding="utf-8")
    forbidden = [
        "OpenClaw",
        "/api/execution",
        "/api/brain/start",
        "ExecutionEngine",
        "TaskCenterTask(",
        ".add(",
        ".delete(",
        ".commit(",
    ]
    for text in forbidden:
        assert text not in combined
