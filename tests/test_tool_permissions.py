from __future__ import annotations

import json
from pathlib import Path

from backend.main import app
from backend.models import TaskCenterTask
from backend.routers import tool_permissions


BASE = "/api/tool-permissions"
EXPECTED_ROUTES = [
    f"{BASE}/overview",
    f"{BASE}/tools",
    f"{BASE}/tools/{{tool_code}}",
    f"{BASE}/employees",
    f"{BASE}/employees/{{employee_code}}",
    f"{BASE}/categories",
    f"{BASE}/high-risk-tools",
    f"{BASE}/boss-confirm-required",
    f"{BASE}/auto-execute-disabled",
    f"{BASE}/missing-configs",
    f"{BASE}/automation-candidates",
]
REQUEST_PATHS = [
    f"{BASE}/overview",
    f"{BASE}/tools",
    f"{BASE}/tools/gpt",
    f"{BASE}/employees",
    f"{BASE}/employees/tiantong",
    f"{BASE}/categories",
    f"{BASE}/high-risk-tools",
    f"{BASE}/boss-confirm-required",
    f"{BASE}/auto-execute-disabled",
    f"{BASE}/missing-configs",
    f"{BASE}/automation-candidates",
]
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
    "session",
    "private_key",
    "api key",
}
TOOL_FIELDS = {
    "tool_code",
    "tool_name",
    "tool_category",
    "description",
    "allowed_employees",
    "forbidden_employees",
    "allowed_departments",
    "forbidden_departments",
    "permission_level",
    "risk_level",
    "cost_level",
    "requires_boss_confirmation",
    "can_read",
    "can_generate_draft",
    "can_execute",
    "can_auto_execute",
    "can_modify_data",
    "can_spend_money",
    "can_access_external_account",
    "can_access_sensitive_data",
    "required_model_level",
    "required_employee_maturity",
    "required_audit_level",
    "fallback_tool",
    "safety_notes",
    "current_status",
    "next_upgrade_suggestion",
}
EMPLOYEE_FIELDS = {
    "employee_code",
    "employee_name",
    "department",
    "allowed_tools",
    "forbidden_tools",
    "high_risk_tools",
    "boss_confirm_required_tools",
    "view_only_tools",
    "draft_only_tools",
    "automation_candidate_tools",
    "missing_tool_configs",
    "safety_notes",
    "next_upgrade_suggestion",
}
CATEGORY_FIELDS = {
    "category_code",
    "category_name",
    "description",
    "risk_level",
    "default_permission_level",
    "safety_notes",
}


def test_tool_permissions_routes_registered():
    paths = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    for path in EXPECTED_ROUTES:
        assert path in paths
        assert paths[path] == {"GET"}


def test_tool_permissions_requires_login(client):
    for path in REQUEST_PATHS:
        assert client.get(path).status_code == 401


def test_tool_permissions_rejects_low_privilege(client, viewer_headers):
    for path in REQUEST_PATHS:
        assert client.get(path, headers=viewer_headers).status_code == 403


