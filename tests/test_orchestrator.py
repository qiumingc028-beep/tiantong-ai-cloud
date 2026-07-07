import subprocess
import sys

from backend.models import AiEmployee, TaskCenterTask
from backend.orchestrator_models import OrchestratorAnalysisRecord, OrchestratorPromptConfirmation


def auth_headers(client, username: str):
    response = client.post("/api/login", json={"username": username, "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_orchestrator_requires_login(client):
    response = client.get("/api/orchestrator/analysis-records")
    assert response.status_code == 401


def test_orchestrator_rejects_non_privileged_roles(client):
    for username in ["operator", "customer_service", "designer", "editor", "viewer"]:
        headers = auth_headers(client, username)
        assert client.get("/api/orchestrator/analysis-records", headers=headers).status_code == 403
        assert client.get("/api/orchestrator/sprints/current", headers=headers).status_code == 403
        assert client.post("/api/orchestrator/analyze-reply", headers=headers, json={"reply_text": "test"}).status_code == 403


def test_orchestrator_allows_boss_owner_admin(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        response = client.get("/api/orchestrator/analysis-records", headers=headers)
        assert response.status_code == 200


def test_analyze_reply_detects_backend_completion_and_writes_safe_record(client, owner_headers, test_db):
    add_employee(test_db, "tianjian_test", "天检：测试验收中心", "test", 50)
    long_secret = "password=super-secret-token"
    reply = (
        "你是【天王：后端开发中心】。\n"
        "现在执行《天统AI公司 V1 Sprint 5》的后端实现任务。\n"
        "AI Orchestrator MVP 后端已完成，测试通过，可以进入下一步。\n"
        f"{long_secret}\n"
        + ("补充说明" * 400)
    )
    response = client.post(
        "/api/orchestrator/analyze-reply",
        headers=owner_headers,
        json={"reply_text": reply, "context": {"sprint": "Sprint 5"}},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["detected_employee"]["employee_code"] == "tianwang"
    assert data["detected_sprint"] == "Sprint 5"
    assert data["detected_stage"] == "backend"
    assert data["completion_status"] == "completed"
    assert data["has_blocker"] is False
    assert data["recommended_next"]["target_codex"] == "tianjian_test"
    assert data["recommended_next"]["is_suggestion"] is True
    assert "super-secret-token" not in data["prompt_draft"]

    db = test_db()
    try:
        record = db.get(OrchestratorAnalysisRecord, data["analysis_id"])
        assert record is not None
        assert len(record.input_excerpt) <= 1500
        assert "super-secret-token" not in record.input_excerpt
        assert len(record.input_hash) == 64
        assert record.recommended_codex == "tianjian_test"
    finally:
        db.close()


def test_analyze_reply_detects_blocker_and_generates_fix_suggestion(client, owner_headers):
    response = client.post(
        "/api/orchestrator/analyze-reply",
        headers=owner_headers,
        json={"reply_text": "天王后端任务测试失败，回归失败，存在阻断，无法继续。"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["has_blocker"] is True
    assert data["needs_fix"] is True
    assert data["recommended_next"]["target_codex"] == "tianwang"
    assert any(item["type"] == "test_failure" for item in data["blockers"])
    assert "修复" in data["recommended_next"]["action"]


def test_analyze_reply_redacts_cookie_equals_from_record_and_prompt(client, owner_headers, test_db):
    analysis_id, prompt_draft = create_sensitive_analysis(client, owner_headers, "cookie=session123")
    assert "session123" not in prompt_draft
    assert "[REDACTED]" in prompt_draft
    assert_saved_analysis_is_redacted(test_db, analysis_id, "session123")


def test_analyze_reply_redacts_cookie_header_from_record_and_prompt(client, owner_headers, test_db):
    analysis_id, prompt_draft = create_sensitive_analysis(client, owner_headers, "Cookie: session123")
    assert "session123" not in prompt_draft
    assert_saved_analysis_is_redacted(test_db, analysis_id, "session123")


def test_analyze_reply_redacts_set_cookie_header_from_record_and_prompt(client, owner_headers, test_db):
    analysis_id, prompt_draft = create_sensitive_analysis(client, owner_headers, "Set-Cookie: session123")
    assert "session123" not in prompt_draft
    assert_saved_analysis_is_redacted(test_db, analysis_id, "session123")


def test_analyze_reply_redacts_tiantong_session_from_record_and_prompt(client, owner_headers, test_db):
    analysis_id, prompt_draft = create_sensitive_analysis(client, owner_headers, "tiantong_session=session123")
    assert "session123" not in prompt_draft
    assert_saved_analysis_is_redacted(test_db, analysis_id, "session123")


def test_confirm_next_prompt_records_only_allowed_statuses(client, owner_headers, test_db):
    analysis_id = create_analysis(client, owner_headers)
    response = client.post(
        "/api/orchestrator/confirm-next-prompt",
        headers=owner_headers,
        json={
            "analysis_id": analysis_id,
            "target_codex": "tianwang",
            "confirmed_prompt": "老板确认后的 Prompt",
            "confirm_status": "confirmed",
        },
    )
    assert response.status_code == 200
    confirmation_id = response.json()["confirmation_id"]

    db = test_db()
    try:
        confirmation = db.get(OrchestratorPromptConfirmation, confirmation_id)
        assert confirmation is not None
        assert confirmation.confirm_status == "confirmed"
        assert confirmation.target_codex == "tianwang"
    finally:
        db.close()

    copied = client.post(
        "/api/orchestrator/confirm-next-prompt",
        headers=owner_headers,
        json={
            "analysis_id": analysis_id,
            "target_codex": "tianwang",
            "confirmed_prompt": "已复制 Prompt",
            "confirm_status": "copied",
        },
    )
    assert copied.status_code == 200

    cancelled = client.post(
        "/api/orchestrator/confirm-next-prompt",
        headers=owner_headers,
        json={
            "analysis_id": analysis_id,
            "target_codex": "tianwang",
            "confirmed_prompt": "取消 Prompt",
            "confirm_status": "cancelled",
        },
    )
    assert cancelled.status_code == 200


def test_confirm_next_prompt_redacts_sensitive_confirmed_prompt_before_save(client, owner_headers, test_db):
    analysis_id = create_analysis(client, owner_headers)
    sensitive_prompt = (
        "cookie=session123 Cookie: session456 Set-Cookie: session789 "
        "tiantong_session=abc session=def sessionid=ghi session_id=jkl "
        "csrftoken=mno csrf_token=pqr token=tok password=pwd api_key=key "
        "DATABASE_URL=postgresql://user:pass@db/name REDIS_URL=redis://redis:6379/0"
    )
    response = client.post(
        "/api/orchestrator/confirm-next-prompt",
        headers=owner_headers,
        json={
            "analysis_id": analysis_id,
            "target_codex": "tianwang",
            "confirmed_prompt": sensitive_prompt,
            "confirm_status": "confirmed",
        },
    )

    assert response.status_code == 200
    db = test_db()
    try:
        confirmation = db.get(OrchestratorPromptConfirmation, response.json()["confirmation_id"])
        assert_sensitive_values_redacted(confirmation.confirmed_prompt)
    finally:
        db.close()


def test_confirm_next_prompt_redacts_sensitive_note_before_save(client, owner_headers, test_db):
    analysis_id = create_analysis(client, owner_headers)
    sensitive_note = (
        "cookie=session123 session=def token=tok password=pwd api_key=key "
        "DATABASE_URL=postgresql://user:pass@db/name REDIS_URL=redis://redis:6379/0"
    )
    response = client.post(
        "/api/orchestrator/confirm-next-prompt",
        headers=owner_headers,
        json={
            "analysis_id": analysis_id,
            "target_codex": "tianwang",
            "confirmed_prompt": "safe prompt",
            "confirm_status": "confirmed",
            "note": sensitive_note,
        },
    )

    assert response.status_code == 200
    db = test_db()
    try:
        confirmation = db.get(OrchestratorPromptConfirmation, response.json()["confirmation_id"])
        assert_sensitive_values_redacted(confirmation.note)
    finally:
        db.close()


def test_confirm_next_prompt_rejects_execution_statuses(client, owner_headers):
    analysis_id = create_analysis(client, owner_headers)
    for status in ["sent_to_codex", "executed", "deployed", "merged", "typo"]:
        response = client.post(
            "/api/orchestrator/confirm-next-prompt",
            headers=owner_headers,
            json={
                "analysis_id": analysis_id,
                "target_codex": "tianwang",
                "confirmed_prompt": "Prompt",
                "confirm_status": status,
            },
        )
        assert response.status_code == 400


def test_analysis_records_return_summary_without_full_input(client, owner_headers):
    analysis_id = create_analysis(client, owner_headers, reply_text="天王后端实现已完成，测试通过。" + ("完整原文" * 200))
    response = client.get("/api/orchestrator/analysis-records?limit=1", headers=owner_headers)

    assert response.status_code == 200
    rows = response.json()
    assert rows[0]["id"] == analysis_id
    assert "input_excerpt" not in rows[0]
    assert "prompt_draft" not in rows[0]


def test_current_sprint_chain_uses_latest_analysis(client, owner_headers):
    create_analysis(client, owner_headers, reply_text="天王后端实现已完成，测试通过。")
    response = client.get("/api/orchestrator/sprints/current", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    stages = [item["stage"] for item in data["chain"]]
    assert stages == ["product", "architecture", "backend", "frontend", "test", "audit", "deploy", "summary"]
    backend = next(item for item in data["chain"] if item["stage"] == "backend")
    assert backend["status"] == "current"


def test_orchestrator_does_not_touch_task_center(client, owner_headers, test_db):
    db = test_db()
    try:
        task = TaskCenterTask(title="existing task", status="created")
        db.add(task)
        db.commit()
        task_id = task.id
    finally:
        db.close()

    create_analysis(client, owner_headers)

    db = test_db()
    try:
        task = db.get(TaskCenterTask, task_id)
        assert task.status == "created"
    finally:
        db.close()


def test_orchestrator_migration_is_single_head():
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        capture_output=True,
        text=True,
        check=True,
    )
    heads = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert heads == ["0016_sprint20_employee_evolution (head)"]


def add_employee(test_db, employee_code: str, employee_name: str, task_type: str, sort_order: int):
    db = test_db()
    try:
        if not db.query(AiEmployee).filter(AiEmployee.employee_code == employee_code).one_or_none():
            db.add(
                AiEmployee(
                    employee_code=employee_code,
                    employee_name=employee_name,
                    legion="研发交付军团",
                    duty=task_type,
                    status="active",
                    task_types=f'["{task_type}"]',
                    default_permissions="[]",
                    is_legacy=False,
                    sort_order=sort_order,
                )
            )
            db.commit()
    finally:
        db.close()


def create_analysis(client, headers, reply_text: str = "你是【天王：后端开发中心】。Sprint 5 后端实现已完成，测试通过。"):
    response = client.post(
        "/api/orchestrator/analyze-reply",
        headers=headers,
        json={"reply_text": reply_text, "context": {"sprint": "Sprint 5"}},
    )
    assert response.status_code == 200
    return response.json()["analysis_id"]


def create_sensitive_analysis(client, headers, sensitive_text: str):
    response = client.post(
        "/api/orchestrator/analyze-reply",
        headers=headers,
        json={
            "reply_text": f"你是【天王：后端开发中心】。Sprint 5 后端实现已完成，测试通过。 {sensitive_text}",
            "context": {"sprint": "Sprint 5"},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert any(item["type"] == "sensitive_text_redacted" for item in data["safety_flags"])
    return data["analysis_id"], data["prompt_draft"]


def assert_saved_analysis_is_redacted(test_db, analysis_id: int, sensitive_value: str):
    db = test_db()
    try:
        record = db.get(OrchestratorAnalysisRecord, analysis_id)
        assert sensitive_value not in record.input_excerpt
        assert sensitive_value not in record.prompt_draft
        assert "[REDACTED]" in record.input_excerpt
        assert "[REDACTED]" in record.prompt_draft
        assert "sensitive_text_redacted" in record.safety_flags_json
    finally:
        db.close()


def assert_sensitive_values_redacted(value: str):
    assert "[REDACTED]" in value
    for secret in [
        "session123",
        "session456",
        "session789",
        "abc",
        "def",
        "ghi",
        "jkl",
        "mno",
        "pqr",
        "tok",
        "pwd",
        "key",
        "postgresql://user:pass@db/name",
        "redis://redis:6379/0",
    ]:
        assert secret not in value
