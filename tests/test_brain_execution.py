from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.brain_execution.models import BrainApprovalRecord, BrainExecutionRun, BrainToolCall
from backend.brain_orchestrator.models import BrainTaskNode
from backend.brain_tool_router.models import BrainExecutionLog
from backend.main import app


def test_brain_execution_routes_registered():
    paths = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    assert paths["/api/brain/analyze"] == {"POST"}
    assert paths["/api/brain/plan"] == {"POST"}
    assert paths["/api/brain/approve"] == {"POST"}
    assert paths["/api/brain/start"] == {"POST"}
    assert paths["/api/brain/queue/status"] == {"GET"}
    assert paths["/api/brain/tasks/{execution_id}"] == {"GET"}
    assert paths["/api/brain/executions/{execution_id}"] == {"GET"}
    assert paths["/api/brain/logs"] == {"GET"}


def test_brain_execution_requires_login_and_rejects_viewer(client, viewer_headers):
    client.cookies.clear()
    assert client.post("/api/brain/analyze", json={"goal": "分析今天销售下降原因"}).status_code == 401
    assert client.post("/api/brain/analyze", headers=viewer_headers, json={"goal": "分析今天销售下降原因"}).status_code == 403
    assert client.get("/api/brain/logs", headers=viewer_headers).status_code == 403


def test_brain_execution_analyze_returns_dry_run_graph(client, owner_headers):
    response = client.post("/api/brain/analyze", headers=owner_headers, json={"goal": "分析京东60店最近销量下降原因"})

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["mode"] == "simulation"
    assert data["execution_id"]
    assert data["run"]["status"] == "ANALYZED"
    assert data["nodes"]
    assert data["edges"]
    employee_codes = {row["employee_code"] for row in data["employees"]}
    assert {"tiancai_data", "tianshu", "tianshang", "tiance_strategy"} <= employee_codes


def test_brain_execution_plan_persists_nodes_tool_checks_and_logs(client, owner_headers, test_db):
    response = client.post("/api/brain/plan", headers=owner_headers, json={"goal": "分析京东60店最近销量下降原因"})

    assert response.status_code == 200
    data = response.json()
    execution_id = data["execution_id"]
    assert data["dry_run"] is True
    assert data["mode"] == "simulation"
    assert data["run"]["status"] == "WAIT_APPROVAL"
    assert data["nodes"]
    assert data["edges"]
    assert data["tool_calls"]

    db = test_db()
    try:
        assert db.get(BrainExecutionRun, execution_id) is not None
        assert db.query(BrainTaskNode).filter(BrainTaskNode.execution_id == execution_id).count() >= 4
        assert db.query(BrainToolCall).filter(BrainToolCall.execution_id == execution_id).count() >= 1
        assert db.query(BrainExecutionLog).filter(BrainExecutionLog.run_id == str(execution_id)).count() >= 1
    finally:
        db.close()


def test_brain_execution_high_risk_blocks_start_until_double_approval(client, owner_headers):
    plan = client.post("/api/brain/plan", headers=owner_headers, json={"goal": "分析销售下降并部署生产修复"})
    assert plan.status_code == 200
    execution_id = plan.json()["execution_id"]
    assert plan.json()["run"]["risk_level"] == "high"
    assert plan.json()["run"]["status"] == "WAIT_APPROVAL"

    blocked = client.post("/api/brain/start", headers=owner_headers, json={"execution_id": execution_id})
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"

    half_approval = client.post(
        "/api/brain/approve",
        headers=owner_headers,
        json={"execution_id": execution_id, "boss_confirm": True, "security_audited": False},
    )
    assert half_approval.status_code == 200
    assert half_approval.json()["status"] == "WAIT_APPROVAL"

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
    assert started.json()["status"] == "APPROVED"


def test_brain_execution_start_is_dry_run_and_writes_execution_logs(client, owner_headers):
    plan = client.post("/api/brain/plan", headers=owner_headers, json={"goal": "分析今天销售下降原因"})
    execution_id = plan.json()["execution_id"]
    started = client.post("/api/brain/start", headers=owner_headers, json={"execution_id": execution_id})
    assert started.status_code == 200
    assert started.json()["status"] == "blocked"

    approved = client.post(
        "/api/brain/approve",
        headers=owner_headers,
        json={"execution_id": execution_id, "boss_confirm": True, "security_audited": True},
    )
    assert approved.status_code == 200
    started = client.post("/api/brain/start", headers=owner_headers, json={"execution_id": execution_id})
    assert started.status_code == 200
    assert started.json()["queued"] is True

    logs = client.get("/api/brain/logs", headers=owner_headers)
    assert logs.status_code == 200
    rows = logs.json()["logs"]
    assert rows
    assert any(row["run_id"] == str(execution_id) and row["action"] == "queued_for_worker" for row in rows)
    assert all("password_hash" not in str(row) for row in rows)


def test_brain_execution_approve_and_start_require_privileged_role(client, operator_headers, owner_headers):
    plan = client.post("/api/brain/plan", headers=owner_headers, json={"goal": "分析今天销售下降原因"})
    execution_id = plan.json()["execution_id"]
    client.cookies.clear()
    assert client.post("/api/brain/approve", headers=operator_headers, json={"execution_id": execution_id}).status_code == 403
    assert client.post("/api/brain/start", headers=operator_headers, json={"execution_id": execution_id}).status_code == 403


def test_brain_execution_source_has_no_real_execution_calls():
    files = [
        Path("backend/brain_execution/planner.py"),
        Path("backend/brain_execution/executor.py"),
        Path("backend/brain_execution/router.py"),
    ]
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
    for path in files:
        source = path.read_text()
        for needle in forbidden:
            assert needle not in source


def test_brain_execution_migration_head_and_tables():
    assert "brain_execution_runs" in set(BrainExecutionRun.metadata.tables)
    assert "brain_approval_records" in set(BrainApprovalRecord.metadata.tables)
    assert "brain_tool_calls" in set(BrainToolCall.metadata.tables)
    script = ScriptDirectory.from_config(Config(str(Path("alembic.ini"))))
    assert script.get_heads() == ["0024_sprint25_brain_runtime"]
