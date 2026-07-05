from __future__ import annotations

import json

from backend.main import app
from backend.models import AiEmployee, TaskCenterTask


BASE = "/api/employee-capabilities"
SENSITIVE_KEYS = {
    "input_excerpt",
    "prompt_draft",
    "raw_text",
    "token",
    "cookie",
    "password",
    "secret",
    "database_url",
    "redis_url",
    "authorization",
    "bearer",
    "jwt_secret",
    "access_token",
    "refresh_token",
    "private_key",
}
EMPLOYEE_FIELDS = {
    "employee_code",
    "employee_name",
    "department",
    "legion",
    "role_title",
    "capability_summary",
    "capability_categories",
    "can_analyze",
    "can_read_image",
    "can_generate_image",
    "can_generate_video",
    "can_search_web",
    "can_write_code",
    "can_test",
    "can_audit",
    "can_deploy",
    "can_call_api",
    "can_use_browser",
    "can_use_database",
    "can_use_files",
    "can_use_tools",
    "allowed_tools",
    "allowed_models",
    "forbidden_actions",
    "requires_boss_confirmation",
    "risk_level",
    "maturity_level",
    "success_rate",
    "error_count",
    "task_count",
    "completed_task_count",
    "blocker_count",
    "audit_pass_count",
    "deploy_count",
    "last_activity_at",
    "last_upgrade_at",
    "last_upgrade_summary",
    "sop_count",
    "skill_count",
    "knowledge_base_count",
    "current_limitations",
    "next_upgrade_suggestion",
    "safety_flags",
}


def test_employee_capabilities_routes_registered():
    paths = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    expected = [
        f"{BASE}/overview",
        f"{BASE}/employees",
        f"{BASE}/employees/{{employee_code}}",
        f"{BASE}/models",
        f"{BASE}/tools",
        f"{BASE}/risks",
        f"{BASE}/missing-capabilities",
    ]
    for path in expected:
        assert path in paths
        assert paths[path] == {"GET"}


def test_employee_capabilities_requires_login(client):
    for path in capability_paths():
        response = client.get(path)
        assert response.status_code == 401


def test_employee_capabilities_rejects_low_privilege(client, viewer_headers):
    for path in capability_paths():
        response = client.get(path, headers=viewer_headers)
        assert response.status_code == 403


