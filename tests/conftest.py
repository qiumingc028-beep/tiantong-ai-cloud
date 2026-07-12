from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.auth import hash_password
from backend.database import Base, get_db
from backend.deploy_models import DeployRecord
from backend.main import app
from backend.models import AiEmployee, AiTask, Permission, Role, Store, User


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.lists = {}

    def setex(self, key, ttl, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

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

    def llen(self, key):
        return len(self.lists.get(key, []))

    def blpop(self, key, timeout=0):
        keys = key if isinstance(key, list) else [key]
        for item_key in keys:
            values = self.lists.get(item_key, [])
            if values:
                return item_key, values.pop(0)
        return None

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
    monkeypatch.setattr("backend.task_queue.get_redis", lambda: fake_redis)
    monkeypatch.setattr("backend.brain_execution.queue.get_redis", lambda: fake_redis)
    monkeypatch.setattr("backend.execution_engine.get_redis", lambda: fake_redis)
    monkeypatch.setattr("backend.workers.tian_shang_worker.get_redis", lambda: fake_redis)
    monkeypatch.setattr("backend.command_center.orchestration_view.get_redis", lambda: fake_redis)
    monkeypatch.setattr("backend.routers.metrics.get_redis", lambda: fake_redis)
    monkeypatch.setattr("backend.routers.ai_employees.get_redis", lambda: fake_redis)
    monkeypatch.setattr("backend.routers.deploy_center.get_redis", lambda: fake_redis)
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


@pytest.fixture()
def admin_headers(client):
    return login_headers(client, "admin", "password")


@pytest.fixture()
def boss_headers(client):
    return login_headers(client, "boss", "password")


@pytest.fixture()
def operator_headers(client):
    return login_headers(client, "operator", "password")


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
            Permission(code="task_center.read", name="Task Center Read"),
            Permission(code="task_center.manage", name="Task Center Manage"),
            Permission(code="task_center.execute", name="Task Center Execute"),
            Permission(code="task_center.review", name="Task Center Review"),
            Permission(code="task_center.audit", name="Task Center Audit"),
            Permission(code="ai_employees.read", name="AI Employees Read"),
            Permission(code="ai_employees.manage", name="AI Employees Manage"),
            Permission(code="menu.skills_center", name="Skills Center Menu"),
            Permission(code="skills.read", name="Skills Read"),
            Permission(code="skills.manage", name="Skills Manage"),
            Permission(code="skills.install", name="Skills Install"),
            Permission(code="skills.invoke", name="Skills Invoke"),
            Permission(code="skills.audit", name="Skills Audit"),
            Permission(code="deploy_center.read", name="Deploy Center Read"),
            Permission(code="deploy_center.manage", name="Deploy Center Manage"),
            Permission(code="orchestrator.read", name="Orchestrator Read"),
            Permission(code="orchestrator.analyze", name="Orchestrator Analyze"),
            Permission(code="orchestrator.confirm", name="Orchestrator Confirm"),
        ]
        owner_role = Role(code="owner", name="Owner", permissions=permissions)
        admin_role = Role(code="admin", name="Admin", permissions=permissions)
        operator_permissions = [
            p
            for p in permissions
            if not p.code.startswith("task_center.")
            and not p.code.startswith("ai_employees.")
            and not p.code.startswith("skills.")
            and not p.code.startswith("deploy_center.")
            and not p.code.startswith("orchestrator.")
        ]
        operator_role = Role(code="operator", name="Operator", permissions=operator_permissions)
        customer_service_role = Role(code="customer_service", name="Customer Service", permissions=[])
        designer_role = Role(code="designer", name="Designer", permissions=[])
        editor_role = Role(code="editor", name="Editor", permissions=[])
        viewer_role = Role(code="viewer", name="Viewer", permissions=[])
        db.add_all([owner_role, admin_role, operator_role, customer_service_role, designer_role, editor_role, viewer_role])
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
                    username="admin",
                    password_hash=hash_password("password"),
                    role="admin",
                    display_name="Admin",
                    active=True,
                ),
                User(
                    username="boss",
                    password_hash=hash_password("password"),
                    role="boss",
                    display_name="Boss",
                    active=True,
                ),
                User(
                    username="operator",
                    password_hash=hash_password("password"),
                    role="operator",
                    display_name="Operator",
                    active=True,
                ),
                User(
                    username="customer_service",
                    password_hash=hash_password("password"),
                    role="customer_service",
                    display_name="Customer Service",
                    active=True,
                ),
                User(
                    username="designer",
                    password_hash=hash_password("password"),
                    role="designer",
                    display_name="Designer",
                    active=True,
                ),
                User(
                    username="editor",
                    password_hash=hash_password("password"),
                    role="editor",
                    display_name="Editor",
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
            DeployRecord(
                deploy_version="Sprint 3 MVP",
                branch="main",
                operator="tiandun",
                status="initialized",
                note="Deploy Center MVP initialized",
            )
        )
        db.add(
            AiTask(
                ai_employee_code="ai_operator",
                ai_employee_name="AI Operator",
                status="idle",
                today_task="Check store metrics",
                execution_log="",
            )
        )
        db.add_all(
            [
                AiEmployee(
                    employee_code="tiantong",
                    employee_name="天统：AI总指挥",
                    legion="研发交付军团",
                    duty="统筹任务拆分、分配、汇总与推进",
                    status="active",
                    task_types='["command", "summary"]',
                    default_permissions='["task_center.manage"]',
                    is_legacy=False,
                    sort_order=10,
                ),
                AiEmployee(
                    employee_code="tianwang",
                    employee_name="天王：后端开发中心",
                    legion="研发交付军团",
                    duty="后端 API、数据库模型、迁移、权限和测试",
                    status="active",
                    task_types='["backend"]',
                    default_permissions='["task_center.execute"]',
                    is_legacy=False,
                    sort_order=30,
                ),
                AiEmployee(
                    employee_code="legacy_operator",
                    employee_name="Legacy Operator",
                    legion="legacy",
                    duty="Legacy placeholder",
                    status="active",
                    task_types='["legacy"]',
                    default_permissions="[]",
                    is_legacy=True,
                    sort_order=999,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()
