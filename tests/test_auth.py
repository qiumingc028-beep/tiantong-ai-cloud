import re
from pathlib import Path

from backend.auth import verify_password
from backend.models import User
from backend.seed import seed_defaults
from scripts.admin_login_recovery import list_admin_accounts, reset_admin_password


def test_backend_main_imports():
    import backend.main  # noqa: F401


def test_health_reports_server_database_and_redis(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert data["database"] is True
    assert data["redis"] is True


def test_ready_endpoint_exists(client):
    response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_login_success_sets_token_and_http_only_cookie(client):
    response = client.post("/api/login", json={"username": "owner", "password": "password"})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["token"]
    assert "password" not in data
    assert "password_hash" not in str(data)
    assert "httponly" in response.headers["set-cookie"].lower()


def test_seed_defaults_creates_login_ready_boss_account(client, test_db):
    db = test_db()
    try:
        db.query(User).filter(User.username == "boss").delete()
        db.commit()
        seed_defaults(db)
        boss = db.query(User).filter(User.username == "boss").one()
        assert boss.role == "boss"
        assert boss.active is True
        assert verify_password("Tiantong@2026", boss.password_hash)
    finally:
        db.close()

    response = client.post("/api/login", json={"username": "boss", "password": "Tiantong@2026"})

    assert response.status_code == 200
    data = response.json()
    assert data["user"]["username"] == "boss"
    assert data["user"]["role"] == "boss"
    assert data["user"]["role_code"] == "owner"
    assert "password" not in data
    assert "password_hash" not in str(data)


def test_login_rejects_wrong_password(client):
    response = client.post("/api/login", json={"username": "owner", "password": "wrong"})

    assert response.status_code == 401
    assert "token" not in response.text.lower()


def test_me_requires_login_and_does_not_leak_secrets(client, owner_headers):
    client.cookies.clear()
    unauthenticated = client.get("/api/me")
    authenticated = client.get("/api/me", headers=owner_headers)

    assert unauthenticated.status_code == 401
    assert authenticated.status_code == 200
    data = authenticated.json()
    assert "password" not in data
    assert "password_hash" not in data
    assert "token" not in data
    assert "cookie" not in data


def test_passwords_are_stored_as_hashes(test_db):
    db = test_db()
    try:
        user = db.query(User).filter(User.username == "owner").one()
        assert user.password_hash != "password"
        assert user.password_hash.startswith("pbkdf2_sha256$")
    finally:
        db.close()


def test_admin_login_recovery_lists_privileged_accounts_without_hashes(test_db):
    db = test_db()
    try:
        rows = list_admin_accounts(db)
        usernames = {row.username for row in rows}
        boss = next(row for row in rows if row.username == "boss")

        assert "owner" in usernames
        assert "boss" in usernames
        assert boss.role == "boss"
        assert boss.active is True
        assert boss.password_hash_algorithm == "pbkdf2_sha256"
        assert all("$" not in row.password_hash_algorithm for row in rows)
    finally:
        db.close()


def test_admin_login_recovery_resets_password_without_printing_or_returning_plaintext(client, test_db):
    db = test_db()
    try:
        summary = reset_admin_password(db, "boss", "NewBossPassword2026!", role="boss")
        assert summary.username == "boss"
        assert summary.role == "boss"
        assert summary.active is True
        assert summary.password_hash_algorithm == "pbkdf2_sha256"
        assert "NewBossPassword2026!" not in repr(summary)
    finally:
        db.close()

    old_login = client.post("/api/login", json={"username": "boss", "password": "Tiantong@2026"})
    assert old_login.status_code == 401

    new_login = client.post("/api/login", json={"username": "boss", "password": "NewBossPassword2026!"})
    assert new_login.status_code == 200
    assert new_login.json()["user"]["username"] == "boss"


def test_repository_does_not_contain_local_env_file():
    assert not Path(".env").exists()


def test_no_obvious_real_api_keys_committed():
    text_files = [
        path
        for path in Path(".").rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and "__pycache__" not in path.parts
        and path.suffix.lower() in {".py", ".md", ".sh", ".env", ".example", ".yml", ".yaml", ".ini"}
    ]
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in text_files
        if path.name != "test_auth.py"
    )

    assert not re.search(r"\bsk-[A-Za-z0-9_-]{20,}\b", combined)
    assert "AKIA" not in combined
    assert "x-acs-accesskey-id" not in combined.lower()