def test_tool_permissions_allows_boss_owner_admin(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        for path in REQUEST_PATHS:
            assert client.get(path, headers=headers).status_code == 200


def test_tool_permissions_overview_schema(client, owner_headers):
    response = client.get(f"{BASE}/overview", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert {
        "total_tools",
        "total_categories",
        "high_risk_tools",
        "critical_tools",
        "boss_confirm_required_count",
        "auto_execute_disabled_count",
        "automation_candidate_count",
        "missing_config_count",
        "employees_with_tool_profile",
        "safety_summary",
        "next_upgrade_suggestion",
    } <= set(data)
    assert data["total_categories"] >= 9
    assert data["total_tools"] >= 60
    assert isinstance(data["safety_summary"], list)


def test_tool_permissions_tools_schema_and_rules(client, owner_headers):
    response = client.get(f"{BASE}/tools", headers=owner_headers)
    assert response.status_code == 200
    tools = response.json()["tools"]
    assert TOOL_FIELDS <= set(tools[0])
    assert {row["tool_code"] for row in tools} >= {"gpt", "codex", "github", "deploy_center", "shell", "payment", "account_credential_management"}
    assert all(row["can_execute"] is False for row in tools)
    assert all(row["can_auto_execute"] is False for row in tools)
    assert all(row["can_spend_money"] is False for row in tools)
    assert all(row["requires_boss_confirmation"] is True for row in tools if row["risk_level"] == "critical")
    assert all(row["can_auto_execute"] is False for row in tools if row["risk_level"] in {"high", "critical"})


def test_tool_permissions_categories_schema(client, owner_headers):
    response = client.get(f"{BASE}/categories", headers=owner_headers)
    assert response.status_code == 200
    categories = response.json()["categories"]
    assert len(categories) >= 9
    assert CATEGORY_FIELDS <= set(categories[0])
    assert {row["category_code"] for row in categories} >= {
        "model_tools",
        "development_tools",
        "deployment_tools",
        "browser_tools",
        "ecommerce_tools",
        "content_tools",
        "data_tools",
        "notification_tools",
        "finance_security_tools",
    }


def test_tool_permissions_employees_schema(client, owner_headers):
    response = client.get(f"{BASE}/employees", headers=owner_headers)
    assert response.status_code == 200
    employees = response.json()["employees"]
    assert len(employees) >= 20
    assert EMPLOYEE_FIELDS <= set(employees[0])
    assert {row["employee_code"] for row in employees} >= {"tiantong", "tianwang", "tianyan_frontend", "tianlian"}


def test_tool_permissions_detail_404(client, owner_headers):
    assert client.get(f"{BASE}/tools/not_exists", headers=owner_headers).status_code == 404
    assert client.get(f"{BASE}/employees/not_exists", headers=owner_headers).status_code == 404


def test_tool_permissions_filtered_endpoints(client, owner_headers):
    high_risk = client.get(f"{BASE}/high-risk-tools", headers=owner_headers).json()["tools"]
    boss_confirm = client.get(f"{BASE}/boss-confirm-required", headers=owner_headers).json()["tools"]
    disabled = client.get(f"{BASE}/auto-execute-disabled", headers=owner_headers).json()["tools"]
    missing = client.get(f"{BASE}/missing-configs", headers=owner_headers).json()["missing_configs"]
    candidates = client.get(f"{BASE}/automation-candidates", headers=owner_headers).json()["tools"]
    assert high_risk and all(row["risk_level"] in {"high", "critical"} for row in high_risk)
    assert boss_confirm and all(row["requires_boss_confirmation"] is True for row in boss_confirm)
    assert disabled and all(row["can_auto_execute"] is False for row in disabled)
    assert isinstance(missing, list)
    assert candidates and all(row["permission_level"] == "automation_candidate" for row in candidates)


def test_tool_permissions_no_sensitive_fields(client, owner_headers):
    for path in REQUEST_PATHS:
        response = client.get(path, headers=owner_headers)
        assert response.status_code == 200
        payload = json.dumps(response.json(), ensure_ascii=False).lower()
        for key in SENSITIVE_KEYS:
            assert key not in payload


def test_tool_permissions_no_write_routes():
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith(BASE):
            assert getattr(route, "methods", set()) == {"GET"}


def test_tool_permissions_does_not_modify_task_status(client, owner_headers, test_db):
    db = test_db()
    try:
        task = TaskCenterTask(title="Tool permissions readonly", description="unchanged", status="created")
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


def test_tool_permissions_safe_defaults():
    assert tool_permissions.safe_text({"unknown": "full object"}, "fallback") == "fallback"
    assert tool_permissions.safe_text({"reason": ["a", {"message": "b"}, None]}, "fallback") == "a、b"
    assert tool_permissions.safe_text_list(["a", {"title": "b"}, [1, True], None]) == ["a", "b", "1", "是"]


def test_tool_permissions_source_has_no_execution_calls():
    source = Path("backend/routers/tool_permissions.py").read_text()
    forbidden = [
        "subprocess",
        "os.system",
        "shell=True",
        "requests.post",
        "http://",
        "https://",
        "eval(",
        "exec(",
        ".add(",
        ".commit(",
        ".flush(",
    ]
    for needle in forbidden:
        assert needle not in source
