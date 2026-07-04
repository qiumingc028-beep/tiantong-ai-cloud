from __future__ import annotations

import json

from backend.deploy_models import DeployRecord
from backend.main import app
from backend.models import AiEmployee, TaskCenterAuditLog, TaskCenterResult, TaskCenterReview, TaskCenterTask
from backend.orchestrator_models import OrchestratorAnalysisRecord, OrchestratorTaskLink


BASE = "/api/employee-activity-trace"
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


def auth_headers(client, username: str):
    response = client.post("/api/login", json={"username": username, "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def trace_paths(task_id: int = 1, employee_code: str = "trace_tianwang", log_id: str = "task_center-1-task_created"):
    return [
        f"{BASE}/logs/{log_id}/trace",
        f"{BASE}/tasks/{task_id}/trace",
        f"{BASE}/employees/{employee_code}/trace",
        f"{BASE}/trace-overview",
    ]


def seed_trace_data(test_db):
    db = test_db()
    try:
        employee = AiEmployee(
            employee_code="trace_tianwang",
            employee_name="追溯天王",
            legion="后端开发中心",
            duty="追溯测试",
            status="active",
            task_types='["backend"]',
            default_permissions="[]",
            is_legacy=False,
            sort_order=901,
        )
        db.add(employee)
        task = TaskCenterTask(
            title="Sprint 9 trace task",
            description="Build readonly trace.",
            status="accepted",
            priority="high",
            assigned_ai_employee_code="trace_tianwang",
            assigned_ai_employee_name="追溯天王",
        )
        db.add(task)
        db.flush()
        db.add_all(
            [
                TaskCenterAuditLog(task_id=task.id, action="task_created", to_status="created", detail="created"),
                TaskCenterAuditLog(task_id=task.id, action="result_submitted", from_status="running", to_status="result_submitted", detail="submitted"),
                TaskCenterResult(task_id=task.id, ai_employee_code="trace_tianwang", ai_employee_name="追溯天王", result_content="result should be summarized"),
                TaskCenterReview(task_id=task.id, review_type="acceptance", review_status="accepted", comment="accepted", reviewer_role="tianjian"),
                TaskCenterReview(task_id=task.id, review_type="audit", review_status="audited", comment="audited", reviewer_role="tianjian_audit"),
            ]
        )
        analysis = OrchestratorAnalysisRecord(
            input_excerpt="raw original should stay hidden",
            input_hash="e" * 64,
            detected_employee_code="trace_tianwang",
            detected_employee_name="追溯天王",
            detected_sprint="Sprint 9",
            detected_stage="backend",
            completion_status="completed",
            recommended_codex="trace_tianwang",
            recommended_action="交给天检验收",
            prompt_draft="hidden draft",
            has_blocker=True,
            safety_flags_json=json.dumps(["manual_review", {"message": "字典安全标记"}, [["嵌套标记"]]]),
        )
        db.add(analysis)
        db.flush()
        db.add(
            OrchestratorTaskLink(
                analysis_record_id=analysis.id,
                task_id=task.id,
                link_type="created_from_draft",
                recommended_codex="trace_tianwang",
                source_stage="backend",
            )
        )
        db.add(DeployRecord(deploy_version="Sprint 9", commit_hash="abc123", branch="main", operator="trace_tianwang", status="success", note="deployed"))
        db.commit()
        return task.id
    finally:
        db.close()


def test_employee_activity_trace_routes_exist():
    paths = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    assert f"{BASE}/logs/{{log_id}}/trace" in paths
    assert f"{BASE}/tasks/{{task_id}}/trace" in paths
    assert f"{BASE}/employees/{{employee_code}}/trace" in paths
    assert f"{BASE}/trace-overview" in paths
    for path in [p for p in paths if p.startswith(BASE)]:
        assert "GET" in paths[path]


def test_employee_activity_trace_requires_login(client):
    for path in trace_paths():
        response = client.get(path)
        assert response.status_code == 401


def test_employee_activity_trace_rejects_low_privilege(client):
    for path in trace_paths():
        response = client.get(path, headers=auth_headers(client, "viewer"))
        assert response.status_code == 403


def test_employee_activity_trace_allows_privileged_users(client, boss_headers, owner_headers, admin_headers, test_db):
    task_id = seed_trace_data(test_db)
    paths = trace_paths(task_id=task_id, log_id=f"task_center-{task_id}-task_created")
    for headers in [boss_headers, owner_headers, admin_headers]:
        for path in paths:
            response = client.get(path, headers=headers)
            assert response.status_code == 200


def assert_trace_shape(data):
    assert {
        "summary",
        "trace_nodes",
        "trace_edges",
        "employee",
        "task",
        "orchestrator_source",
        "boss_confirmation",
        "review_status",
        "audit_status",
        "deploy_status",
        "git_commit",
        "blockers",
        "missing_steps",
        "next_suggestion",
        "safety_flags",
    } <= set(data)
    assert isinstance(data["trace_nodes"], list)
    assert isinstance(data["trace_edges"], list)
    assert isinstance(data["blockers"], list)
    assert isinstance(data["missing_steps"], list)
    assert isinstance(data["safety_flags"], list)


def test_employee_activity_trace_response_schema_and_content(client, owner_headers, test_db):
    task_id = seed_trace_data(test_db)
    response = client.get(f"{BASE}/tasks/{task_id}/trace", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert_trace_shape(data)
    assert data["trace_nodes"]
    assert data["orchestrator_source"]["link_type"] == "created_from_draft"
    assert "字典安全标记" in data["safety_flags"]
    assert "嵌套标记" in data["safety_flags"]


def test_employee_activity_trace_handles_empty_and_missing_data(client, owner_headers):
    response = client.get(f"{BASE}/employees/missing_employee/trace", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert_trace_shape(data)
    assert data["trace_nodes"] == []
    assert data["employee"]["employee_code"] == "missing_employee"

    response = client.get(f"{BASE}/trace-overview", headers=owner_headers)
    assert response.status_code == 200
    assert_trace_shape(response.json())


def test_employee_activity_trace_handles_mixed_values_without_500(client, owner_headers, test_db):
    task_id = seed_trace_data(test_db)
    response = client.get(f"{BASE}/tasks/{task_id}/trace", headers=owner_headers)
    assert response.status_code == 200
    payload = json.dumps(response.json(), ensure_ascii=False)
    assert "字典安全标记" in payload
    assert "嵌套标记" in payload
    assert "raw original should stay hidden" not in payload
    assert "hidden draft" not in payload


def test_employee_activity_trace_does_not_return_sensitive_fields(client, owner_headers, test_db):
    task_id = seed_trace_data(test_db)
    response = client.get(f"{BASE}/tasks/{task_id}/trace", headers=owner_headers)
    assert response.status_code == 200
    payload = json.dumps(response.json(), ensure_ascii=False).lower()
    for key in SENSITIVE_KEYS:
        assert key not in payload


def test_employee_activity_trace_is_read_only(client, owner_headers, test_db):
    task_id = seed_trace_data(test_db)
    db = test_db()
    try:
        before = db.get(TaskCenterTask, task_id).status
    finally:
        db.close()

    response = client.get(f"{BASE}/tasks/{task_id}/trace", headers=owner_headers)
    assert response.status_code == 200

    db = test_db()
    try:
        assert db.get(TaskCenterTask, task_id).status == before
    finally:
        db.close()
