from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.auth import hash_password
from backend.database import Base, get_db
from backend.deploy_models import DeployRecord
from backend.main import app
from backend.models import AiEmployee, AiTask, Company, Permission, Role, Store, Tenant, User, UserStoreMembership


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_ADMIN_URL_ENV = "V2_ALPHA_POSTGRES_ADMIN_URL"
ALPHA_FLAGS = {
    "AGENT_RUNTIME_ENABLED": "true",
    "ALPHA_WORKFLOW_ENABLED": "true",
    "ALPHA_WORKFLOW_DASHBOARD_ENABLED": "true",
    "PUBLIC_RESEARCH_ENABLED": "true",
    "PUBLIC_SEARCH_ENABLED": "true",
    "PUBLIC_SEARCH_PROVIDER": "mock",
    "KNOWLEDGE_CENTER_ENABLED": "true",
    "KNOWLEDGE_SUBMISSION_ENABLED": "true",
    "KNOWLEDGE_LOCAL_SEARCH_ENABLED": "true",
    "SKILLS_ENGINE_ENABLED": "true",
    "SKILL_INSTALLATION_ENABLED": "true",
    "SKILL_INVOCATION_ENABLED": "true",
}


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.lists = {}
        self.hashes = {}
        self.sorted_sets = {}

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
        self.hashes.pop(key, None)

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update({name: str(value) for name, value in mapping.items()})

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def zadd(self, key, mapping):
        self.sorted_sets.setdefault(key, {}).update(mapping)

    def zrem(self, key, value):
        self.sorted_sets.get(key, {}).pop(value, None)

    def zrangebyscore(self, key, minimum, maximum):
        minimum = float("-inf") if minimum == "-inf" else float(minimum)
        maximum = float("inf") if maximum == "+inf" else float(maximum)
        return [value for value, score in self.sorted_sets.get(key, {}).items() if minimum <= score <= maximum]

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

    def lrem(self, key, _count, value):
        values = self.lists.get(key, [])
        if value not in values:
            return 0
        values.remove(value)
        return 1

    def eval(self, script, _key_count, *args):
        from backend import queue

        if script == queue._CLAIM_SCRIPT:
            (
                ready, processing, deadlines, prefix, worker_id, now, deadline,
                _ttl, score, generation_prefix, _generation_ttl,
            ) = args
            values = self.lists.get(ready, [])
            if not values:
                return None
            task = json.loads(values.pop(0))
            generation_key = generation_prefix + task["task_id"]
            task["claim_generation"] = max(
                int(task.get("claim_generation", 0)), int(self.values.get(generation_key, 0))
            ) + 1
            self.values[generation_key] = str(task["claim_generation"])
            raw = json.dumps(task, separators=(",", ":"))
            lease_id = f"{task['task_id']}:{task['claim_generation']}"
            metadata = prefix + lease_id
            payload = task.get("payload") or {}
            self.lists.setdefault(processing, []).append(raw)
            self.hashes[metadata] = {
                "task_id": task["task_id"],
                "tenant_id": str(payload.get("tenant_id") or ""),
                "company_id": str(payload.get("company_id") or ""),
                "store_id": str(payload.get("store_id") or ""),
                "sync_window_started_at": str(payload.get("sync_window_started_at") or ""),
                "claimed_by": worker_id,
                "claim_generation": str(task["claim_generation"]),
                "started_at": now,
                "heartbeat_at": now,
                "visibility_deadline": deadline,
            }
            self.zadd(deadlines, {lease_id: float(score)})
            return raw

        if script == queue._HEARTBEAT_SCRIPT:
            metadata, deadlines, worker_id, heartbeat, deadline, _ttl, lease_id, score = args
            if self.hashes.get(metadata, {}).get("claimed_by") != worker_id:
                return 0
            self.hashes[metadata].update({"heartbeat_at": heartbeat, "visibility_deadline": deadline})
            self.zadd(deadlines, {lease_id: float(score)})
            return 1

        if script in {queue._ACK_SCRIPT, queue._NACK_SCRIPT, queue._RETRY_CLAIMED_SCRIPT}:
            processing, metadata, deadlines, *rest = args
            if script == queue._RETRY_CLAIMED_SCRIPT:
                ready, raw, worker_id, task_id, generation, replacement = rest
            elif script == queue._NACK_SCRIPT:
                ready, raw, worker_id, task_id, generation = rest
                replacement = raw
            else:
                raw, worker_id, task_id, generation = rest
                ready = replacement = None
            record = self.hashes.get(metadata, {})
            if record.get("claimed_by") != worker_id or record.get("task_id") != task_id:
                return 0
            if record.get("claim_generation") != generation or not self.lrem(processing, 1, raw):
                return 0
            if ready is not None:
                self.rpush(ready, replacement)
            self.delete(metadata)
            self.zrem(deadlines, f"{task_id}:{generation}")
            return 1

        if script == queue._DISCARD_PROCESSING_SCRIPT:
            processing, metadata, deadlines, raw, lease_id = args
            if not self.lrem(processing, 1, raw):
                return 0
            self.delete(metadata)
            self.zrem(deadlines, lease_id)
            return 1

        raise AssertionError("FakeRedis received an unsupported Lua script")

    def blpop(self, key, timeout=0):
        keys = key if isinstance(key, list) else [key]
        for item_key in keys:
            values = self.lists.get(item_key, [])
            if values:
                return item_key, values.pop(0)
        return None

    def ping(self):
        return True


