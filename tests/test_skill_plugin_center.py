from __future__ import annotations

import json
from pathlib import Path

from backend.main import app


BASE = "/api/skill-plugin-center"
EXPECTED_ROUTES = [
    f"{BASE}/overview",
    f"{BASE}/skills",
    f"{BASE}/skills/{{skill_code}}",
    f"{BASE}/plugins",
    f"{BASE}/plugins/{{plugin_code}}",
    f"{BASE}/mcps",
    f"{BASE}/mcps/{{mcp_code}}",
    f"{BASE}/external-tools",
    f"{BASE}/external-tools/{{tool_code}}",
    f"{BASE}/employees",
    f"{BASE}/employees/{{employee_code}}",
    f"{BASE}/departments",
    f"{BASE}/risk-tools",
    f"{BASE}/missing-configs",
    f"{BASE}/next-upgrades",
]
REQUEST_PATHS = [
    f"{BASE}/overview",
    f"{BASE}/skills",
    f"{BASE}/skills/skill_prompt_engineering",
    f"{BASE}/plugins",
    f"{BASE}/plugins/typeless_dictation",
    f"{BASE}/mcps",
    f"{BASE}/mcps/github_mcp",
    f"{BASE}/external-tools",
    f"{BASE}/external-tools/github",
    f"{BASE}/employees",
    f"{BASE}/employees/tiantong",
    f"{BASE}/departments",
    f"{BASE}/risk-tools",
    f"{BASE}/missing-configs",
    f"{BASE}/next-upgrades",
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
SKILL_FIELDS = {
    "skill_code",
    "skill_name",
    "skill_category",
    "suitable_employees",
    "suitable_departments",
    "risk_level",
    "cost_level",
    "permission_level",
    "requires_boss_confirmation",
    "can_auto_install",
    "can_auto_enable",
    "can_auto_execute",
    "safety_notes",
}
PLUGIN_FIELDS = {
    "plugin_code",
    "plugin_name",
    "plugin_category",
    "official_url",
    "vendor",
    "install_method",
    "supported_platform",
    "risk_level",
    "cost_level",
    "requires_boss_confirmation",
    "can_auto_download",
    "can_auto_install",
    "can_auto_enable",
    "can_auto_execute",
    "safety_notes",
}
MCP_FIELDS = {
    "mcp_code",
    "mcp_name",
    "capability",
    "target_employee",
    "target_department",
    "risk_level",
    "permission_scope",
    "can_read",
    "can_write",
    "can_execute",
    "can_spend_money",
    "safety_notes",
}
EXTERNAL_TOOL_FIELDS = {
    "tool_code",
    "tool_name",
    "tool_category",
    "vendor",
    "official_url",
    "capability",
    "target_employee",
    "target_department",
    "risk_level",
    "permission_scope",
    "requires_boss_confirmation",
    "can_read",
    "can_write",
    "can_execute",
    "can_spend_money",
    "can_auto_download",
    "can_auto_install",
    "can_auto_enable",
    "can_auto_execute",
    "safety_notes",
}
EMPLOYEE_FIELDS = {
    "employee_code",
    "employee_name",
    "department",
    "recommended_skills",
    "recommended_plugins",
    "recommended_mcps",
    "recommended_external_tools",
    "forbidden_tools",
    "boss_confirm_required_tools",
}


def test_skill_plugin_center_routes_registered():
    paths = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    for path in EXPECTED_ROUTES:
        assert path in paths
        assert paths[path] == {"GET"}


def test_skill_plugin_center_requires_login(client):
    for path in REQUEST_PATHS:
        assert client.get(path).status_code == 401


def test_skill_plugin_center_rejects_low_privilege(client, viewer_headers):
    for path in REQUEST_PATHS:
        assert client.get(path, headers=viewer_headers).status_code == 403


def test_skill_plugin_center_allows_boss_owner_admin(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        for path in REQUEST_PATHS:
            assert client.get(path, headers=headers).status_code == 200


def test_skill_plugin_center_overview_schema(client, owner_headers):
    data = client.get(f"{BASE}/overview", headers=owner_headers).json()
    assert {
        "total_skills",
        "total_plugins",
        "total_mcps",
        "total_external_tools",
        "high_risk_count",
        "boss_confirmation_required_count",
        "auto_execute_disabled_count",
        "research_candidate_count",
        "missing_config_count",
        "safe_readonly_mode",
        "can_auto_execute_all",
        "can_auto_install_all",
        "can_auto_enable_all",
    } <= set(data)
    assert data["total_skills"] >= 10
    assert data["total_plugins"] >= 10
    assert data["total_mcps"] >= 8
    assert data["total_external_tools"] >= 18
    assert data["safe_readonly_mode"] is True
    assert data["can_auto_execute_all"] is False
    assert data["can_auto_install_all"] is False
    assert data["can_auto_enable_all"] is False


def test_skill_plugin_center_skills_schema_and_404(client, owner_headers):
    rows = client.get(f"{BASE}/skills", headers=owner_headers).json()["skills"]
    assert SKILL_FIELDS <= set(rows[0])
    assert {row["skill_code"] for row in rows} >= {"skill_prompt_engineering", "skill_backend_debug", "skill_deploy_check"}
    assert all(row["can_auto_install"] is False for row in rows)
    assert all(row["can_auto_enable"] is False for row in rows)
    assert all(row["can_auto_execute"] is False for row in rows)
    detail = client.get(f"{BASE}/skills/{rows[0]['skill_code']}", headers=owner_headers)
    assert detail.status_code == 200
    assert SKILL_FIELDS <= set(detail.json())
    response = client.get(f"{BASE}/skills/not_exists", headers=owner_headers)
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "not_found"


def test_skill_plugin_center_plugins_schema_and_404(client, owner_headers):
    rows = client.get(f"{BASE}/plugins", headers=owner_headers).json()["plugins"]
    assert PLUGIN_FIELDS <= set(rows[0])
    assert {row["plugin_code"] for row in rows} >= {"typeless_dictation", "github_desktop", "local_file_indexer"}
    assert all(row["can_auto_download"] is False for row in rows)
    assert all(row["can_auto_install"] is False for row in rows)
    assert all(row["can_auto_enable"] is False for row in rows)
    assert all(row["can_auto_execute"] is False for row in rows)
    detail = client.get(f"{BASE}/plugins/{rows[0]['plugin_code']}", headers=owner_headers)
    assert detail.status_code == 200
    assert PLUGIN_FIELDS <= set(detail.json())
    response = client.get(f"{BASE}/plugins/not_exists", headers=owner_headers)
    assert response.status_code == 404
    assert response.json()["detail"]["kind"] == "plugin"


def test_skill_plugin_center_mcps_schema_and_404(client, owner_headers):
    rows = client.get(f"{BASE}/mcps", headers=owner_headers).json()["mcps"]
    assert MCP_FIELDS <= set(rows[0])
    assert {row["mcp_code"] for row in rows} >= {"github_mcp", "filesystem_mcp", "playwright_mcp"}
    assert all(row["can_write"] is False for row in rows)
    assert all(row["can_execute"] is False for row in rows)
    assert all(row["can_spend_money"] is False for row in rows)
    detail = client.get(f"{BASE}/mcps/{rows[0]['mcp_code']}", headers=owner_headers)
    assert detail.status_code == 200
    assert MCP_FIELDS <= set(detail.json())
    response = client.get(f"{BASE}/mcps/not_exists", headers=owner_headers)
    assert response.status_code == 404
    assert response.json()["detail"]["kind"] == "mcp"


def test_skill_plugin_center_external_tools_schema_and_404(client, owner_headers):
    rows = client.get(f"{BASE}/external-tools", headers=owner_headers).json()["external_tools"]
    assert EXTERNAL_TOOL_FIELDS <= set(rows[0])
    assert {row["tool_code"] for row in rows} >= {"github", "docker", "shell", "openai_api", "claude_api", "1688_search"}
    assert all(row["can_write"] is False for row in rows)
    assert all(row["can_execute"] is False for row in rows)
    assert all(row["can_spend_money"] is False for row in rows)
    assert all(row["can_auto_download"] is False for row in rows)
    assert all(row["can_auto_install"] is False for row in rows)
    assert all(row["can_auto_enable"] is False for row in rows)
    assert all(row["can_auto_execute"] is False for row in rows)
    detail = client.get(f"{BASE}/external-tools/{rows[0]['tool_code']}", headers=owner_headers)
    assert detail.status_code == 200
    assert EXTERNAL_TOOL_FIELDS <= set(detail.json())
    response = client.get(f"{BASE}/external-tools/not_exists", headers=owner_headers)
    assert response.status_code == 404
    assert response.json()["detail"]["kind"] == "external_tool"


def test_skill_plugin_center_employees_departments_and_filtered_schemas(client, owner_headers):
    employees = client.get(f"{BASE}/employees", headers=owner_headers).json()["employees"]
    departments = client.get(f"{BASE}/departments", headers=owner_headers).json()["departments"]
    risk_tools = client.get(f"{BASE}/risk-tools", headers=owner_headers).json()["risk_tools"]
    missing = client.get(f"{BASE}/missing-configs", headers=owner_headers).json()["missing_configs"]
    upgrades = client.get(f"{BASE}/next-upgrades", headers=owner_headers).json()["next_upgrades"]
    assert EMPLOYEE_FIELDS <= set(employees[0])
    assert {row["employee_code"] for row in employees} >= {"tiantong", "tianwang", "tiandun_ops"}
    assert {"department", "recommended_skills", "recommended_external_tools", "forbidden_tools"} <= set(departments[0])
    assert {"tool_code", "risk_type", "forbidden_reason", "can_auto_execute"} <= set(risk_tools[0])
    assert all(row["can_auto_execute"] is False for row in risk_tools)
    assert {"target_type", "target_code", "missing_fields", "suggested_fix", "risk_level"} <= set(missing[0])
    assert {"upgrade_code", "title", "target_module", "forbidden_actions", "acceptance_notes"} <= set(upgrades[0])
    response = client.get(f"{BASE}/employees/not_exists", headers=owner_headers)
    assert response.status_code == 404
    assert response.json()["detail"]["kind"] == "employee"


def test_skill_plugin_center_no_write_routes():
    paths = [getattr(route, "path", "") for route in app.routes if "/api/skill-plugin-center" in getattr(route, "path", "")]
    assert len(paths) == len(EXPECTED_ROUTES)
    for route in app.routes:
        if "/api/skill-plugin-center" in getattr(route, "path", ""):
            assert getattr(route, "methods", set()) == {"GET"}


def test_skill_plugin_center_no_sensitive_fields(client, owner_headers):
    for path in REQUEST_PATHS:
        response = client.get(path, headers=owner_headers)
        assert response.status_code == 200
        payload = json.dumps(response.json(), ensure_ascii=False).lower()
        for key in SENSITIVE_KEYS:
            assert key not in payload


def test_skill_plugin_center_no_dangerous_router_calls():
    source = Path("backend/routers/skill_plugin_center.py").read_text()
    forbidden_snippets = [
        "@router.post",
        "@router.patch",
        "@router.put",
        "@router.delete",
        "db.add",
        "db.commit",
        "db.flush",
        "subprocess",
        "os.system",
        "shell=True",
        "requests.post",
        "git push",
        "git commit",
        "systemctl",
        "Docker socket",
    ]
    for snippet in forbidden_snippets:
        assert snippet not in source
