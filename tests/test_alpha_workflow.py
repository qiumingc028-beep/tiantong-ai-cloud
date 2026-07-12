from backend.alpha_workflow.models import AlphaWorkflowRun
from backend.config import get_settings


ALPHA_FEATURE_FLAGS = {
    "ALPHA_WORKFLOW_ENABLED": "true",
    "ALPHA_WORKFLOW_DASHBOARD_ENABLED": "true",
    "PUBLIC_RESEARCH_ENABLED": "true",
    "PUBLIC_SEARCH_ENABLED": "true",
    "PUBLIC_SEARCH_PROVIDER": "mock",
    "KNOWLEDGE_CENTER_ENABLED": "true",
    "KNOWLEDGE_SUBMISSION_ENABLED": "true",
    "KNOWLEDGE_LOCAL_SEARCH_ENABLED": "true",
    "SKILLS_ENGINE_ENABLED": "true",
    "SKILL_INSTALLATION_ENABLED": "true",
    "SKILL_INVOCATION_ENABLED": "true",
}


def enable_alpha_stack(monkeypatch):
    for key, value in ALPHA_FEATURE_FLAGS.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()


def test_alpha_workflow_demo_runs_full_chain(client, boss_headers, monkeypatch, test_db):
    enable_alpha_stack(monkeypatch)

    response = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "研究 Apple 最新 AI 战略"},
    )

    assert response.status_code == 200
    run = response.json()["run"]
    assert run["status"] == "已完成"
    assert run["task_id"]
    assert run["research_execution_id"]
    assert run["knowledge_id"]
    assert run["skill_invocation_id"]
    assert run["quality_score"] >= 80
    assert run["risk_level"] in {"低", "中"}
    assert len(run["workflow_context"]["step_trace"]) == 7

    task_response = client.get(f"/api/task-center/tasks/{run['task_id']}", headers=boss_headers)
    assert task_response.status_code == 200
    task = task_response.json()
    assert task["status"] == "summarized"
    assert task["results"]
    assert "Apple" in task["results"][0]["result_content"]

    research_response = client.get(f"/api/v2/research/executions/{run['research_execution_id']}", headers=boss_headers)
    assert research_response.status_code == 200
    research = research_response.json()["execution"]
    assert research["report_title"]
    assert research["source_count"] >= 1
    assert research["report_hash"]

    knowledge_response = client.get(f"/api/v2/knowledge/{run['knowledge_id']}", headers=boss_headers)
    assert knowledge_response.status_code == 200
    knowledge = knowledge_response.json()["knowledge"]
    assert knowledge["title"] == "Apple 最新 AI 战略研究"
    assert knowledge["current_version_id"]

    skill_response = client.get("/api/v2/skills/invocations", headers=boss_headers)
    assert skill_response.status_code == 200
    invocations = skill_response.json()["invocations"]
    assert any(item["skill_code"] == "knowledge.local.search" for item in invocations)

    detail_response = client.get(f"/api/v2/alpha-workflows/runs/{run['run_id']}", headers=boss_headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()["run"]
    assert len(detail["events"]) >= 7
    assert any(event["event_code"] == "workflow_completed" for event in detail["events"])


def test_alpha_workflow_recovery_reuses_root_trace_and_checkpoint(client, boss_headers, monkeypatch, test_db):
    enable_alpha_stack(monkeypatch)

    first = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "研究 Apple 最新 AI 战略"},
    )
    assert first.status_code == 200
    original_run = first.json()["run"]

    db = test_db()
    try:
        row = db.get(AlphaWorkflowRun, original_run["run_id"])
        row.status = "已失败"
        row.recovery_status = "待恢复"
        db.commit()
    finally:
        db.close()

    recovered = client.post(
        f"/api/v2/alpha-workflows/runs/{original_run['run_id']}/recover",
        headers=boss_headers,
        json={"reason": "验证失败恢复"},
    )
    assert recovered.status_code == 200
    recovered_run = recovered.json()["run"]
    assert recovered_run["status"] == "已完成"
    assert recovered_run["run_id"] == original_run["run_id"]
    assert recovered_run["trace_id"] == original_run["trace_id"]
    assert recovered_run["root_span_id"] == original_run["root_span_id"]
    assert recovered_run["workflow_context"]["recovery_from_run_id"] == original_run["run_id"]
    assert recovered_run["workflow_context"]["step_trace"][-1]["stage"] == "recovery"


def test_alpha_workflow_flags_default_off(client, boss_headers):
    get_settings.cache_clear()
    response = client.get("/api/v2/alpha-workflows/health", headers=boss_headers)

    assert response.status_code == 403
    assert "Alpha 工作流未启用" in response.json()["detail"]
