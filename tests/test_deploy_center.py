from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.deploy_models import DeployHealthCheck


def auth_headers(client, username: str):
    response = client.post("/api/login", json={"username": username, "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_deploy_center_requires_login(client):
    response = client.get("/api/deploy-center/status")
    assert response.status_code == 401


def test_deploy_center_page_is_whitelisted(client):
    response = client.get("/deploy-center.html")
    assert response.status_code == 200


def test_deploy_center_rejects_non_privileged_roles(client):
    for username in ["operator", "customer_service", "designer", "editor", "viewer"]:
        response = client.get("/api/deploy-center/status", headers=auth_headers(client, username))
        assert response.status_code == 403


def test_deploy_center_allows_boss_owner_admin(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        response = client.get("/api/deploy-center/status", headers=headers)
        assert response.status_code == 200


def test_deploy_center_status(client, owner_headers):
    response = client.get("/api/deploy-center/status", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["service_status"] == "running"
    assert data["database_status"] == "healthy"
    assert data["last_deploy_status"] == "initialized"


def test_deploy_center_version(client, owner_headers):
    response = client.get("/api/deploy-center/version", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert {"branch", "commit_hash", "commit_short", "deploy_version", "alembic_version", "build_time"} <= set(data)


def test_deploy_center_migration(client, owner_headers):
    response = client.get("/api/deploy-center/migration", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["expected_version"] == "0011_orchestrator_task_links"
    assert data["status"] in {"up_to_date", "outdated"}


def test_deploy_center_health(client, owner_headers):
    response = client.get("/api/deploy-center/health", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["backend"]["status"] == "running"
    assert data["database"]["status"] == "healthy"
    assert data["redis"]["status"] == "healthy"
    assert data["nginx"]["status"] == "unknown"


def test_deploy_center_health_check_writes_rows(client, owner_headers, test_db):
    response = client.post("/api/deploy-center/health/check", headers=owner_headers)
    assert response.status_code == 200

    db = test_db()
    try:
        rows = db.query(DeployHealthCheck).all()
        assert len(rows) == 5
        assert {row.check_type for row in rows} == {"backend", "database", "redis", "migration", "nginx"}
    finally:
        db.close()


def test_deploy_center_records(client, owner_headers):
    response = client.get("/api/deploy-center/records", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert data[0]["deploy_version"] == "Sprint 3 MVP"
    assert data[0]["status"] == "initialized"


def test_alembic_has_single_head():
    config = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert heads == ["0011_orchestrator_task_links"]
