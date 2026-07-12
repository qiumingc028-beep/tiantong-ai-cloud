from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.auth import hash_password
from backend.main import app
from backend.models import Role, User
from backend.tool_center.models import EmployeeToolBinding, ToolExecutionLog, ToolRegistry
from tests.test_helpers import latest_alembic_head


def create_employee_user(test_db, username: str, role: str = "operator"):
    db = test_db()
    try:
        if not db.query(Role).filter(Role.code == role).first():
            db.add(Role(code=role, name=role, permissions=[]))
            db.commit()
        if not db.query(User).filter(User.username == username).first():
            db.add(User(username=username, password_hash=hash_password("password"), role=role, display_name=username, active=True))
            db.commit()
    finally:
        db.close()


def login_headers(client, username: str):
    response = client.post("/api/login", json={"username": username, "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_tool_center_routes_registered():
    paths = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    assert paths["/api/tools/list"] == {"GET"}
    assert paths["/api/tools/{tool_name}"] == {"GET"}
    assert paths["/api/tools/employees/{code}"] == {"GET"}
    assert paths["/api/tools/check"] == {"POST"}
    assert paths["/api/tools/call"] == {"POST"}
    assert paths["/api/tools/logs"] == {"GET"}


def test_tool_center_requires_login_and_rejects_viewer(client, viewer_headers):
    client.cookies.clear()
    assert client.get("/api/tools/list").status_code == 401
    assert client.get("/api/tools/list", headers=viewer_headers).status_code == 403
    assert client.get("/api/tools/employees/tiancai", headers=viewer_headers).status_code == 403
    assert client.post("/api/tools/check", headers=viewer_headers, json={"employee_code": "tiancai", "tool_name": "browser_search"}).status_code == 403


def test_owner_can_view_tool_registry_and_detail(client, owner_headers):
    response = client.get("/api/tools/list", headers=owner_headers)
    assert response.status_code == 200
    tools = response.json()["tools"]
    assert any(tool["tool_name"] == "browser_search" for tool in tools)
    assert any(tool["tool_name"] == "excel_analyzer" for tool in tools)

    detail = client.get("/api/tools/browser_search", headers=owner_headers)
    assert detail.status_code == 200
    assert detail.json()["tool"]["risk_level"] == "high"


def test_employee_tool_binding_scope(client, test_db):
    create_employee_user(test_db, "tiancai")
    headers = login_headers(client, "tiancai")
    own = client.get("/api/tools/employees/tiancai", headers=headers)
    assert own.status_code == 200
    assert any(row["tool_name"] == "excel_analyzer" for row in own.json()["tools"])
    assert client.get("/api/tools/employees/tianchuang", headers=headers).status_code == 403


def test_tool_permission_check_allows_low_risk_and_blocks_forbidden(client, owner_headers):
    allowed = client.post(
        "/api/tools/check",
        headers=owner_headers,
        json={"employee_code": "tiancai", "tool_name": "excel_analyzer"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["allowed"] is True
    assert allowed.json()["require_approval"] is False

    blocked = client.post(
        "/api/tools/check",
        headers=owner_headers,
        json={"employee_code": "tiancai", "tool_name": "delete_data", "boss_confirmed": True, "security_audited": True},
    )
    assert blocked.status_code == 200
    assert blocked.json()["allowed"] is False
    assert blocked.json()["require_approval"] is True


def test_high_risk_tool_requires_boss_and_security_audit(client, owner_headers):
    blocked = client.post(
        "/api/tools/check",
        headers=owner_headers,
        json={"employee_code": "tiancai", "tool_name": "browser_search"},
    )
    assert blocked.status_code == 200
    assert blocked.json()["allowed"] is False
    assert blocked.json()["require_approval"] is True
    assert "老板确认" in blocked.json()["reason"]

    approved = client.post(
        "/api/tools/check",
        headers=owner_headers,
        json={"employee_code": "tiancai", "tool_name": "browser_search", "boss_confirmed": True, "security_audited": True},
    )
    assert approved.status_code == 200
    assert approved.json()["allowed"] is True
    assert approved.json()["risk_level"] == "high"


def test_tool_call_is_dry_run_and_writes_log(client, owner_headers, test_db):
    response = client.post(
        "/api/tools/call",
        headers=owner_headers,
        json={
            "employee_code": "tiancai",
            "tool_name": "browser_search",
            "request": {"query": "男表市场趋势"},
            "boss_confirmed": True,
            "security_audited": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "approved"
    assert data["mode"] == "simulation"
    assert data["log_id"]

    db = test_db()
    try:
        log = db.query(ToolExecutionLog).filter(ToolExecutionLog.id == data["log_id"]).one()
        assert log.employee_code == "tiancai"
        assert log.tool_name == "browser_search"
        assert log.status == "approved"
        assert "男表市场趋势" in log.request
    finally:
        db.close()

    logs = client.get("/api/tools/logs", headers=owner_headers)
    assert logs.status_code == 200
    assert any(row["id"] == data["log_id"] for row in logs.json()["logs"])


def test_blocked_tool_call_writes_blocked_log(client, owner_headers):
    response = client.post(
        "/api/tools/call",
        headers=owner_headers,
        json={"employee_code": "tiancai", "tool_name": "browser_search", "request": {"query": "test"}},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "blocked"

    logs = client.get("/api/tools/logs", headers=owner_headers)
    assert any(row["status"] == "blocked" and row["tool_name"] == "browser_search" for row in logs.json()["logs"])


def test_unknown_tool_denied(client, owner_headers):
    response = client.post(
        "/api/tools/check",
        headers=owner_headers,
        json={"employee_code": "tiancai", "tool_name": "unknown_tool"},
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is False
    assert response.json()["permission_level"] == "not_configured"


def test_tool_center_does_not_leak_sensitive_fields(client, owner_headers):
    response = client.post(
        "/api/tools/call",
        headers=owner_headers,
        json={
            "employee_code": "tiancai",
            "tool_name": "excel_analyzer",
            "request": {"password": "bad", "token": "bad", "query": "safe"},
        },
    )
    assert response.status_code == 200
    logs = client.get("/api/tools/logs", headers=owner_headers)
    payload = str(logs.json()).lower()
    assert "password" not in payload
    assert "token" not in payload
    assert "secret" not in payload
    assert "api key" not in payload
    assert "authorization" not in payload
    assert "bearer" not in payload


def test_tool_center_source_has_no_real_external_execution_calls():
    files = [
        Path("backend/routers/tool_center.py"),
        Path("backend/tool_center/gateway.py"),
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


def test_tool_center_migration_head_and_tables():
    assert {"tool_registry", "employee_tool_binding", "tool_execution_logs"} <= set(ToolRegistry.metadata.tables)
    assert "employee_tool_binding" in set(EmployeeToolBinding.metadata.tables)
    assert "tool_execution_logs" in set(ToolExecutionLog.metadata.tables)
    script = ScriptDirectory.from_config(Config(str(Path("alembic.ini"))))
    assert script.get_heads() == [latest_alembic_head()]
