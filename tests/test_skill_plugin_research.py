from __future__ import annotations

import json
from pathlib import Path

from backend.main import app


BASE = "/api/skill-plugin-research"
EXPECTED_ROUTES = [
    f"{BASE}/overview",
    f"{BASE}/candidates",
    f"{BASE}/candidates/{{id}}",
    f"{BASE}/skills",
    f"{BASE}/plugins",
    f"{BASE}/mcps",
    f"{BASE}/external-tools",
    f"{BASE}/employees",
    f"{BASE}/departments",
    f"{BASE}/risk-levels",
    f"{BASE}/cost-levels",
    f"{BASE}/approval-suggestions",
    f"{BASE}/forbidden-list",
    f"{BASE}/sprint16-candidates",
    f"{BASE}/next-upgrades",
]
REQUEST_PATHS = [
    f"{BASE}/overview",
    f"{BASE}/candidates",
    f"{BASE}/candidates/skill_prompt_research",
    f"{BASE}/skills",
    f"{BASE}/plugins",
    f"{BASE}/mcps",
    f"{BASE}/external-tools",
    f"{BASE}/employees",
    f"{BASE}/departments",
    f"{BASE}/risk-levels",
    f"{BASE}/cost-levels",
    f"{BASE}/approval-suggestions",
    f"{BASE}/forbidden-list",
    f"{BASE}/sprint16-candidates",
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
AUTO_FALSE_FIELDS = {
    "can_auto_download",
    "can_auto_install",
    "can_auto_enable",
    "can_auto_execute",
    "can_connect_mcp",
    "can_call_external_api",
    "can_modify_system",
    "can_spend_money",
}
CandidateFields = {
    "candidate_code",
    "candidate_name",
    "candidate_type",
    "vendor",
    "official_url",
    "description",
    "use_case",
    "target_employee",
    "target_department",
    "risk_level",
    "cost_level",
    "permission_level",
    "requires_boss_confirmation",
    "recommended_stage",
    "forbidden_actions",
    "safety_notes",
    "next_step_suggestion",
    "approval_required",
    "can_auto_download",
    "can_auto_install",
    "can_auto_enable",
    "can_auto_execute",
    "can_connect_mcp",
    "can_call_external_api",
    "can_modify_system",
    "can_spend_money",
}


def test_skill_plugin_research_routes_registered():
    paths = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    for path in EXPECTED_ROUTES:
        assert path in paths
        assert paths[path] == {"GET"}


def test_skill_plugin_research_requires_login(client):
    for path in REQUEST_PATHS:
        assert client.get(path).status_code == 401


def test_skill_plugin_research_rejects_low_privilege(client, viewer_headers):
    for path in REQUEST_PATHS:
        assert client.get(path, headers=viewer_headers).status_code == 403


def test_skill_plugin_research_allows_boss_owner_admin(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        for path in REQUEST_PATHS:
            assert client.get(path, headers=headers).status_code == 200


def test_skill_plugin_research_overview_schema(client, owner_headers):
    data = client.get(f"{BASE}/overview", headers=owner_headers).json()
    assert {
        "total_candidates",
        "skill_candidates",
        "plugin_candidates",
        "mcp_candidates",
        "external_tool_candidates",
        "high_risk_candidates",
        "critical_risk_candidates",
        "boss_confirmation_required_count",
        "sprint16_candidate_count",
        "forbidden_candidate_count",
        "safe_readonly_mode",
        "all_auto_actions_disabled",
    } <= set(data)
    assert data["total_candidates"] >= 10
    assert data["safe_readonly_mode"] is True
    assert data["all_auto_actions_disabled"] is True


def test_skill_plugin_research_candidates_schema_and_404(client, owner_headers):
    rows = client.get(f"{BASE}/candidates", headers=owner_headers).json()["candidates"]
    assert CandidateFields <= set(rows[0])
    assert {row["candidate_type"] for row in rows} >= {"skill", "plugin", "mcp", "external_tool"}
    for row in rows:
        for field in AUTO_FALSE_FIELDS:
            assert row[field] is False
    detail = client.get(f"{BASE}/candidates/{rows[0]['candidate_code']}", headers=owner_headers)
    assert detail.status_code == 200
    assert CandidateFields <= set(detail.json())
    response = client.get(f"{BASE}/candidates/not_exists", headers=owner_headers)
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "not_found"


def test_skill_plugin_research_filtered_collections(client, owner_headers):
    skills = client.get(f"{BASE}/skills", headers=owner_headers).json()["candidates"]
    plugins = client.get(f"{BASE}/plugins", headers=owner_headers).json()["candidates"]
    mcps = client.get(f"{BASE}/mcps", headers=owner_headers).json()["candidates"]
    external = client.get(f"{BASE}/external-tools", headers=owner_headers).json()["candidates"]
    assert skills and all(row["candidate_type"] == "skill" for row in skills)
    assert plugins and all(row["candidate_type"] == "plugin" for row in plugins)
    assert mcps and all(row["candidate_type"] == "mcp" for row in mcps)
    assert external and all(row["candidate_type"] == "external_tool" for row in external)


def test_skill_plugin_research_supporting_schemas(client, owner_headers):
    employees = client.get(f"{BASE}/employees", headers=owner_headers).json()["employees"]
    departments = client.get(f"{BASE}/departments", headers=owner_headers).json()["departments"]
    risk_levels = client.get(f"{BASE}/risk-levels", headers=owner_headers).json()["risk_levels"]
    cost_levels = client.get(f"{BASE}/cost-levels", headers=owner_headers).json()["cost_levels"]
    approvals = client.get(f"{BASE}/approval-suggestions", headers=owner_headers).json()["approval_suggestions"]
    forbidden = client.get(f"{BASE}/forbidden-list", headers=owner_headers).json()["forbidden_list"]
    sprint16 = client.get(f"{BASE}/sprint16-candidates", headers=owner_headers).json()["sprint16_candidates"]
    upgrades = client.get(f"{BASE}/next-upgrades", headers=owner_headers).json()["next_upgrades"]
    assert {"employee_code", "recommended_candidates", "can_auto_execute"} <= set(employees[0])
    assert all(row["can_auto_execute"] is False for row in employees)
    assert {"department", "recommended_candidates", "can_auto_execute"} <= set(departments[0])
    assert all(row["can_auto_execute"] is False for row in departments)
    assert {"risk_level", "risk_name", "requires_boss_confirmation", "can_enter_sprint16"} <= set(risk_levels[0])
    assert {"cost_level", "cost_name", "requires_boss_confirmation"} <= set(cost_levels[0])
    assert {"candidate_code", "approval_status", "required_reviewers", "can_auto_execute"} <= set(approvals[0])
    assert all(row["can_auto_execute"] is False for row in approvals)
    assert {"candidate_code", "forbidden_reason", "forbidden_actions", "can_auto_execute"} <= set(forbidden[0])
    assert all(row["can_auto_execute"] is False for row in forbidden)
    assert {"candidate_code", "recommended_reason", "required_preconditions", "can_auto_execute"} <= set(sprint16[0])
    assert all(row["can_auto_execute"] is False for row in sprint16)
    assert {"upgrade_code", "title", "target_module", "forbidden_actions", "acceptance_notes"} <= set(upgrades[0])


def test_skill_plugin_research_no_write_routes():
    paths = [getattr(route, "path", "") for route in app.routes if "/api/skill-plugin-research" in getattr(route, "path", "")]
    assert len(paths) == len(EXPECTED_ROUTES)
    for route in app.routes:
        if "/api/skill-plugin-research" in getattr(route, "path", ""):
            assert getattr(route, "methods", set()) == {"GET"}


def test_skill_plugin_research_no_sensitive_fields(client, owner_headers):
    for path in REQUEST_PATHS:
        response = client.get(path, headers=owner_headers)
        assert response.status_code == 200
        payload = json.dumps(response.json(), ensure_ascii=False).lower()
        for key in SENSITIVE_KEYS:
            assert key not in payload


def test_skill_plugin_research_no_dangerous_calls():
    for file_name in [
        "backend/routers/skill_plugin_research.py",
        "backend/routers/skill_plugin_research_data.py",
    ]:
        source = Path(file_name).read_text()
        for snippet in [
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
            "http://",
            "https://",
            "git push",
            "git commit",
            "systemctl",
            "Docker socket",
        ]:
            assert snippet not in source
