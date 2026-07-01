from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.auth import hash_password
from backend.database import Base, get_db
from backend.main import app
from backend.models import AiTask, Permission, Role, Store, User


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def override_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_db


def setup_module():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    permissions = [
        Permission(code="menu.dashboard", name="老板驾驶舱"),
        Permission(code="menu.jd_data", name="京东数据中心"),
        Permission(code="data.metrics.write", name="写入经营数据"),
        Permission(code="stores.manage", name="管理店铺"),
        Permission(code="ai.tasks.manage", name="管理AI员工任务"),
        Permission(code="ai.tasks.read", name="读取AI员工任务"),
    ]
    role = Role(code="owner", name="Owner", permissions=permissions)
    db.add(role)
    db.add(User(username="owner", password_hash=hash_password("password"), role="owner", display_name="老板", active=True))
    db.add(Store(platform="jd", store_code="JD01", store_name="京东店铺01", active=True))
    db.add(AiTask(ai_employee_code="ai_operator", ai_employee_name="AI运营", status="idle", today_task="检查数据", execution_log=""))
    db.commit()
    db.close()


def test_login_and_core_apis(monkeypatch):
    fake_session = {}

    class FakeRedis:
        def setex(self, key, ttl, value):
            fake_session[key] = value
        def get(self, key):
            return fake_session.get(key)
        def delete(self, key):
            fake_session.pop(key, None)
        def scan_iter(self, pattern):
            return iter([k for k in fake_session if k.startswith("session:")])
        def rpush(self, key, value):
            fake_session.setdefault(key, [])
            fake_session[key].append(value)
        def lpush(self, key, value):
            fake_session.setdefault(key, [])
            fake_session[key].insert(0, value)
        def ltrim(self, key, start, end):
            fake_session[key] = fake_session.get(key, [])[start:end + 1]
        def lrange(self, key, start, end):
            return fake_session.get(key, [])[start:end + 1]
        def blpop(self, key, timeout=0):
            values = fake_session.get(key, [])
            if not values:
                return None
            return key, values.pop(0)
        def ping(self):
            return True

    monkeypatch.setattr("backend.auth.get_redis", lambda: FakeRedis())
    monkeypatch.setattr("backend.queue.get_redis", lambda: FakeRedis())
    monkeypatch.setattr("backend.routers.metrics.get_redis", lambda: FakeRedis())
    monkeypatch.setattr("backend.routers.ai_employees.get_redis", lambda: FakeRedis())
    monkeypatch.setattr("backend.main.ensure_tables", lambda: None)
    monkeypatch.setattr("backend.main.SessionLocal", TestingSessionLocal)

    client = TestClient(app)
    login = client.post("/api/login", json={"username": "owner", "password": "password"})
    assert login.status_code == 200
    assert login.json()["token"]

    assert client.get("/api/stores").status_code == 200
    assert client.get("/api/jd/dashboard").status_code == 200
    assert client.get("/api/metrics/today").status_code == 200
    assert client.get("/api/ai/tasks").status_code == 200
    assert client.get("/api/jd/accounts").status_code == 200

    metric = client.post(
        "/api/metrics/manual",
        json={
            "store_id": 1,
            "metric_date": date.today().isoformat(),
            "sales_amount": 100,
            "profit_amount": 20,
            "ad_spend": 10,
            "roi": 10,
            "orders_count": 2,
            "visitors_count": 30,
            "refunds_count": 0,
            "after_sales_count": 0,
        },
    )
    assert metric.status_code == 200

    run = client.post("/api/ai/tasks/1/run")
    assert run.status_code == 200

    account = client.post(
        "/api/jd/accounts",
        json={"store_id": 1, "account_type": "jd_smart", "account_name": "商智账号"},
    )
    assert account.status_code == 200

    queued = client.post("/api/jd/sync/store/1")
    assert queued.status_code == 200
    assert queued.json()["ok"] is True

    analysis = client.post("/api/ai/store-manager/analyze")
    assert analysis.status_code == 200

    ai_queue = client.post("/api/ai/store-manager/enqueue")
    assert ai_queue.status_code == 200
