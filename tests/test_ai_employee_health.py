from pathlib import Path

from backend.evolution_models import EmployeeGrowth, RiskEvent
from backend.models import AiEmployee, KnowledgeArticle, PromptLibrary, SopLibrary, TaskCenterTask, User


BASE = "/api/ai-employee-health/overview"
ROUTER_FILE = Path("backend/routers/ai_employee_health.py")
SERVICE_FILE = Path("backend/services/ai_employee_health_overview.py")


def test_ai_employee_health_requires_login(client):
    response = client.get(BASE)

    assert response.status_code == 401


def test_ai_employee_health_permissions(client, owner_headers, admin_headers, boss_headers, viewer_headers, operator_headers):
    for headers in [owner_headers, admin_headers, boss_headers, viewer_headers]:
        client.cookies.clear()
        response = client.get(BASE, headers=headers)
        assert response.status_code == 200

    client.cookies.clear()
    forbidden = client.get(BASE, headers=operator_headers)
    assert forbidden.status_code == 403


def test_ai_employee_health_returns_readonly_shape(client, owner_headers):
    response = client.get(BASE, headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "readonly"
    assert data["version"] == "ai_employee_health_overview_v1"
    for key in [
        "status",
        "overall_score",
        "generated_at",
        "alert_count",
        "employees",
        "modules",
        "apis",
        "freshness",
        "score",
        "alerts",
        "empty_state",
        "security",
        "data_sources",
    ]:
        assert key in data

    assert {"total", "working", "idle", "frozen", "offline", "departments"} <= set(data["employees"])
    assert {"overall", "module_score", "api_score", "freshness_score", "security_score", "alert_penalty", "breakdown"} <= set(data["score"])
    assert {row["module_key"] for row in data["modules"]} >= {
        "ai_workforce",
        "skill_center",
        "memory_center",
        "growth_center",
        "audit_center",
        "meeting_room",
        "task_center",
    }
    assert {row["path"] for row in data["apis"]} >= {
        "/api/ai-employee-health/overview",
        "/api/ai-employee-ecosystem/overview",
        "/api/health",
        "/api/ready",
    }


def test_ai_employee_health_security_flags(client, owner_headers):
    response = client.get(BASE, headers=owner_headers)

    assert response.status_code == 200
    security = response.json()["security"]
    assert security["readonly"] is True
    assert security["auto_repair_enabled"] is False
    assert security["auto_execute_enabled"] is False
    assert security["execution_engine_called"] is False
    assert security["openclaw_connected"] is False
    assert security["n8n_connected"] is False
    assert security["permission_mutation_enabled"] is False
    assert security["task_mutation_enabled"] is False
    assert security["high_risk_requires"] == {"boss_confirm": True, "security_audited": True}


def test_ai_employee_health_aggregates_existing_ecosystem_data(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add_all(
            [
                TaskCenterTask(
                    title="Health running task",
                    status="running",
                    assigned_ai_employee_code="tianwang",
                    assigned_ai_employee_name="天王：后端开发中心",
                ),
                TaskCenterTask(title="Health blocked task", status="failed", assigned_ai_employee_code="tianwang"),
                KnowledgeArticle(title="Health Article", content="body"),
                SopLibrary(title="Health SOP"),
                PromptLibrary(title="Health Prompt"),
                EmployeeGrowth(employee_code="tianwang", score=88, growth_level="L4", success_rate=91),
                RiskEvent(employee_code="tianwang", event_type="blocked", risk_level="high"),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get(BASE, headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    modules = {row["module_key"]: row for row in data["modules"]}
    assert data["employees"]["total"] == 2
    assert data["employees"]["working"] == 1
    assert modules["ai_workforce"]["status"] == "connected"
    assert modules["memory_center"]["count"] >= 3
    assert modules["growth_center"]["status"] == "connected"
    assert modules["audit_center"]["status"] == "degraded"
    assert modules["audit_center"]["risk_level"] == "high"
    assert modules["task_center"]["status"] == "degraded"
    assert data["alert_count"] >= 2
    assert any(row["level"] == "high" and row["requires_boss_confirm"] is True for row in data["alerts"])


def test_ai_employee_health_is_readonly(client, owner_headers, test_db):
    db = test_db()
    try:
        before_task_count = db.query(TaskCenterTask).count()
        before_employee_count = db.query(AiEmployee).count()
        before_owner_role = db.query(User).filter(User.username == "owner").first().role
    finally:
        db.close()

    response = client.get(BASE, headers=owner_headers)

    assert response.status_code == 200
    db = test_db()
    try:
        assert db.query(TaskCenterTask).count() == before_task_count
        assert db.query(AiEmployee).count() == before_employee_count
        assert db.query(User).filter(User.username == "owner").first().role == before_owner_role
    finally:
        db.close()


def test_ai_employee_health_static_safety_boundaries():
    router = ROUTER_FILE.read_text(encoding="utf-8")
    service = SERVICE_FILE.read_text(encoding="utf-8")
    combined = router + service

    forbidden = [
        "/api/execution",
        "/api/brain/start",
        "employee-evolution/analyze",
        "analyze_employee(",
        "TaskCenterTask(",
        ".add(",
        ".delete(",
        ".commit(",
        "requests.",
        "httpx.",
        "connect_openclaw",
        "n8n_url",
    ]
    for text in forbidden:
        assert text not in combined
