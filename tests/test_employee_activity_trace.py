from __future__ import annotations

import hashlib
import json

from backend.deploy_models import DeployRecord
from backend.main import app
from backend.models import AiEmployee, TaskCenterAuditLog, TaskCenterResult, TaskCenterReview, TaskCenterTask, User
from backend.orchestrator_models import OrchestratorAnalysisRecord, OrchestratorTaskLink
from tests.task_center_ownership_helpers import (
    bind_pending_tasks as _bind_pending_tasks,
    owner_db as _owner_db,
)


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
    db = _owner_db(test_db)
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
        _bind_pending_tasks(db)
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
        _bind_pending_tasks(db)
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
        _bind_pending_tasks(db)
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
    db = test_db()
    try:
        users = {username: db.query(User).filter(User.username == username).one() for username in ("owner", "admin", "boss")}
        ownerless = TaskCenterTask(title="Intentional ownerless trace fixture", status="accepted")
        db.add(ownerless)
        db.flush()
        owner_user_id = int(users["owner"].id)
        admin_user_id = int(users["admin"].id)
        boss_user_id = int(users["boss"].id)
        ownerless_id = int(ownerless.id)
        assert {"owner": owner_user_id, "admin": admin_user_id, "boss": boss_user_id} == {"owner": 1, "admin": 2, "boss": 3}
        db.commit()
    finally:
        db.close()

    def object_state():
        db = test_db()
        try:
            state = {}
            for model in (TaskCenterTask, TaskCenterResult, TaskCenterAuditLog, TaskCenterReview):
                rows = db.query(model).order_by(model.id.asc()).all()
                payloads = [
                    {column.name: getattr(row, column.name) for column in model.__table__.columns}
                    for row in rows
                ]
                canonical = json.dumps(payloads, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
                state[model.__tablename__] = {
                    "primary_keys": tuple(row.id for row in rows),
                    "content_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                }
            return state
        finally:
            db.close()

    def get_as(headers, expected_user_id, path):
        client.cookies.clear()
        identity = client.get("/api/me", headers=headers)
        assert identity.status_code == 200
        assert identity.json()["id"] == expected_user_id
        client.cookies.clear()
        return client.get(path, headers=headers)

    before = object_state()
    log_path = f"{BASE}/logs/task_center-{task_id}-task_created/trace"
    task_path = f"{BASE}/tasks/{task_id}/trace"
    owner_paths = [log_path, task_path, f"{BASE}/employees/trace_tianwang/trace", f"{BASE}/trace-overview"]
    for path in owner_paths:
        response = get_as(owner_headers, owner_user_id, path)
        assert response.status_code == 200
        if path in {log_path, task_path}:
            assert response.json()["task"]["task_id"] == task_id

    missing_id = max(task_id, ownerless_id) + 99999
    object_paths = [
        (log_path, f"{BASE}/logs/task_center-{missing_id}-task_created/trace"),
        (task_path, f"{BASE}/tasks/{missing_id}/trace"),
    ]
    for expected_user_id, headers in ((boss_user_id, boss_headers), (admin_user_id, admin_headers)):
        for foreign_path, missing_path in object_paths:
            foreign = get_as(headers, expected_user_id, foreign_path)
            missing = get_as(headers, expected_user_id, missing_path)
            assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json())
            assert foreign.status_code == 404
        for path in (f"{BASE}/employees/trace_tianwang/trace", f"{BASE}/trace-overview"):
            response = get_as(headers, expected_user_id, path)
            assert response.status_code == 200
            assert response.json()["task"] == {} if "employees" in path else response.json()["summary"]["total_tasks"] == 0

    for ownerless_path, missing_path in (
        (f"{BASE}/logs/task_center-{ownerless_id}-task_created/trace", f"{BASE}/logs/task_center-{missing_id}-task_created/trace"),
        (f"{BASE}/tasks/{ownerless_id}/trace", f"{BASE}/tasks/{missing_id}/trace"),
    ):
        ownerless_response = get_as(owner_headers, owner_user_id, ownerless_path)
        missing_response = get_as(owner_headers, owner_user_id, missing_path)
        assert (ownerless_response.status_code, ownerless_response.json()) == (missing_response.status_code, missing_response.json())
        assert ownerless_response.status_code == 404

    assert object_state() == before


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
    db = _owner_db(test_db)
    try:
        before = db.get(TaskCenterTask, task_id).status
    finally:
        db.close()

    response = client.get(f"{BASE}/tasks/{task_id}/trace", headers=owner_headers)
    assert response.status_code == 200

    db = _owner_db(test_db)
    try:
        assert db.get(TaskCenterTask, task_id).status == before
    finally:
        db.close()
