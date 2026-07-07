from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.release_models import ReleaseVersion


def test_release_center_page_exists(client):
    response = client.get("/release-center.html")
    assert response.status_code == 200
    assert "Release Center" in response.text


def test_release_center_requires_login_and_rejects_viewer(client, viewer_headers, operator_headers):
    client.cookies.clear()
    assert client.get("/api/release/current").status_code == 401
    assert client.get("/api/release/check", headers=viewer_headers).status_code == 403
    assert client.post("/api/release/create", headers=viewer_headers, json={"version": "Sprint20-v1.0", "sprint_name": "Sprint20"}).status_code == 403
    assert client.get("/api/release/check", headers=operator_headers).status_code == 403


def test_release_center_check_returns_static_gate_status(client, owner_headers):
    response = client.get("/api/release/check", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert {"commit", "test", "migration", "docker", "nginx", "docs", "can_release"} <= set(data)
    assert data["commit"] is True
    assert data["test"] is True
    assert data["migration"] is True
    assert data["docker"] is True
    assert data["nginx"] is True
    assert data["docs"] is True
    assert data["can_release"] is True


def test_owner_can_create_release_without_deploying(client, owner_headers, test_db):
    response = client.post(
        "/api/release/create",
        headers=owner_headers,
        json={
            "version": "Sprint20-v1.0",
            "sprint_name": "Sprint20 Release Center",
            "commit_id": "7130d2816f778fca9dc26eeea87cdd24549c8d84",
            "branch": "main",
            "author": "tiantong",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["release"]["version"] == "Sprint20-v1.0"
    assert data["release"]["status"] == "draft"
    assert data["release"]["deploy_status"] == "waiting"

    db = test_db()
    try:
        release = db.query(ReleaseVersion).filter(ReleaseVersion.version == "Sprint20-v1.0").one()
        assert release.status == "draft"
        assert release.deploy_status == "waiting"
    finally:
        db.close()


def test_release_approval_requires_boss_and_security_flags(client, owner_headers):
    create_response = client.post(
        "/api/release/create",
        headers=owner_headers,
        json={"version": "Sprint20-v1.1", "sprint_name": "Sprint20"},
    )
    assert create_response.status_code == 200
    release_id = create_response.json()["release"]["id"]

    blocked = client.post("/api/release/approve", headers=owner_headers, json={"release_id": release_id, "boss_confirmed": True})
    assert blocked.status_code == 403

    approved = client.post(
        "/api/release/approve",
        headers=owner_headers,
        json={"release_id": release_id, "boss_confirmed": True, "security_audited": True},
    )
    assert approved.status_code == 200
    data = approved.json()["release"]
    assert data["status"] == "approved"
    assert data["deploy_status"] == "waiting"
    assert data["approved_by"] == "owner"


def test_release_current_returns_latest_release(client, admin_headers):
    assert client.post(
        "/api/release/create",
        headers=admin_headers,
        json={"version": "Sprint20-v1.2", "sprint_name": "Sprint20"},
    ).status_code == 200
    response = client.get("/api/release/current", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["release"]["version"] == "Sprint20-v1.2"


def test_release_center_does_not_leak_sensitive_fields(client, owner_headers):
    response = client.get("/api/release/current", headers=owner_headers)
    assert response.status_code == 200
    payload = str(response.json()).lower()
    for word in ["password_hash", "token", "secret", "api key", "authorization", "bearer"]:
        assert word not in payload


def test_release_center_migration_head_and_table():
    assert "release_versions" in set(ReleaseVersion.metadata.tables)
    script = ScriptDirectory.from_config(Config(str(Path("alembic.ini"))))
    assert script.get_heads() == ["0017_sprint20_5_release_center"]
