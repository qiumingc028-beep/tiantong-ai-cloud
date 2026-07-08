from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.auth import hash_password
from backend.main import app
from backend.models import Role, User
from backend.tool_router.models import ToolRoute, ToolRouteLog


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


def test_tool_router_routes_registered():
    paths = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    assert paths["/api/tool-router/routes"] == {"GET"}
    assert paths["/api/tool-router/check"] == {"POST"}
    assert paths["/api/tool-router/route"] == {"POST"}
    assert paths["/api/tool-router/logs"] == {"GET"}


def test_tool_router_requires_login_and_rejects_viewer(client, viewer_headers):
    client.cookies.clear()
    assert client.get("/api/tool-router/routes").status_code == 401
    assert client.get("/api/tool-router/routes", headers=viewer_headers).status_code == 403
    assert client.post("/api/tool-router/check", headers=viewer_headers, json={"employee_code": "tiancai", "tool_name": "excel_analyzer"}).status_code == 403


def test_owner_admin_boss_can_view_routes(client, owner_headers, admin_headers, boss_headers):
    for headers in (owner_headers, admin_headers, boss_headers):
        response = client.get("/api/tool-router/routes", headers=headers)
        assert response.status_code == 200
        assert response.json()["routes"]


def test_employee_can_only_route_own_tools(client, test_db):
    create_employee_user(test_db, "tiancai")
    headers = login_headers(client, "tiancai")
    own = client.get("/api/tool-router/routes", headers=headers)
    assert own.status_code == 200
    assert {row["employee_code"] for row in own.json()["routes"]} == {"tiancai"}
    other = client.post("/api/tool-router/check", headers=headers, json={"employee_code": "tianchuang", "tool_name": "image_reader"})
    assert other.status_code == 403


def test_tool_router_matches_excel_task_and_allows_low_risk(client, owner_headers, test_db):
    response = client.post(
        "/api/tool-router/route",
        headers=owner_headers,
        json={"employee_code": "tiancai", "task": "分析 Excel 销售报表", "requirement": "读取表格并输出趋势"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["recommended_tool"] == "excel_analyzer"
    assert data["allowed"] is True
    assert data["risk_level"] == "low"
    assert data["mode"] == "simulation"

    db = test_db()
    try:
        log = db.query(ToolRouteLog).filter(ToolRouteLog.recommended_tool == "excel_analyzer").one()
        assert log.employee_code == "tiancai"
        assert log.allowed is True
    finally:
        db.close()


def test_tool_router_high_risk_requires_boss_and_security_audit(client, owner_headers):
    blocked = client.post(
        "/api/tool-router/route",
        headers=owner_headers,
        json={"employee_code": "tiancai", "task": "搜索男表市场趋势", "requirement": "需要网页搜索"},
    )
    assert blocked.status_code == 200
    assert blocked.json()["recommended_tool"] == "browser_search"
    assert blocked.json()["allowed"] is False
    assert blocked.json()["require_approval"] is True
    assert "老板确认" in blocked.json()["reason"]

    approved = client.post(
        "/api/tool-router/route",
        headers=owner_headers,
        json={
            "employee_code": "tiancai",
            "task": "搜索男表市场趋势",
            "requirement": "需要网页搜索",
            "boss_confirmed": True,
            "security_audited": True,
        },
    )
    assert approved.status_code == 200
    assert approved.json()["recommended_tool"] == "browser_search"
    assert approved.json()["allowed"] is True
    assert approved.json()["risk_level"] == "high"


def test_tool_router_check_uses_tool_permission_gateway(client, owner_headers):
    response = client.post(
        "/api/tool-router/check",
        headers=owner_headers,
        json={"employee_code": "tiancai", "tool_name": "delete_data", "boss_confirmed": True, "security_audited": True},
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is False
    assert response.json()["mode"] == "simulation"


def test_tool_router_logs_endpoint(client, owner_headers):
    client.post(
        "/api/tool-router/route",
        headers=owner_headers,
        json={"employee_code": "tiancai", "task": "分析 Excel 报表", "requirement": "表格数据"},
    )
    logs = client.get("/api/tool-router/logs", headers=owner_headers)
    assert logs.status_code == 200
    assert logs.json()["logs"]
    assert {"employee_code", "recommended_tool", "risk_level", "allowed"} <= set(logs.json()["logs"][0])


def test_tool_router_source_has_no_external_execution_calls():
    files = [
        Path("backend/routers/tool_router.py"),
        Path("backend/tool_router/router_engine.py"),
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


def test_tool_router_migration_head_and_tables():
    assert {"tool_routes", "tool_route_logs"} <= set(ToolRoute.metadata.tables)
    assert "tool_route_logs" in set(ToolRouteLog.metadata.tables)
    script = ScriptDirectory.from_config(Config(str(Path("alembic.ini"))))
    assert script.get_heads() == ["0026_sprint26_ai_employee_execution_mvp"]

