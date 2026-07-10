from pathlib import Path

from backend.models import TaskCenterTask, User


BASE = "/api/ai-employee-ecosystem/overview"
ROUTER_FILE = Path("backend/routers/ai_employee_ecosystem.py")
SERVICE_FILE = Path("backend/services/ai_employee_ecosystem_overview.py")


def test_ai_employee_ecosystem_overview_requires_login(client):
    response = client.get(BASE)

    assert response.status_code == 401


def test_ai_employee_ecosystem_overview_permissions(client, owner_headers, admin_headers, boss_headers, viewer_headers, operator_headers):
    for headers in [owner_headers, admin_headers, boss_headers, viewer_headers]:
        client.cookies.clear()
        response = client.get(BASE, headers=headers)
        assert response.status_code == 200

    client.cookies.clear()
    forbidden = client.get(BASE, headers=operator_headers)
    assert forbidden.status_code == 403


def test_ai_employee_ecosystem_overview_returns_readonly_shape(client, owner_headers):
    response = client.get(BASE, headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "readonly"
    for key in [
        "employees",
        "capability",
        "skill",
        "memory",
        "growth",
        "audit",
        "meeting",
        "task",
        "centers",
        "empty_state",
        "security",
        "data_sources",
        "errors",
    ]:
        assert key in data

    assert {"total", "working", "idle", "frozen", "offline", "departments"} <= set(data["employees"])
    assert {"total", "enabled", "reviewing", "high_risk", "sop_count", "prompt_count"} <= set(data["skill"])
    assert {"Experience", "DecisionHistory", "LearningRecord", "SuccessCase", "FailureCase"} <= set(data["memory"]["types"])
    assert {"total", "running", "pending", "blocked", "review_pending"} <= set(data["task"])


def test_ai_employee_ecosystem_overview_security_flags(client, owner_headers):
    response = client.get(BASE, headers=owner_headers)

    assert response.status_code == 200
    security = response.json()["security"]
    assert security["readonly"] is True
    assert security["execution_engine_called"] is False
    assert security["openclaw_connected"] is False
    assert security["n8n_connected"] is False
    assert security["auto_execute"] is False
    assert security["high_risk_requires"] == {"boss_confirm": True, "security_audited": True}


def test_ai_employee_ecosystem_overview_is_readonly(client, owner_headers, test_db):
    db = test_db()
    try:
        before_task_count = db.query(TaskCenterTask).count()
        before_owner_role = db.query(User).filter(User.username == "owner").first().role
    finally:
        db.close()

    response = client.get(BASE, headers=owner_headers)

    assert response.status_code == 200
    db = test_db()
    try:
        assert db.query(TaskCenterTask).count() == before_task_count
        assert db.query(User).filter(User.username == "owner").first().role == before_owner_role
    finally:
        db.close()


def test_ai_employee_ecosystem_overview_static_safety_boundaries():
    router = ROUTER_FILE.read_text(encoding="utf-8")
    service = SERVICE_FILE.read_text(encoding="utf-8")
    combined = router + service

    forbidden = [
        "OpenClaw",
        "/api/execution",
        "/api/brain/start",
        "employee-evolution/analyze",
        "analyze_employee(",
        "TaskCenterTask(",
        ".add(",
        ".delete(",
        ".commit(",
    ]
    for text in forbidden:
        assert text not in combined
