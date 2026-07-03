import subprocess
import sys

from backend.models import TaskCenterTask
from backend.orchestrator_models import OrchestratorAnalysisRecord, OrchestratorTaskLink


def auth_headers(client, username: str):
    response = client.post("/api/login", json={"username": username, "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_orchestrator_task_link_endpoints_require_login(client):
    assert client.post("/api/orchestrator/task-links", json={"analysis_record_id": 1, "task_id": 1}).status_code == 401
    assert client.post("/api/orchestrator/task-drafts", json={"analysis_record_id": 1}).status_code == 401
    assert client.post(
        "/api/orchestrator/task-drafts/confirm-create-task",
        json={"analysis_record_id": 1, "title": "task"},
    ).status_code == 401
    assert client.get("/api/task-center/tasks/1/orchestrator-links").status_code == 401


def test_low_privilege_users_cannot_access_link_endpoints(client):
    for username in ["operator", "customer_service", "designer", "editor", "viewer"]:
        headers = auth_headers(client, username)
        assert client.post("/api/orchestrator/task-links", headers=headers, json={"analysis_record_id": 1, "task_id": 1}).status_code == 403
        assert client.post("/api/orchestrator/task-drafts", headers=headers, json={"analysis_record_id": 1}).status_code == 403
        assert client.post(
            "/api/orchestrator/task-drafts/confirm-create-task",
            headers=headers,
            json={"analysis_record_id": 1, "title": "task"},
        ).status_code == 403
        assert client.get("/api/task-center/tasks/1/orchestrator-links", headers=headers).status_code == 403


def test_owner_boss_admin_can_generate_task_drafts(client, owner_headers, boss_headers, admin_headers, test_db):
    analysis_id = create_analysis(test_db)
    for headers in [owner_headers, boss_headers, admin_headers]:
        response = client.post("/api/orchestrator/task-drafts", headers=headers, json={"analysis_record_id": analysis_id})
        assert response.status_code == 200
        assert response.json()["ok"] is True


def test_link_existing_task_does_not_change_task_state_or_assignment(client, owner_headers, test_db):
    analysis_id = create_analysis(test_db, recommended_codex="tianwang", recommended_action="backend_development")
    task_id = create_task(test_db, status="created")

    response = client.post(
        "/api/orchestrator/task-links",
        headers=owner_headers,
        json={
            "analysis_record_id": analysis_id,
            "task_id": task_id,
            "link_type": "existing_task",
            "note": "linked to existing task cookie=session123 token=secret-token",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["link"]["link_type"] == "existing_task"
    assert "session123" not in data["link"]["note"]
    assert "secret-token" not in data["link"]["note"]
    assert "[REDACTED]" in data["link"]["note"]

    db = test_db()
    try:
        task = db.get(TaskCenterTask, task_id)
        assert task.status == "created"
        assert task.assigned_ai_employee_code is None
        assert task.assigned_ai_employee_name is None
    finally:
        db.close()


def test_task_draft_does_not_create_formal_task_and_redacts_description(client, owner_headers, test_db):
    analysis_id = create_analysis(
        test_db,
        input_excerpt="architecture design completed cookie=session123 DATABASE_URL=postgresql://user:pass@db/name",
        recommended_codex="tianwang",
    )
    before = task_count(test_db)

    response = client.post("/api/orchestrator/task-drafts", headers=owner_headers, json={"analysis_record_id": analysis_id})

    assert response.status_code == 200
    data = response.json()
    assert data["draft"]["recommended_ai_employee_code"] == "tianwang"
    assert "session123" not in data["draft"]["description"]
    assert "postgresql://user:pass@db/name" not in data["draft"]["description"]
    assert "[REDACTED]" in data["draft"]["description"]
    assert task_count(test_db) == before


def test_confirm_create_task_creates_created_task_and_link_without_assignment(client, owner_headers, test_db):
    analysis_id = create_analysis(test_db, recommended_codex="tianwang", recommended_action="backend_development")

    response = client.post(
        "/api/orchestrator/task-drafts/confirm-create-task",
        headers=owner_headers,
        json={
            "analysis_record_id": analysis_id,
            "title": "Implement Orchestrator task link APIs",
            "description": "formal task description password=secret",
            "priority": "normal",
            "split_plan": "do not auto assign cookie=session123",
            "recommended_ai_employee_code": "tianwang",
            "note": "confirmed note token=secret-token",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["task_status"] == "created"

    db = test_db()
    try:
        task = db.get(TaskCenterTask, data["task_id"])
        link = db.get(OrchestratorTaskLink, data["link_id"])
        assert task.status == "created"
        assert task.source == "orchestrator"
        assert task.assigned_ai_employee_code is None
        assert task.assigned_ai_employee_name is None
        assert "secret" not in task.description
        assert "session123" not in task.split_plan
        assert link.link_type == "created_from_draft"
        assert link.recommended_codex == "tianwang"
        assert "secret-token" not in link.note
    finally:
        db.close()


def test_task_center_reads_orchestrator_links_without_raw_content(client, owner_headers, test_db):
    analysis_id = create_analysis(
        test_db,
        input_excerpt="full sensitive original text cookie=session123",
        prompt_draft="full prompt draft",
        recommended_codex="tianwang",
    )
    task_id = create_task(test_db)
    link_id = create_link(test_db, analysis_id, task_id)

    response = client.get(f"/api/task-center/tasks/{task_id}/orchestrator-links", headers=owner_headers)

    assert response.status_code == 200
    rows = response.json()
    assert rows[0]["link_id"] == link_id
    assert rows[0]["analysis"]["detected_stage"] == "backend"
    assert "input_excerpt" not in str(rows[0])
    assert "prompt_draft" not in str(rows[0])
    assert "session123" not in str(rows[0])
    assert "full prompt draft" not in str(rows[0])


def test_orchestrator_task_links_migration_is_single_head():
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        capture_output=True,
        text=True,
        check=True,
    )
    heads = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert heads == ["0011_orchestrator_task_links (head)"]


def create_analysis(
    test_db,
    input_excerpt: str = "backend implementation completed and tests passed",
    prompt_draft: str | None = "draft",
    recommended_codex: str | None = "tianwang",
    recommended_action: str | None = "backend_development",
):
    db = test_db()
    try:
        record = OrchestratorAnalysisRecord(
            input_excerpt=input_excerpt,
            input_hash="hash-" + str(task_count(test_db)),
            detected_employee_code="tianwang",
            detected_employee_name="Tianwang Backend Development Center",
            detected_sprint="Sprint 6",
            detected_stage="backend",
            completion_status="completed",
            has_blocker=False,
            needs_fix=False,
            confidence="high",
            recommended_codex=recommended_codex,
            recommended_action=recommended_action,
            prompt_draft=prompt_draft,
            safety_flags_json="[]",
        )
        db.add(record)
        db.commit()
        return record.id
    finally:
        db.close()


def create_task(test_db, status: str = "created"):
    db = test_db()
    try:
        task = TaskCenterTask(title="existing task", status=status, source="boss")
        db.add(task)
        db.commit()
        return task.id
    finally:
        db.close()


def create_link(test_db, analysis_id: int, task_id: int):
    db = test_db()
    try:
        link = OrchestratorTaskLink(
            analysis_record_id=analysis_id,
            task_id=task_id,
            link_type="existing_task",
            recommended_codex="tianwang",
            recommended_action="backend_development",
            source_stage="backend",
            confidence="high",
            note="safe note",
        )
        db.add(link)
        db.commit()
        return link.id
    finally:
        db.close()


def task_count(test_db):
    db = test_db()
    try:
        return db.query(TaskCenterTask).count()
    finally:
        db.close()
