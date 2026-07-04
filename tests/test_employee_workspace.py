from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import event

from backend.deploy_models import DeployRecord
from backend.models import AiEmployee, TaskCenterAuditLog, TaskCenterTask
from backend.orchestrator_models import OrchestratorAnalysisRecord, OrchestratorTaskLink


API_PATH = "/api/employee-workspace/overview"
SENSITIVE_KEYS = {
    "input_excerpt",
    "prompt_draft",
    "raw_text",
    "token",
    "cookie",
    "password",
    "api_key",
    "database_url",
    "redis_url",
    "bearer",
    "authorization",
    "secret",
}


def auth_headers(client, username: str):
    response = client.post("/api/login", json={"username": username, "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_employee_workspace_requires_login(client):
    response = client.get(API_PATH)
    assert response.status_code == 401


def test_employee_workspace_rejects_low_privilege_users(client):
    for username in ["operator", "customer_service", "designer", "editor", "viewer"]:
        response = client.get(API_PATH, headers=auth_headers(client, username))
        assert response.status_code == 403


def test_employee_workspace_allows_boss_owner_admin(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        response = client.get(API_PATH, headers=headers)
        assert response.status_code == 200


def test_employee_workspace_response_shape(client, owner_headers):
    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert {
        "summary",
        "employees",
        "blockers",
        "pending_reviews",
        "pending_audits",
        "pending_deploys",
        "recent_actions",
    } <= set(data)
    assert {
        "total_employees",
        "standby_count",
        "running_count",
        "reviewing_count",
        "completed_count",
        "blocked_count",
        "current_sprint",
        "today_tasks",
        "pending_boss_confirmations",
        "pending_test_reviews",
        "pending_audits",
        "pending_deploys",
    } <= set(data["summary"])


def test_employee_workspace_employee_without_task_is_standby(client, owner_headers):
    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    rows = {row["employee_code"]: row for row in response.json()["employees"]}
    assert rows["tiantong"]["status"] == "standby"
    assert rows["tiantong"]["current_task"] is None
    assert rows["tiantong"]["task_id"] is None
    assert rows["tiantong"]["next_suggestion"] == "等待任务"


def test_employee_workspace_maps_task_and_orchestrator_data(client, owner_headers, test_db):
    db = test_db()
    try:
        task = TaskCenterTask(
            title="Implement workspace API",
            status="result_submitted",
            priority="high",
            assigned_ai_employee_code="tianwang",
            assigned_ai_employee_name="天王：后端开发中心",
        )
        db.add(task)
        db.flush()
        db.add(
            OrchestratorAnalysisRecord(
                input_excerpt="password=hidden raw text",
                input_hash="a" * 64,
                detected_employee_code="tianwang",
                detected_employee_name="天王：后端开发中心",
                detected_sprint="Sprint 7",
                detected_stage="backend",
                completion_status="completed",
                recommended_codex="tianwang",
                recommended_action="交给天检验收",
                safety_flags_json=json.dumps(["manual_review"]),
                prompt_draft="secret prompt should not be returned",
            )
        )
        db.add(TaskCenterAuditLog(task_id=task.id, action="result_submitted", to_status="result_submitted"))
        db.commit()
        task_id = task.id
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    rows = {row["employee_code"]: row for row in data["employees"]}
    tianwang = rows["tianwang"]
    assert tianwang["status"] == "reviewing"
    assert tianwang["task_id"] == task_id
    assert tianwang["sprint"] == "Sprint 7"
    assert tianwang["stage"] == "backend"
    assert tianwang["review_status"] == "pending"
    assert tianwang["recent_orchestrator_source"]["analysis_id"]
    assert data["summary"]["pending_test_reviews"] == 1
    assert data["pending_reviews"][0]["task_id"] == task_id
    assert data["recent_actions"]


def test_employee_workspace_handles_empty_sources(client, owner_headers, test_db):
    db = test_db()
    try:
        db.query(OrchestratorTaskLink).delete()
        db.query(OrchestratorAnalysisRecord).delete()
        db.query(TaskCenterAuditLog).delete()
        db.query(TaskCenterTask).delete()
        db.query(DeployRecord).delete()
        db.query(AiEmployee).delete()
        db.commit()
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["total_employees"] == 0
    assert data["employees"] == []
    assert data["blockers"] == []
    assert data["pending_reviews"] == []
    assert data["pending_audits"] == []
    assert data["pending_deploys"] == []
    assert data["recent_actions"] == []


def test_employee_workspace_reports_blockers_audits_and_deploys(client, owner_headers, test_db):
    db = test_db()
    try:
        rejected = TaskCenterTask(
            title="Needs fix",
            status="rejected",
            assigned_ai_employee_code="tianwang",
            assigned_ai_employee_name="天王：后端开发中心",
        )
        accepted = TaskCenterTask(title="Wait audit", status="accepted")
        db.add_all([rejected, accepted])
        db.add(DeployRecord(deploy_version="Sprint 7", operator="tiandun", status="pending"))
        db.commit()
        rejected_id = rejected.id
        accepted_id = accepted.id
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["blocked_count"] >= 1
    assert data["summary"]["pending_audits"] == 1
    assert data["summary"]["pending_deploys"] == 1
    assert any(item["task_id"] == rejected_id for item in data["blockers"])
    assert data["pending_audits"][0]["task_id"] == accepted_id
    assert data["pending_deploys"][0]["status"] == "pending"


def test_employee_workspace_does_not_return_sensitive_fields(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add(
            OrchestratorAnalysisRecord(
                input_excerpt="raw_text cookie password secret",
                input_hash="b" * 64,
                detected_employee_code="tianwang",
                detected_employee_name="天王：后端开发中心",
                prompt_draft="Bearer token Authorization DATABASE_URL REDIS_URL API key",
                recommended_codex="tianwang",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    assert_sensitive_keys_absent(response.json())


def test_employee_workspace_is_read_only(client, owner_headers, test_db):
    db = test_db()
    engine = db.get_bind()
    statements = []

    def capture_write(_conn, _cursor, statement, _parameters, _context, _executemany):
        verb = statement.strip().split(maxsplit=1)[0].upper()
        if verb in {"INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER"}:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture_write)
    try:
        response = client.get(API_PATH, headers=owner_headers)
        assert response.status_code == 200
        assert statements == []
    finally:
        event.remove(engine, "before_cursor_execute", capture_write)
        db.close()


def test_employee_workspace_does_not_add_alembic_migration():
    versions = {path.name for path in Path("alembic/versions").glob("*.py")}
    assert "0011_orchestrator_task_links.py" in versions
    assert "0012_employee_workspace.py" not in versions


def assert_sensitive_keys_absent(value):
    if isinstance(value, dict):
        for key, child in value.items():
            assert key.lower() not in SENSITIVE_KEYS
            assert_sensitive_keys_absent(child)
    elif isinstance(value, list):
        for child in value:
            assert_sensitive_keys_absent(child)