def test_employee_capabilities_allows_boss_owner_admin(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        for path in capability_paths():
            response = client.get(path, headers=headers)
            assert response.status_code == 200


def test_employee_capabilities_overview_schema(client, owner_headers):
    response = client.get(f"{BASE}/overview", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert {"summary", "recent_upgrades", "missing_capabilities", "safety_flags"} <= set(data)
    summary = data["summary"]
    assert {
        "total_employees",
        "configured_capabilities",
        "can_analyze_count",
        "can_read_image_count",
        "can_generate_image_count",
        "can_generate_video_count",
        "can_search_web_count",
        "can_write_code_count",
        "can_deploy_count",
        "requires_boss_confirmation_count",
        "high_risk_capability_count",
        "missing_capability_count",
        "average_maturity_level",
        "average_success_rate",
    } <= set(summary)
    assert isinstance(data["missing_capabilities"], list)
    assert isinstance(data["safety_flags"], list)


def test_employee_capabilities_employees_schema(client, owner_headers):
    response = client.get(f"{BASE}/employees", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert "employees" in data
    assert isinstance(data["employees"], list)
    assert data["employees"]
    assert_employee_shape(data["employees"][0])


def test_employee_capabilities_employee_detail_schema(client, owner_headers):
    response = client.get(f"{BASE}/employees/tianwang", headers=owner_headers)
    assert response.status_code == 200
    assert_employee_shape(response.json())


def test_employee_capabilities_models_schema(client, owner_headers):
    response = client.get(f"{BASE}/models", headers=owner_headers)
    assert response.status_code == 200
    models = response.json()["models"]
    assert models
    assert {"model_code", "model_name", "model_type", "best_for", "risk_level", "requires_boss_confirmation", "available_for_employees", "current_status"} <= set(models[0])


def test_employee_capabilities_tools_schema(client, owner_headers):
    response = client.get(f"{BASE}/tools", headers=owner_headers)
    assert response.status_code == 200
    tools = response.json()["tools"]
    assert tools
    assert {"tool_code", "tool_name", "tool_type", "allowed_for_employees", "forbidden_for_employees", "risk_level", "requires_boss_confirmation", "current_status", "safety_notes"} <= set(tools[0])


def test_employee_capabilities_risks_schema(client, owner_headers):
    response = client.get(f"{BASE}/risks", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert {"high_risk_tools", "high_risk_models", "high_risk_employees", "requires_boss_confirmation", "forbidden_actions", "missing_safety_rules", "safety_flags"} <= set(data)
    assert isinstance(data["high_risk_employees"], list)


def test_employee_capabilities_missing_schema(client, owner_headers):
    response = client.get(f"{BASE}/missing-capabilities", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert "missing_capabilities" in data
    assert isinstance(data["missing_capabilities"], list)
    if data["missing_capabilities"]:
        assert {"employee_code", "employee_name", "missing_capability", "impact", "suggested_upgrade", "priority", "requires_boss_confirmation"} <= set(data["missing_capabilities"][0])


def test_employee_capabilities_no_sensitive_fields(client, owner_headers):
    for path in capability_paths():
        response = client.get(path, headers=owner_headers)
        assert response.status_code == 200
        payload = json.dumps(response.json(), ensure_ascii=False).lower()
        for key in SENSITIVE_KEYS:
            assert key not in payload


def test_employee_capabilities_no_write_routes():
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith(BASE):
            assert getattr(route, "methods", set()) == {"GET"}


def test_employee_capabilities_does_not_modify_task_status(client, owner_headers, test_db):
    db = test_db()
    try:
        task = TaskCenterTask(
            title="Capability read only task",
            description="status should not change",
            status="created",
            assigned_ai_employee_code="tianwang",
            assigned_ai_employee_name="天王：后端开发中心",
        )
        db.add(task)
        db.commit()
        task_id = task.id
    finally:
        db.close()

    response = client.get(f"{BASE}/employees/tianwang", headers=owner_headers)
    assert response.status_code == 200

    db = test_db()
    try:
        assert db.get(TaskCenterTask, task_id).status == "created"
    finally:
        db.close()


def test_employee_capabilities_safe_defaults(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add(
            AiEmployee(
                employee_code="odd_capability_employee",
                employee_name="异常能力员工",
                legion=None,
                duty=None,
                status="active",
                task_types=None,
                default_permissions=None,
                is_legacy=False,
                sort_order=999,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(f"{BASE}/employees/odd_capability_employee", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert_employee_shape(data)
    assert data["employee_name"] == "异常能力员工"
    assert data["allowed_tools"] == []
    assert data["current_limitations"]


def capability_paths():
    return [
        f"{BASE}/overview",
        f"{BASE}/employees",
        f"{BASE}/employees/tianwang",
        f"{BASE}/models",
        f"{BASE}/tools",
        f"{BASE}/risks",
        f"{BASE}/missing-capabilities",
    ]


def assert_employee_shape(data):
    assert EMPLOYEE_FIELDS <= set(data)
    for key in [
        "capability_categories",
        "allowed_tools",
        "allowed_models",
        "forbidden_actions",
        "requires_boss_confirmation",
        "current_limitations",
        "safety_flags",
    ]:
        assert isinstance(data[key], list)
    for key in [
        "can_analyze",
        "can_read_image",
        "can_generate_image",
        "can_generate_video",
        "can_search_web",
        "can_write_code",
        "can_test",
        "can_audit",
        "can_deploy",
        "can_call_api",
        "can_use_browser",
        "can_use_database",
        "can_use_files",
        "can_use_tools",
    ]:
        assert isinstance(data[key], bool)
