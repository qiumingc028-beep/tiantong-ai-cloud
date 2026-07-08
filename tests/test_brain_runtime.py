from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.brain_execution.models import BrainExecutionEvent, BrainExecutionRun
from backend.brain_execution.worker import process_next_execution
from backend.brain_tool_router.models import BrainExecutionLog


def test_brain_runtime_state_machine_requires_auth(client, viewer_headers):
    client.cookies.clear()
    assert client.post("/api/brain/analyze", json={"goal": "分析爆款手表机会"}).status_code == 401
    assert client.post("/api/brain/analyze", headers=viewer_headers, json={"goal": "分析爆款手表机会"}).status_code == 403
    assert client.get("/api/brain/executions/1", headers=viewer_headers).status_code == 403


def test_brain_runtime_state_flow_and_event_logs(client, owner_headers, test_db):
    analyze = client.post("/api/brain/analyze", headers=owner_headers, json={"goal": "帮我找一个爆款手表"})
    assert analyze.status_code == 200
    execution_id = analyze.json()["execution_id"]
    assert analyze.json()["run"]["status"] == "ANALYZED"

    plan = client.post(
        "/api/brain/plan",
        headers=owner_headers,
        json={"execution_id": execution_id, "goal": "帮我找一个爆款手表"},
    )
    assert plan.status_code == 200
    assert plan.json()["run"]["status"] == "WAIT_APPROVAL"
    assert plan.json()["nodes"]

    blocked = client.post("/api/brain/start", headers=owner_headers, json={"execution_id": execution_id})
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"

    approved = client.post(
        "/api/brain/approve",
        headers=owner_headers,
        json={"execution_id": execution_id, "boss_confirm": True, "security_audited": True},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"

    started = client.post("/api/brain/start", headers=owner_headers, json={"execution_id": execution_id})
    assert started.status_code == 200
    assert started.json()["queued"] is True
    assert started.json()["status"] == "QUEUED"

    db = test_db()
    try:
        result = process_next_execution(db, timeout=1)
        assert result["run"]["status"] == "SUCCESS"
    finally:
        db.close()

    detail = client.get(f"/api/brain/executions/{execution_id}", headers=owner_headers)
    assert detail.status_code == 200
    assert detail.json()["run"]["status"] == "SUCCESS"
    event_types = [row["event_type"] for row in detail.json()["events"]]
    assert "state_analyzed" in event_types
    assert "state_planned" in event_types
    assert "state_wait_approval" in event_types
    assert "state_approved" in event_types
    assert "state_queued" in event_types
    assert "worker_started" in event_types
    assert "state_success" in event_types

    db = test_db()
    try:
        run = db.get(BrainExecutionRun, execution_id)
        assert run is not None
        assert run.status == "SUCCESS"
        assert db.query(BrainExecutionEvent).filter(BrainExecutionEvent.execution_id == execution_id).count() >= 6
        assert db.query(BrainExecutionLog).filter(BrainExecutionLog.run_id == str(execution_id)).count() >= 4
    finally:
        db.close()


def test_brain_runtime_double_approval_required_even_for_low_risk(client, owner_headers):
    plan = client.post("/api/brain/plan", headers=owner_headers, json={"goal": "分析近期爆款手表趋势"})
    assert plan.status_code == 200
    execution_id = plan.json()["execution_id"]
    assert plan.json()["run"]["risk_level"] == "low"

    boss_only = client.post(
        "/api/brain/approve",
        headers=owner_headers,
        json={"execution_id": execution_id, "boss_confirm": True, "security_audited": False},
    )
    assert boss_only.status_code == 200
    assert boss_only.json()["status"] == "WAIT_APPROVAL"
    assert boss_only.json()["approval"]["blocked"] is True

    dual_confirm = client.post(
        "/api/brain/approve",
        headers=owner_headers,
        json={"execution_id": execution_id, "boss_confirm": True, "security_audited": True},
    )
    assert dual_confirm.status_code == 200
    assert dual_confirm.json()["status"] == "APPROVED"


def test_brain_runtime_operator_cannot_approve_or_start(client, owner_headers, operator_headers):
    plan = client.post("/api/brain/plan", headers=owner_headers, json={"goal": "分析近期爆款手表趋势"})
    execution_id = plan.json()["execution_id"]
    assert client.post("/api/brain/approve", headers=operator_headers, json={"execution_id": execution_id}).status_code == 403
    assert client.post("/api/brain/start", headers=operator_headers, json={"execution_id": execution_id}).status_code == 403


def test_brain_runtime_source_has_no_real_execution_calls():
    forbidden = [
        "subprocess",
        "os.system",
        "shell=True",
        "requests.",
        "httpx.",
        "webbrowser",
        "selenium",
        "playwright",
        "puppeteer",
        "docker.from_env",
        "git push",
    ]
    for path in [
        Path("backend/brain_execution/planner.py"),
        Path("backend/brain_execution/executor.py"),
        Path("backend/brain_execution/router.py"),
        Path("backend/brain_execution/state_machine.py"),
    ]:
        source = path.read_text()
        for needle in forbidden:
            assert needle not in source


def test_brain_runtime_migration_head_and_event_table():
    assert "brain_execution_events" in set(BrainExecutionEvent.metadata.tables)
    script = ScriptDirectory.from_config(Config(str(Path("alembic.ini"))))
    assert script.get_heads() == ["0025_sprint25_3_execution_engine_enhancement"]