def _alembic(database_url: str, *args: str):
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    for key in tuple(env):
        assert "DRIFT" not in key or "SKIP" not in key, f"禁止Drift跳过变量：{key}"
    env.pop("ALEMBIC_SKIP_SQLITE_DRIFT", None)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


@pytest.fixture(scope="module")
def postgres_database_factory():
    raw_admin_url = os.getenv(POSTGRES_ADMIN_URL_ENV)
    assert raw_admin_url, f"真实PostgreSQL专项要求设置 {POSTGRES_ADMIN_URL_ENV}"
    admin_url = make_url(raw_admin_url)
    assert admin_url.get_backend_name() == "postgresql", "Migration专项禁止SQLite或其它数据库"
    admin_dsn = admin_url.set(drivername="postgresql").render_as_string(hide_password=False)
    created: list[str] = []

    def create_database(label: str) -> str:
        name = f"alpha_s11_{label}_{uuid.uuid4().hex[:12]}"
        connection = psycopg2.connect(admin_dsn)
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        finally:
            connection.close()
        created.append(name)
        return admin_url.set(database=name).render_as_string(hide_password=False)

    yield create_database

    connection = psycopg2.connect(admin_dsn)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            for name in created:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                    (name,),
                )
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
    finally:
        connection.close()


@pytest.fixture()
def alpha_enabled(monkeypatch):
    from backend.config import get_settings

    for key, value in ALPHA_FLAGS.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def postgres_alpha_runtime(postgres_database_factory, alpha_enabled, monkeypatch):
    """Run the HTTP workflow against an isolated migrated PostgreSQL database."""
    database_url = postgres_database_factory("alpha_api")
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    previous_overrides = app.dependency_overrides.copy()

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    fake_redis = FakeRedis()
    for target in (
        "backend.database.get_redis",
        "backend.auth.get_redis",
        "backend.queue.get_redis",
        "backend.task_queue.get_redis",
        "backend.brain_execution.queue.get_redis",
        "backend.execution_engine.get_redis",
        "backend.command_center.orchestration_view.get_redis",
        "backend.routers.metrics.get_redis",
        "backend.routers.ai_employees.get_redis",
        "backend.routers.deploy_center.get_redis",
        "backend.main.get_redis",
    ):
        monkeypatch.setattr(target, lambda: fake_redis)
    seed_database(session_factory)
    client = TestClient(app)
    login = client.post("/api/login", json={"username": "boss", "password": "password"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    yield client, headers, session_factory
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous_overrides)
    engine.dispose()


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
        tenant = db.query(Tenant).filter(Tenant.tenant_code == "internal-test").one_or_none()
        if not tenant:
            tenant = Tenant(tenant_code="internal-test", tenant_name="Internal Test", active=True)
            db.add(tenant)
            db.flush()
        company = db.query(Company).filter(
            Company.tenant_id == tenant.id,
            Company.company_code == "internal-test",
        ).one_or_none()
        if not company:
            company = Company(
                tenant_id=tenant.id,
                company_code="internal-test",
                company_name="Internal Test",
                active=True,
            )
            db.add(company)
            db.flush()
        permissions = [
            Permission(code="menu.dashboard", name="Dashboard"),
            Permission(code="menu.jd_data", name="JD Data"),
            Permission(code="menu.import", name="Import"),
            Permission(code="menu.stores", name="Stores"),
            Permission(code="data.metrics.write", name="Metrics Write"),
            Permission(code="jd_workbench.ingest", name="JD Workbench Ingest"),
            Permission(code="stores.manage", name="Stores Manage"),
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
            Permission(code="menu.computer_executor", name="Computer Executor Menu"),
            Permission(code="menu.device_center", name="Device Center Menu"),
            Permission(code="skills.read", name="Skills Read"),
            Permission(code="skills.manage", name="Skills Manage"),
            Permission(code="skills.install", name="Skills Install"),
            Permission(code="skills.invoke", name="Skills Invoke"),
            Permission(code="skills.audit", name="Skills Audit"),
            Permission(code="computer_executor.read", name="Computer Executor Read"),
            Permission(code="computer_executor.manage", name="Computer Executor Manage"),
            Permission(code="device_center.read", name="Device Center Read"),
            Permission(code="device_center.manage", name="Device Center Manage"),
            Permission(code="device_center.audit", name="Device Center Audit"),
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
            and p.code != "jd_workbench.ingest"
            and not p.code.startswith("ai_employees.")
            and not p.code.startswith("skills.")
            and not p.code.startswith("computer_executor.")
            and not p.code.startswith("device_center.")
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
                    tenant_id=tenant.id,
                    company_id=company.id,
                    active=True,
                ),
                User(
                    username="admin",
                    password_hash=hash_password("password"),
                    role="admin",
                    display_name="Admin",
                    tenant_id=tenant.id,
                    company_id=company.id,
                    active=True,
                ),
                User(
                    username="boss",
                    password_hash=hash_password("password"),
                    role="boss",
                    display_name="Boss",
                    tenant_id=tenant.id,
                    company_id=company.id,
                    active=True,
                ),
                User(
                    username="operator",
                    password_hash=hash_password("password"),
                    role="operator",
                    display_name="Operator",
                    tenant_id=tenant.id,
                    company_id=company.id,
                    active=True,
                ),
                User(
                    username="customer_service",
                    password_hash=hash_password("password"),
                    role="customer_service",
                    display_name="Customer Service",
                    tenant_id=tenant.id,
                    company_id=company.id,
                    active=True,
                ),
                User(
                    username="designer",
                    password_hash=hash_password("password"),
                    role="designer",
                    display_name="Designer",
                    tenant_id=tenant.id,
                    company_id=company.id,
                    active=True,
                ),
                User(
                    username="editor",
                    password_hash=hash_password("password"),
                    role="editor",
                    display_name="Editor",
                    tenant_id=tenant.id,
                    company_id=company.id,
                    active=True,
                ),
                User(
                    username="viewer",
                    password_hash=hash_password("password"),
                    role="viewer",
                    display_name="Viewer",
                    tenant_id=tenant.id,
                    company_id=company.id,
                    active=True,
                ),
            ]
        )
        db.flush()
        store = Store(
            platform="jd",
            store_code="JD01",
            store_name="JD Store 01",
            tenant_id=tenant.id,
            company_id=company.id,
            active=True,
        )
        db.add(store)
        db.flush()
        permitted_users = db.query(User).filter(User.username.in_(["owner", "admin", "boss", "operator"])).all()
        db.add_all(
            [
                UserStoreMembership(
                    user_id=user.id,
                    store_id=store.id,
                    can_read=True,
                    can_write=True,
                    active=True,
                )
                for user in permitted_users
            ]
        )
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
