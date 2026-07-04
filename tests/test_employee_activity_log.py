from __future__ import annotations

import json

from backend.deploy_models import DeployRecord
from backend.models import AiEmployee, TaskCenterAuditLog, TaskCenterResult, TaskCenterReview, TaskCenterTask
from backend.orchestrator_models import OrchestratorAnalysisRecord, OrchestratorTaskLink


API_PATH = "/api/employee-activity-log/overview"
SENSITIVE_KEYS = {
    "input_excerpt",
    "raw_text",
    "token",
    "cookie",
    "password",
    "secret",
    "authorization",
    "database_url",
    "redis_url",
    "access_token",
    "refresh_token",
    "private_key",
}


def auth_headers(client, username: str):
    response = client.post("/api/login", json={"username": username, "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_employee_activity_log_requires_login(client):
    response = client.get(API_PATH)
    assert response.status_code == 401


def test_employee_activity_log_rejects_low_privilege_users(client):
    for username in ["operator", "customer_service", "designer", "editor", "viewer"]:
        response = client.get(API_PATH, headers=auth_headers(client, username))
        assert response.status_code == 403


def test_employee_activity_log_allows_boss_owner_admin(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        response = client.get(API_PATH, headers=headers)
        assert response.status_code == 200


def test_employee_activity_log_response_shape(client, owner_headers):
    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert {
        "summary",
        "logs",
        "employees",
        "tasks",
        "filters",
        "timeline",
        "blockers",
        "pending_boss_confirmations",
        "recent_commits",
        "recent_deploys",
    } <= set(data)
    assert {
        "today_logs",
        "today_task_flows",
        "today_reviews",
        "today_audits",
        "today_deploys",
        "today_git_commits",
        "today_failed_or_blocked",
        "pending_boss_confirmations",
        "current_sprint",
    } <= set(data["summary"])
    assert {"employee_codes", "sprints", "action_types", "statuses"} <= set(data["filters"])


def seed_activity_data(test_db):
    db = test_db()
    try:
        if not db.query(AiEmployee).filter(AiEmployee.employee_code == "log_tianwang").one_or_none():
            db.add(
                AiEmployee(
                    employee_code="log_tianwang",
                    employee_name="日志天王",
                    legion="后端开发中心",
                    duty="日志测试",
                    status="active",
                    task_types='["backend"]',
                    default_permissions="[]",
                    is_legacy=False,
                    sort_order=900,
                )
            )
        task = TaskCenterTask(
            title="Sprint 8 activity log task",
            description="Build readonly activity log.",
            status="result_submitted",
            priority="high",
            assigned_ai_employee_code="log_tianwang",
            assigned_ai_employee_name="日志天王",
        )
        blocked = TaskCenterTask(
            title="Sprint 8 blocked task",
            status="blocked",
            assigned_ai_employee_code="log_tianwang",
            assigned_ai_employee_name="日志天王",
        )
        created = TaskCenterTask(title="Sprint 8 confirmation task", status="created")
        db.add_all([task, blocked, created])
        db.flush()
        db.add_all(
            [
                TaskCenterAuditLog(task_id=task.id, action="task_created", to_status="created", detail="created"),
                TaskCenterAuditLog(task_id=task.id, action="ai_employee_assigned", from_status="created", to_status="assigned", detail="assigned"),
                TaskCenterAuditLog(task_id=task.id, action="task_started", from_status="assigned", to_status="running", detail="started"),
                TaskCenterAuditLog(task_id=task.id, action="result_submitted", from_status="running", to_status="result_submitted", detail="submitted"),
                TaskCenterResult(task_id=task.id, ai_employee_code="log_tianwang", ai_employee_name="日志天王", result_content="result done"),
                TaskCenterReview(task_id=task.id, review_type="acceptance", review_status="accepted", comment="accepted", reviewer_role="tianjian"),
                TaskCenterReview(task_id=task.id, review_type="audit", review_status="audited", comment="audited", reviewer_role="tianjian_audit"),
            ]
        )
        analysis = OrchestratorAnalysisRecord(
            input_excerpt="raw original should stay hidden",
            input_hash="c" * 64,
            detected_employee_code="log_tianwang",
            detected_employee_name="日志天王",
            detected_sprint="Sprint 8",
            detected_stage="backend",
            completion_status="completed",
            recommended_codex="log_tianwang",
            recommended_action="交给天检验收",
            prompt_draft="hidden draft",
            safety_flags_json=json.dumps(["manual_review"]),
        )
        db.add(analysis)
        db.flush()
        db.add(OrchestratorTaskLink(analysis_record_id=analysis.id, task_id=task.id, link_type="created_from_draft", recommended_codex="log_tianwang", source_stage="backend"))
        db.add(DeployRecord(deploy_version="Sprint 8", commit_hash="abc123", branch="main", operator="log_tianwang", status="success", note="deployed"))
        db.commit()
        return task.id, blocked.id, created.id
    finally:
        db.close()


def test_employee_activity_log_generates_action_types_and_filters(client, owner_headers, test_db):
    task_id, blocked_id, created_id = seed_activity_data(test_db)

    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    action_types = {row["action_type"] for row in data["logs"]}
    assert {
        "task_created",
        "task_assigned",
        "task_started",
        "task_submitted",
        "task_reviewed",
        "task_audited",
        "orchestrator_analyzed",
        "prompt_draft_generated",
        "task_draft_generated",
        "task_created_from_orchestrator",
        "deploy_success",
        "git_commit_recorded",
        "blocker_detected",
        "boss_confirmation_required",
    } <= action_types

    assert client.get(API_PATH, headers=owner_headers, params={"employee_code": "log_tianwang"}).json()["logs"]
    assert all(row["sprint"] == "Sprint 8" for row in client.get(API_PATH, headers=owner_headers, params={"sprint": "Sprint 8"}).json()["logs"])
    assert all(row["task_id"] == task_id for row in client.get(API_PATH, headers=owner_headers, params={"task_id": task_id}).json()["logs"])
    assert all(row["action_type"] == "task_submitted" for row in client.get(API_PATH, headers=owner_headers, params={"action_type": "task_submitted"}).json()["logs"])
    assert all(row["status"] == "blocked" for row in client.get(API_PATH, headers=owner_headers, params={"status": "blocked"}).json()["logs"])
    assert all(row["has_blocker"] is True for row in client.get(API_PATH, headers=owner_headers, params={"has_blocker": "true"}).json()["logs"])
    assert all(row["needs_boss_confirmation"] is True for row in client.get(API_PATH, headers=owner_headers, params={"needs_boss_confirmation": "true"}).json()["logs"])
    assert any(row["task_id"] == blocked_id for row in data["blockers"])
    assert any(row["task_id"] == created_id for row in data["pending_boss_confirmations"])
    assert data["recent_commits"]
    assert data["recent_deploys"]


def test_employee_activity_log_handles_empty_sources(client, owner_headers, test_db):
    db = test_db()
    try:
        db.query(OrchestratorTaskLink).delete()
        db.query(OrchestratorAnalysisRecord).delete()
        db.query(TaskCenterAuditLog).delete()
        db.query(TaskCenterResult).delete()
        db.query(TaskCenterReview).delete()
        db.query(TaskCenterTask).delete()
        db.query(DeployRecord).delete()
        db.query(AiEmployee).delete()
        db.commit()
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["logs"] == []
    assert data["employees"] == []
    assert data["tasks"] == []
    assert data["timeline"] == []
    assert data["blockers"] == []
    assert data["pending_boss_confirmations"] == []
    assert data["recent_commits"] == []
    assert data["recent_deploys"] == []


def test_employee_activity_log_does_not_return_sensitive_fields(client, owner_headers, test_db):
    seed_activity_data(test_db)
    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    payload = json.dumps(response.json(), ensure_ascii=False).lower()
    for key in SENSITIVE_KEYS:
        assert key not in payload
    assert "raw original should stay hidden" not in payload
    assert "hidden draft" not in payload


def test_employee_activity_log_is_read_only_and_limit_is_capped(client, owner_headers, test_db):
    task_id, _, _ = seed_activity_data(test_db)
    db = test_db()
    try:
        before = db.get(TaskCenterTask, task_id).status
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers, params={"limit": 999})
    assert response.status_code == 200
    data = response.json()
    assert len(data["logs"]) <= 200

    db = test_db()
    try:
        assert db.get(TaskCenterTask, task_id).status == before
    finally:
        db.close()


def test_employee_activity_log_action_type_options_are_reasonable(client, owner_headers):
    response = client.get(API_PATH, headers=owner_headers)
    assert response.status_code == 200
    action_types = {row["value"] for row in response.json()["filters"]["action_types"]}
    assert {
        "task_created",
        "task_assigned",
        "task_started",
        "task_submitted",
        "task_reviewed",
        "task_audited",
        "task_summarized",
        "orchestrator_analyzed",
        "prompt_draft_generated",
        "task_draft_generated",
        "task_created_from_orchestrator",
        "deploy_started",
        "deploy_success",
        "deploy_failed",
        "git_commit_recorded",
        "blocker_detected",
        "boss_confirmation_required",
        "fix_submitted",
    } <= action_types
