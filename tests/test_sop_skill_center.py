from __future__ import annotations

import json

from backend.main import app


BASE = "/api/sop-skill-center"
EXPECTED_ROUTES = [
    f"{BASE}/overview",
    f"{BASE}/sops",
    f"{BASE}/sops/{{sop_code}}",
    f"{BASE}/skills",
    f"{BASE}/skills/{{skill_code}}",
    f"{BASE}/prompts",
    f"{BASE}/prompts/{{prompt_code}}",
    f"{BASE}/employees",
    f"{BASE}/employees/{{employee_code}}",
    f"{BASE}/task-types",
    f"{BASE}/departments",
    f"{BASE}/acceptance-rules",
    f"{BASE}/security-rules",
    f"{BASE}/missing-bindings",
    f"{BASE}/next-upgrades",
]
REQUEST_PATHS = [
    f"{BASE}/overview",
    f"{BASE}/sops",
    f"{BASE}/sops/sop_product_design",
    f"{BASE}/skills",
    f"{BASE}/skills/skill_product_planning",
    f"{BASE}/prompts",
    f"{BASE}/prompts/prompt_product_design_summary",
    f"{BASE}/employees",
    f"{BASE}/employees/tiandao",
    f"{BASE}/task-types",
    f"{BASE}/departments",
    f"{BASE}/acceptance-rules",
    f"{BASE}/security-rules",
    f"{BASE}/missing-bindings",
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
OVERVIEW_FIELDS = {
    "total_sops",
    "total_skills",
    "total_prompt_templates",
    "bound_employee_count",
    "bound_task_type_count",
    "department_binding_count",
    "boss_confirmation_rule_count",
    "test_acceptance_rule_count",
    "security_audit_rule_count",
    "deploy_required_rule_count",
    "auto_execute_disabled_count",
    "missing_binding_count",
}
SOP_FIELDS = {
    "sop_code",
    "sop_name",
    "department",
    "task_types",
    "description",
    "steps_summary",
    "required_inputs",
    "expected_outputs",
    "acceptance_rules",
    "safety_rules",
    "owner_employee",
    "required_roles",
    "requires_boss_confirmation",
    "requires_test_acceptance",
    "requires_security_audit",
    "requires_deploy_review",
    "can_auto_execute",
    "current_status",
    "next_upgrade_suggestion",
}
SKILL_FIELDS = {
    "skill_code",
    "skill_name",
    "skill_category",
    "description",
    "suitable_employees",
    "suitable_task_types",
    "required_tools",
    "forbidden_tools",
    "recommended_models",
    "safety_level",
    "requires_boss_confirmation",
    "requires_test_acceptance",
    "requires_security_audit",
    "can_auto_execute",
    "current_status",
    "next_upgrade_suggestion",
}
PROMPT_FIELDS = {
    "prompt_code",
    "prompt_name",
    "task_type",
    "employee_code",
    "template_content_summary",
    "required_variables",
    "output_format",
    "safety_notes",
    "forbidden_content",
    "current_status",
    "next_upgrade_suggestion",
}
EMPLOYEE_FIELDS = {
    "employee_code",
    "employee_name",
    "department",
    "bound_sops",
    "bound_skills",
    "bound_prompt_templates",
    "recommended_models",
    "allowed_tools",
    "forbidden_tools",
    "requires_boss_confirmation",
    "requires_test_acceptance",
    "requires_security_audit",
    "requires_deploy_review",
    "safety_rules",
    "can_auto_execute",
    "missing_bindings",
    "next_upgrade_suggestion",
}
TASK_TYPE_FIELDS = {
    "task_type",
    "task_type_name",
    "recommended_employee",
    "recommended_sop",
    "recommended_skill",
    "recommended_prompt",
    "recommended_model",
    "recommended_tools",
    "forbidden_tools",
    "required_acceptance_flow",
    "safety_level",
    "requires_boss_confirmation",
    "requires_test_acceptance",
    "requires_security_audit",
    "requires_deploy_review",
    "can_auto_execute",
    "next_upgrade_suggestion",
}


def test_sop_skill_center_routes_registered():
    paths = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    for path in EXPECTED_ROUTES:
        assert path in paths
        assert paths[path] == {"GET"}


def test_sop_skill_center_requires_login(client):
    for path in REQUEST_PATHS:
        assert client.get(path).status_code == 401


def test_sop_skill_center_rejects_low_privilege(client, viewer_headers):
    for path in REQUEST_PATHS:
        assert client.get(path, headers=viewer_headers).status_code == 403


def test_sop_skill_center_allows_boss_owner_admin(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        for path in REQUEST_PATHS:
            assert client.get(path, headers=headers).status_code == 200


def test_sop_skill_center_overview_schema(client, owner_headers):
    data = client.get(f"{BASE}/overview", headers=owner_headers).json()
    assert OVERVIEW_FIELDS <= set(data)
    assert data["total_sops"] >= 8
    assert data["total_skills"] >= 8
    assert data["total_prompt_templates"] >= 3


def test_sop_skill_center_sops_schema_and_404(client, owner_headers):
    rows = client.get(f"{BASE}/sops", headers=owner_headers).json()["sops"]
    assert SOP_FIELDS <= set(rows[0])
    assert all(row["can_auto_execute"] is False for row in rows)
    detail = client.get(f"{BASE}/sops/{rows[0]['sop_code']}", headers=owner_headers)
    assert detail.status_code == 200
    assert SOP_FIELDS <= set(detail.json())
    response = client.get(f"{BASE}/sops/not_exists", headers=owner_headers)
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "not_found"


def test_sop_skill_center_skills_schema_and_404(client, owner_headers):
    rows = client.get(f"{BASE}/skills", headers=owner_headers).json()["skills"]
    assert SKILL_FIELDS <= set(rows[0])
    assert all(row["can_auto_execute"] is False for row in rows)
    detail = client.get(f"{BASE}/skills/{rows[0]['skill_code']}", headers=owner_headers)
    assert detail.status_code == 200
    assert SKILL_FIELDS <= set(detail.json())
    response = client.get(f"{BASE}/skills/not_exists", headers=owner_headers)
    assert response.status_code == 404
    assert response.json()["detail"]["kind"] == "skill"


def test_sop_skill_center_prompts_schema_summary_only_and_404(client, owner_headers):
    rows = client.get(f"{BASE}/prompts", headers=owner_headers).json()["prompts"]
    assert PROMPT_FIELDS <= set(rows[0])
    assert "template_content" not in rows[0]
    assert "template_content_summary" in rows[0]
    detail = client.get(f"{BASE}/prompts/{rows[0]['prompt_code']}", headers=owner_headers)
    assert detail.status_code == 200
    assert PROMPT_FIELDS <= set(detail.json())
    response = client.get(f"{BASE}/prompts/not_exists", headers=owner_headers)
    assert response.status_code == 404
    assert response.json()["detail"]["kind"] == "prompt"


def test_sop_skill_center_employees_schema_and_404(client, owner_headers):
    rows = client.get(f"{BASE}/employees", headers=owner_headers).json()["employees"]
    assert EMPLOYEE_FIELDS <= set(rows[0])
    assert all(row["can_auto_execute"] is False for row in rows)
    detail = client.get(f"{BASE}/employees/{rows[0]['employee_code']}", headers=owner_headers)
    assert detail.status_code == 200
    assert EMPLOYEE_FIELDS <= set(detail.json())
    response = client.get(f"{BASE}/employees/not_exists", headers=owner_headers)
    assert response.status_code == 404
    assert response.json()["detail"]["kind"] == "employee"


def test_sop_skill_center_collection_schemas(client, owner_headers):
    task_types = client.get(f"{BASE}/task-types", headers=owner_headers).json()["task_types"]
    departments = client.get(f"{BASE}/departments", headers=owner_headers).json()["departments"]
    acceptance = client.get(f"{BASE}/acceptance-rules", headers=owner_headers).json()["acceptance_rules"]
    security = client.get(f"{BASE}/security-rules", headers=owner_headers).json()["security_rules"]
    missing = client.get(f"{BASE}/missing-bindings", headers=owner_headers).json()["missing_bindings"]
    upgrades = client.get(f"{BASE}/next-upgrades", headers=owner_headers).json()["next_upgrades"]
    assert TASK_TYPE_FIELDS <= set(task_types[0])
    assert all(row["can_auto_execute"] is False for row in task_types)
    assert {"department", "department_name", "bound_sops", "missing_bindings"} <= set(departments[0])
    assert {"rule_code", "required_checker", "acceptance_steps", "current_status"} <= set(acceptance[0])
    assert {"rule_code", "forbidden_actions", "sensitive_fields", "can_auto_execute"} <= set(security[0])
    assert all(row["can_auto_execute"] is False for row in security)
    assert isinstance(missing, list)
    assert {"upgrade_code", "target_sprint", "can_auto_execute"} <= set(upgrades[0])
    assert all(row["can_auto_execute"] is False for row in upgrades)


def test_sop_skill_center_no_write_routes():
    paths = [getattr(route, "path", "") for route in app.routes if "/api/sop-skill-center" in getattr(route, "path", "")]
    assert len(paths) == len(EXPECTED_ROUTES)
    for route in app.routes:
        if "/api/sop-skill-center" in getattr(route, "path", ""):
            assert getattr(route, "methods", set()) == {"GET"}


def test_sop_skill_center_no_sensitive_fields_or_full_prompt(client, owner_headers):
    for path in REQUEST_PATHS:
        response = client.get(path, headers=owner_headers)
        assert response.status_code == 200
        payload = json.dumps(response.json(), ensure_ascii=False).lower()
        for key in SENSITIVE_KEYS:
            assert key not in payload
        assert "template_content_summary" in payload or "prompt" not in path
        assert "template_content\":" not in payload


def test_sop_skill_center_can_auto_execute_all_false(client, owner_headers):
    for path, key in [
        (f"{BASE}/sops", "sops"),
        (f"{BASE}/skills", "skills"),
        (f"{BASE}/employees", "employees"),
        (f"{BASE}/task-types", "task_types"),
        (f"{BASE}/security-rules", "security_rules"),
        (f"{BASE}/next-upgrades", "next_upgrades"),
    ]:
        rows = client.get(path, headers=owner_headers).json()[key]
        assert rows
        assert all(row["can_auto_execute"] is False for row in rows)
