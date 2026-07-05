from __future__ import annotations

import json
from pathlib import Path

from backend.main import app
from backend.models import TaskCenterTask
from backend.routers import model_routing


BASE = "/api/model-routing"
EXPECTED_ROUTES = [
    f"{BASE}/overview",
    f"{BASE}/models",
    f"{BASE}/models/{{model_code}}",
    f"{BASE}/employees",
    f"{BASE}/employees/{{employee_code}}",
    f"{BASE}/task-types",
    f"{BASE}/recommendations",
    f"{BASE}/risks",
    f"{BASE}/fallbacks",
]
REQUEST_PATHS = [
    f"{BASE}/overview",
    f"{BASE}/models",
    f"{BASE}/models/gpt_5_5_thinking",
    f"{BASE}/employees",
    f"{BASE}/employees/tianwang",
    f"{BASE}/task-types",
    f"{BASE}/recommendations",
    f"{BASE}/risks",
    f"{BASE}/fallbacks",
]
SENSITIVE_KEYS = {
    "token",
    "secret",
    "api key",
    "authorization",
    "bearer",
    "database_url",
    "redis_url",
    "jwt_secret",
    "access_token",
    "refresh_token",
    "session",
    "private_key",
    "input_excerpt",
    "prompt_draft",
    "raw_text",
}
MODEL_FIELDS = {
    "model_code",
    "model_name",
    "provider",
    "model_type",
    "best_for",
    "not_good_for",
    "cost_level",
    "risk_level",
    "speed_level",
    "quality_level",
    "reasoning_level",
    "coding_level",
    "vision_level",
    "image_generation_level",
    "video_generation_level",
    "tool_call_level",
    "recommended_employees",
    "recommended_task_types",
    "fallback_models",
    "requires_boss_confirmation",
    "can_auto_call",
    "current_status",
    "safety_notes",
}
TASK_TYPE_FIELDS = {
    "task_type",
    "task_name",
    "primary_model",
    "backup_models",
    "forbidden_models",
    "recommended_reason",
    "cost_level",
    "risk_level",
    "requires_boss_confirmation",
    "can_auto_call",
    "safety_notes",
}
EMPLOYEE_FIELDS = {
    "employee_code",
    "employee_name",
    "department",
    "primary_model",
    "backup_models",
    "allowed_models",
    "forbidden_models",
    "recommended_task_types",
    "model_selection_reason",
    "cost_control_level",
    "risk_level",
    "requires_boss_confirmation",
    "can_auto_call",
    "safety_notes",
}


def test_model_routing_routes_registered():
    paths = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    for path in EXPECTED_ROUTES:
        assert path in paths
        assert paths[path] == {"GET"}


def test_model_routing_requires_login(client):
    for path in REQUEST_PATHS:
        response = client.get(path)
        assert response.status_code == 401


def test_model_routing_rejects_low_privilege(client, viewer_headers):
    for path in REQUEST_PATHS:
        response = client.get(path, headers=viewer_headers)
        assert response.status_code == 403


def test_model_routing_allows_boss_owner_admin(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        for path in REQUEST_PATHS:
            response = client.get(path, headers=headers)
            assert response.status_code == 200


def test_model_routing_overview_schema(client, owner_headers):
    response = client.get(f"{BASE}/overview", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert {
        "total_models",
        "active_models",
        "high_cost_models",
        "high_risk_models",
        "boss_confirmation_required_count",
        "employees_with_model_profile",
        "task_types_configured",
        "auto_call_disabled_count",
        "fallback_strategy_count",
        "recommended_model_summary",
        "risk_summary",
        "cost_summary",
        "safety_flags",
        "next_upgrade_suggestions",
    } <= set(data)
    assert data["total_models"] >= 10
    assert data["task_types_configured"] >= 18
    assert isinstance(data["recommended_model_summary"], list)
    assert isinstance(data["safety_flags"], list)


def test_model_routing_models_schema(client, owner_headers):
    response = client.get(f"{BASE}/models", headers=owner_headers)
    assert response.status_code == 200
    models = response.json()["models"]
    assert len(models) >= 10
    assert MODEL_FIELDS <= set(models[0])
    assert all(model["can_auto_call"] is False for model in models)
    assert client.get(f"{BASE}/models/gpt_5_5_thinking", headers=owner_headers).status_code == 200


def test_model_routing_employees_schema(client, owner_headers):
    response = client.get(f"{BASE}/employees", headers=owner_headers)
    assert response.status_code == 200
    employees = response.json()["employees"]
    assert len(employees) >= 20
    assert EMPLOYEE_FIELDS <= set(employees[0])
    assert all(employee["can_auto_call"] is False for employee in employees)
    assert client.get(f"{BASE}/employees/tianwang", headers=owner_headers).status_code == 200


def test_model_routing_task_types_schema(client, owner_headers):
    response = client.get(f"{BASE}/task-types", headers=owner_headers)
    assert response.status_code == 200
    task_types = response.json()["task_types"]
    assert len(task_types) >= 18
    assert TASK_TYPE_FIELDS <= set(task_types[0])
    assert all(row["can_auto_call"] is False for row in task_types)


def test_model_routing_recommendations_risks_fallbacks_schema(client, owner_headers):
    recommendations = client.get(f"{BASE}/recommendations", headers=owner_headers).json()["recommendations"]
    risks = client.get(f"{BASE}/risks", headers=owner_headers).json()
    fallbacks = client.get(f"{BASE}/fallbacks", headers=owner_headers).json()["fallbacks"]
    assert recommendations
    assert risks["disabled_auto_call"]
    assert fallbacks
    assert all(row["can_auto_call"] is False for row in recommendations)
    assert all(row["can_auto_call"] is False and row["can_auto_switch"] is False for row in fallbacks)


def test_model_routing_no_sensitive_fields(client, owner_headers):
    for path in REQUEST_PATHS:
        response = client.get(path, headers=owner_headers)
        assert response.status_code == 200
        payload = json.dumps(response.json(), ensure_ascii=False).lower()
        for key in SENSITIVE_KEYS:
            assert key not in payload


def test_model_routing_no_write_routes():
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith(BASE):
            assert getattr(route, "methods", set()) == {"GET"}


def test_model_routing_does_not_modify_task_status(client, owner_headers, test_db):
    db = test_db()
    try:
        task = TaskCenterTask(title="Model routing readonly", description="unchanged", status="created")
        db.add(task)
        db.commit()
        task_id = task.id
    finally:
        db.close()

    response = client.get(f"{BASE}/overview", headers=owner_headers)
    assert response.status_code == 200

    db = test_db()
    try:
        assert db.get(TaskCenterTask, task_id).status == "created"
    finally:
        db.close()


def test_model_routing_safe_defaults():
    assert model_routing.safe_text({"unknown": "full object"}, "fallback") == "fallback"
    assert model_routing.safe_text({"reason": ["a", {"message": "b"}, None]}, "fallback") == "a、b"
    assert model_routing.safe_text_list(["a", {"title": "b"}, [1, True], None]) == ["a", "b", "1", "是"]


def test_model_routing_source_has_no_dangerous_calls():
    source = Path("backend/routers/model_routing.py").read_text()
    forbidden = [
        "subprocess",
        "os.system",
        "shell=True",
        "requests.post",
        "http://",
        "https://",
        "docker",
        "systemctl",
        "deploy.sh",
        "git push",
        "git commit",
        "eval(",
        "exec(",
        ".add(",
        ".commit(",
        ".flush(",
    ]
    for needle in forbidden:
        assert needle not in source
