from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.brain_tool_router.models import BrainExecutionLog
from backend.main import app


def test_brain_tool_router_routes_registered():
    paths = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    assert paths["/api/brain-tool-router/analyze"] == {"POST"}
    assert paths["/api/brain-tool-router/plan"] == {"POST"}
    assert paths["/api/brain-tool-router/approval-check"] == {"POST"}
    assert paths["/api/brain-tool-router/logs"] == {"GET"}


def test_brain_tool_router_requires_login_and_rejects_viewer(client, viewer_headers):
    client.cookies.clear()
    assert client.post("/api/brain-tool-router/analyze", json={"request_text": "分析男表趋势"}).status_code == 401
    assert client.post(
        "/api/brain-tool-router/analyze",
        headers=viewer_headers,
        json={"request_text": "分析男表趋势"},
    ).status_code == 403
    assert client.get("/api/brain-tool-router/logs", headers=viewer_headers).status_code == 403


def test_analyze_standardizes_task_intent_and_recommends_employee(client, owner_headers, test_db):
    response = client.post(
        "/api/brain-tool-router/analyze",
        headers=owner_headers,
        json={"request_text": "分析近期爆款手表市场趋势，并输出数据采集计划"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["task_type"] == "data_research"
    assert data["recommended_employee"]["employee_code"] == "tiancai"
    assert "browser_search" in data["required_tools"]
    assert data["risk_level"] in {"medium", "high"}
    assert data["approval_required"] is True
    assert data["task_intent"]["task_id"].startswith("brain-")
    assert data["task_intent"]["dry_run"] if "dry_run" in data["task_intent"] else True

    db = test_db()
    try:
        log = db.query(BrainExecutionLog).filter(BrainExecutionLog.recommended_employee == "tiancai").first()
        assert log is not None
        assert log.approval_status == "analysis_only"
    finally:
        db.close()


def test_plan_routes_tools_with_dry_run_and_logs(client, owner_headers, test_db):
    response = client.post(
        "/api/brain-tool-router/plan",
        headers=owner_headers,
        json={
            "request_text": "分析 Excel 销售报表并给出趋势",
            "boss_confirmed": False,
            "security_audited": False,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["employee"] == "tiancai"
    assert data["dry_run"] is True
    assert data["tools"]
    assert data["tools"][0]["mode"] == "simulation"
    assert data["tools"][0]["tool_name"] == "excel_analyzer"
    assert data["tools"][0]["allowed"] is True

    db = test_db()
    try:
        assert db.query(BrainExecutionLog).filter(BrainExecutionLog.execution_result == "plan_generated_dry_run").count() == 1
    finally:
        db.close()


def test_approval_check_blocks_medium_and_high_risk_without_required_confirmation(client, owner_headers):
    medium = client.post(
        "/api/brain-tool-router/approval-check",
        headers=owner_headers,
        json={"risk_level": "medium", "boss_confirmed": False, "security_audited": False},
    )
    assert medium.status_code == 403
    assert medium.json()["detail"]["approval_status"] == "needs_boss_confirmation"

    high = client.post(
        "/api/brain-tool-router/approval-check",
        headers=owner_headers,
        json={"risk_level": "high", "boss_confirmed": True, "security_audited": False},
    )
    assert high.status_code == 403
    assert high.json()["detail"]["approval_status"] == "blocked"

    approved = client.post(
        "/api/brain-tool-router/approval-check",
        headers=owner_headers,
        json={"risk_level": "high", "boss_confirmed": True, "security_audited": True},
    )
    assert approved.status_code == 200
    assert approved.json()["allowed"] is True


def test_plan_high_risk_tool_stays_blocked_without_double_approval(client, owner_headers):
    response = client.post(
        "/api/brain-tool-router/plan",
        headers=owner_headers,
        json={"request_text": "搜索市场趋势并联网采集竞品页面"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["approval_required"] is True
    assert any(tool["allowed"] is False for tool in data["tools"])
    assert any("老板确认" in (tool["reason"] or "") for tool in data["tools"])


def test_employee_scope_blocks_other_employee_recommendation(client, operator_headers):
    response = client.post(
        "/api/brain-tool-router/analyze",
        headers=operator_headers,
        json={"request_text": "分析近期爆款手表市场趋势"},
    )
    assert response.status_code == 403


def test_brain_tool_router_logs_endpoint(client, owner_headers):
    client.post(
        "/api/brain-tool-router/analyze",
        headers=owner_headers,
        json={"request_text": "分析 Excel 销售报表"},
    )
    response = client.get("/api/brain-tool-router/logs", headers=owner_headers)
    assert response.status_code == 200
    logs = response.json()["logs"]
    assert logs
    assert {"user_request", "ai_analysis_result", "recommended_employee", "tool_selection", "approval_status"} <= set(logs[0])


def test_brain_tool_router_source_has_no_real_execution_calls():
    files = [
        Path("backend/routers/brain_tool_router.py"),
        Path("backend/brain_tool_router/intent_engine.py"),
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
    ]
    for path in files:
        source = path.read_text()
        for needle in forbidden:
            assert needle not in source


def test_brain_tool_router_migration_head_and_table():
    assert "brain_execution_logs" in set(BrainExecutionLog.metadata.tables)
    script = ScriptDirectory.from_config(Config(str(Path("alembic.ini"))))
    assert script.get_heads() == ["0025_sprint25_3_execution_engine_enhancement"]

