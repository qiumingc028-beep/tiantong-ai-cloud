from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.auth import hash_password
from backend.database import Base, get_db
from backend.main import app
from backend.models import AiTask, Permission, Role, Store, User


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.lists = {}

    def setex(self, key, ttl, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)

    def scan_iter(self, pattern):
        prefix = pattern.removesuffix("*")
        return iter([key for key in self.values if key.startswith(prefix)])

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start : end + 1]

    def lrange(self, key, start, end):
        return self.lists.get(key, [])[start : end + 1]

    def blpop(self, key, timeout=0):
        values = self.lists.get(key, [])
        if not values:
            return None
        return key, values.pop(0)

    def ping(self):
        return True


@pytest.fixture()
def test_db(monkeypatch):
    previous_overrides = app.dependency_overrides.copy()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db

    fake_redis = FakeRedis()
    monkeypatch.setattr("backend.database.get_redis", lambda: fake_redis)
    monkeypatch.setattr("backend.auth.get_redis", lambda: fake_redis)
    monkeypatch.setattr("backend.queue.get_redis", lambda: fake_redis)
    monkeypatch.setattr("backend.routers.metrics.get_redis", lambda: fake_redis)
    monkeypatch.setattr("backend.routers.ai_employees.get_redis", lambda: fake_redis)
    monkeypatch.setattr("backend.main.get_redis", lambda: fake_redis)
    monkeypatch.setattr("backend.main.engine", engine)
    monkeypatch.setattr("backend.main.ensure_tables", lambda: None)
    monkeypatch.setattr("backend.main.SessionLocal", TestingSessionLocal)

    seed_database(TestingSessionLocal)
    yield TestingSessionLocal

    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous_overrides)
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(test_db):
    return TestClient(app)


@pytest.fixture()
def owner_headers(client):
    return login_headers(client, "owner", "password")


@pytest.fixture()
def viewer_headers(client):
    return login_headers(client, "viewer", "password")


def login_headers(client: TestClient, username: str, password: str):
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 200
    token = response.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def seed_database(session_factory):
    db = session_factory()
    try:
        permissions = [
            Permission(code="menu.dashboard", name="Dashboard"),
            Permission(code="menu.jd_data", name="JD Data"),
            Permission(code="menu.stores", name="Stores"),
            Permission(code="data.metrics.write", name="Metrics Write"),
            Permission(code="ai.tasks.manage", name="AI Tasks Manage"),
            Permission(code="ai.tasks.read", name="AI Tasks Read"),
        ]
        owner_role = Role(code="owner", name="Owner", permissions=permissions)
        viewer_role = Role(code="viewer", name="Viewer", permissions=[])
        db.add_all([owner_role, viewer_role])
        db.add_all(
            [
                User(
                    username="owner",
                    password_hash=hash_password("password"),
                    role="owner",
                    display_name="Owner",
                    active=True,
                ),
                User(
                    username="viewer",
                    password_hash=hash_password("password"),
                    role="viewer",
                    display_name="Viewer",
                    active=True,
                ),
            ]
        )
        db.add(Store(platform="jd", store_code="JD01", store_name="JD Store 01", active=True))
        db.add(
            AiTask(
                ai_employee_code="ai_operator",
                ai_employee_name="AI Operator",
                status="idle",
                today_task="Check store metrics",
                execution_log="",
            )
        )
        db.commit()
    finally:
        db.close()
