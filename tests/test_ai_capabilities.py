from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.ai_capabilities.models import AiCapability, ToolPermission
from backend.auth import hash_password
from backend.main import app
from backend.models import Role, User


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


def test_ai_capability_routes_registered():
    paths = {getattr(route, "path", ""): getattr(route, "methods", set()) for route in app.routes}
    assert paths["/api/capabilities/employees/{code}"] == {"GET"}
    assert paths["/api/capabilities/list"] == {"GET"}
    assert paths["/api/capabilities/create"] == {"POST"}
    assert paths["/api/tools/permissions/{code}"] == {"GET"}
    assert paths["/api/tools/check"] == {"POST"}


def test_ai_capability_requires_login_and_rejects_viewer(client, viewer_headers):
    client.cookies.clear()
    assert client.get("/api/capabilities/list").status_code == 401
    assert client.get("/api/capabilities/list", headers=viewer_headers).status_code == 403
    assert client.get("/api/tools/permissions/tiancai", headers=viewer_headers).status_code == 403
    assert client.post("/api/tools/check", headers=viewer_headers, json={"employee_code": "tiancai", "tool_name": "database_read"}).status_code == 403


def test_owner_admin_boss_can_view_capabilities(client, owner_headers, admin_headers, boss_headers):
    for headers in (owner_headers, admin_headers, boss_headers):
        response = client.get("/api/capabilities/list", headers=headers)
        assert response.status_code == 200
        assert response.json()["capabilities"]
        permissions = client.get("/api/tools/permissions/tiancai", headers=headers)
        assert permissions.status_code == 200
        assert permissions.json()["permissions"]


def test_owner_can_create_capability(client, owner_headers, test_db):
    response = client.post(
        "/api/capabilities/create",
        headers=owner_headers,
        json={
            "employee_code": "tianyu",
            "employee_name": "天誉：GEO/SEO品牌增长中心",
            "capability_name": "GEO分析增强",
            "capability_type": "geo_analysis",
            "description": "生成 GEO 分析建议，不自动调用外部 API。",
            "enabled": True,
        },
    )
    assert response.status_code == 200
    data = response.json()["capability"]
    assert data["employee_code"] == "tianyu"
    assert data["enabled"] is True

    db = test_db()
    try:
        assert db.query(AiCapability).filter(AiCapability.employee_code == "tianyu").count() == 1
    finally:
        db.close()


def test_employee_can_only_view_own_capabilities_and_permissions(client, test_db):
    create_employee_user(test_db, "tiancai")
    headers = login_headers(client, "tiancai")
    own = client.get("/api/capabilities/employees/tiancai", headers=headers)
    assert own.status_code == 200
    assert {row["employee_code"] for row in own.json()["capabilities"]} == {"tiancai"}
    assert client.get("/api/capabilities/employees/tianyu", headers=headers).status_code == 403
    assert client.get("/api/tools/permissions/tiancai", headers=headers).status_code == 200
    assert client.get("/api/tools/permissions/tianyu", headers=headers).status_code == 403


def test_tool_permission_check_allows_readonly_and_blocks_forbidden(client, owner_headers):
    allowed = client.post(
        "/api/tools/check",
        headers=owner_headers,
        json={"employee_code": "tiancai", "tool_name": "database_read"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["allowed"] is True
    assert allowed.json()["require_approval"] is False

    forbidden = client.post(
        "/api/tools/check",
        headers=owner_headers,
        json={"employee_code": "tiancai", "tool_name": "delete_data", "boss_confirmed": True, "security_audited": True},
    )
    assert forbidden.status_code == 200
    assert forbidden.json()["allowed"] is False
    assert forbidden.json()["require_approval"] is True


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
    assert approved.json()["require_approval"] is True


def test_unknown_tool_is_denied(client, owner_headers):
    response = client.post(
        "/api/tools/check",
        headers=owner_headers,
        json={"employee_code": "tiancai", "tool_name": "not_registered_tool"},
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is False
    assert response.json()["permission_level"] == "not_configured"


def test_ai_capabilities_do_not_leak_sensitive_fields(client, owner_headers):
    responses = [
        client.get("/api/capabilities/list", headers=owner_headers),
        client.get("/api/capabilities/employees/tiancai", headers=owner_headers),
        client.get("/api/tools/permissions/tiancai", headers=owner_headers),
        client.post("/api/tools/check", headers=owner_headers, json={"employee_code": "tiancai", "tool_name": "database_read"}),
    ]
    for response in responses:
        assert response.status_code == 200
        payload = str(response.json()).lower()
        for word in ["password_hash", "token", "secret", "api key", "authorization", "bearer"]:
            assert word not in payload


def test_ai_capabilities_source_has_no_external_execution_calls():
    source = Path("backend/routers/ai_capabilities.py").read_text()
    forbidden = [
        "subprocess",
        "os.system",
        "shell=True",
        "requests.",
        "httpx.",
        "docker.from_env",
        "subprocess.run",
    ]
    for needle in forbidden:
        assert needle not in source


def test_ai_capabilities_migration_head_and_tables():
    assert {"ai_capabilities", "tool_permissions"} <= set(AiCapability.metadata.tables)
    script = ScriptDirectory.from_config(Config(str(Path("alembic.ini"))))
    assert script.get_heads() == ["0018_sprint21_ai_capabilities"]


def test_tool_permission_model_registered():
    assert "tool_permissions" in set(ToolPermission.metadata.tables)
