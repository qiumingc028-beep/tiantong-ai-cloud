import asyncio
import contextvars
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date
from io import BytesIO
from threading import Barrier, BrokenBarrierError, Lock
from time import monotonic
from types import MappingProxyType

import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from backend.database import Base, get_db
from backend.main import app
from backend.models import Company, EmployeeLog, JdDailyMetric, MetricDaily, Permission, Role, Store, Tenant, User, UserStoreMembership


def test_rbac_guard_is_served_to_real_browser(client):
    response = client.get("/rbac-navigation.js")

    assert response.status_code == 200
    assert "TiantongRbac" in response.text


def test_owner_menu_returns_all_authorized_uat_pages(client, owner_headers, test_db):
    with test_db() as db:
        owner_role = db.query(Role).filter(Role.code == "owner").one()
        for code, name in (
            ("menu.ai_employees", "AI Employees"),
            ("menu.settings", "Settings"),
            ("menu.computer_executor", "Computer Executor"),
        ):
            permission = db.query(Permission).filter(Permission.code == code).one_or_none()
            if permission is None:
                permission = Permission(code=code, name=name)
                db.add(permission)
            if permission not in owner_role.permissions:
                owner_role.permissions.append(permission)
        db.commit()

    response = client.get("/api/me", headers=owner_headers)

    assert response.status_code == 200
    assert [(item["label"], item["href"]) for item in response.json()["menus"]] == [
        ("老板驾驶舱", "/"),
        ("店铺与数据", "/import.html"),
        ("经营中心", "/jd-dashboard.html"),
        ("AI员工名册", "/ai-employees.html"),
        ("电脑执行中心", "/computer-execution-center.html"),
        ("系统设置", "/settings.html"),
    ]
    permissions = [item["permission"] for item in response.json()["menus"]]
    assert len(permissions) == len(set(permissions))


def test_restricted_user_menu_keeps_unknown_permissions_fail_closed(client, test_db):
    with test_db() as db:
        viewer_role = db.query(Role).filter(Role.code == "viewer").one()
        unknown = Permission(code="menu.r178_unknown", name="R178 Unknown")
        viewer_role.permissions.append(unknown)
        db.add(unknown)
        db.commit()

    login = client.post("/api/login", json={"username": "viewer", "password": "password"})
    assert login.status_code == 200
    response = client.get("/api/me", headers={"Authorization": f"Bearer {login.json()['token']}"})

    assert response.status_code == 200
    assert response.json()["menus"] == []


def test_csv_import_reports_errors_blocks_duplicates_and_persists(client, owner_headers):
    csv_data = (
        "store_code,metric_date,sales_amount,profit_amount,ad_spend,roi,"
        "orders_count,visitors_count,favorites_count,cart_add_count,conversion_rate\n"
        "JD01,2026-08-08,500,120,50,10,5,80,8,6,0.0625\n"
        "JD01,2026-08-09,700,180,70,10,7,100,10,9,0.07\n"
        "JD01,2026-08-10,not-a-number,20,10,2,1,10,1,1,0.1\n"
    ).encode("utf-8")

    first = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        data={"store_id": "1"},
        files={"file": ("internal-test.csv", csv_data, "text/csv")},
    )
    assert first.status_code == 200
    assert {key: first.json()[key] for key in (
        "ok", "status", "total_rows", "success_rows", "failed_rows", "errors", "duplicate"
    )} == {
        "ok": True,
        "status": "partial_success",
        "total_rows": 3,
        "success_rows": 2,
        "failed_rows": 1,
        "errors": [{"row": 4, "reason": "销售额格式错误"}],
        "duplicate": False,
    }

    duplicate = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        data={"store_id": "1"},
        files={"file": ("internal-test.csv", csv_data, "text/csv")},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["success_rows"] == 2

    records = client.get("/api/metrics/import-records", headers=owner_headers)
    assert records.status_code == 200
    assert len(records.json()["records"]) == 1
    assert records.json()["records"][0]["status"] == "partial_success"

    business = client.get(
        "/api/business-center/metrics?store_id=1&date_from=2026-08-08&date_to=2026-08-09",
        headers=owner_headers,
    )
    assert business.status_code == 200
    assert business.json()["total"] == 2
    assert business.json()["summary"] == {
        "sales_amount": 1200.0,
        "orders_count": 12,
        "ad_spend": 120.0,
        "visitors_count": 180,
        "favorites_count": 18,
        "cart_add_count": 15,
    }

    dashboard = client.get(
        "/api/owner/dashboard?store_id=1&date_from=2026-08-08&date_to=2026-08-09",
        headers=owner_headers,
    )
    assert dashboard.status_code == 200
    assert dashboard.json()["today_sales"] == business.json()["summary"]["sales_amount"]
    assert dashboard.json()["orders"] == business.json()["summary"]["orders_count"]
    assert dashboard.json()["ad_spend"] == business.json()["summary"]["ad_spend"]


def test_xlsx_import_uses_selected_store(client, owner_headers):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["日期", "今日成交", "订单数", "广告花费", "访客数", "收藏", "加购", "转化率"])
    sheet.append(["2026-08-09", 880, 8, 88, 120, 12, 9, 0.0667])
    content = BytesIO()
    workbook.save(content)

    response = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        data={"store_id": "1"},
        files={"file": ("internal-test.xlsx", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["total_rows"] == response.json()["success_rows"] == 1
    assert response.json()["failed_rows"] == 0


def test_business_center_rejects_users_without_server_permission(client, viewer_headers):
    response = client.get("/api/business-center/metrics", headers=viewer_headers)

    assert response.status_code == 403


def test_import_rejects_unrecognized_schema_without_writing_metrics(client, owner_headers, test_db):
    response = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        data={"store_id": "1"},
        files={"file": ("wrong.csv", b"foo\nbar\n", "text/csv")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "缺少必要字段：日期、销售额、订单量、广告消耗"
    with test_db() as db:
        assert db.query(MetricDaily).count() == 0
        assert db.query(JdDailyMetric).count() == 0


def test_concurrent_duplicate_import_is_claimed_once(postgres_alpha_runtime):
    fixture_client, _fixture_headers, session_factory = postgres_alpha_runtime
    write_set_table_manifest = frozenset({"metrics_daily", "jd_daily_metrics", "employee_logs"})
    csv_data = (
        "metric_date,sales_amount,ad_spend,orders_count\n"
        "2026-08-11,100,10,1\n"
    ).encode("utf-8")
    client_counts = {"created": 1, "closed": 0}
    client_count_lock = Lock()

    def close_client(client):
        client.close()
        with client_count_lock:
            client_counts["closed"] += 1

    try:
        login = fixture_client.post("/api/login", json={"username": "owner", "password": "password"})
        assert login.status_code == 200
        owner_headers = MappingProxyType({"Authorization": f"Bearer {login.json()['token']}"})
        credential = login.json()["token"]
    finally:
        close_client(fixture_client)

    with session_factory() as db:
        owner = db.query(User).filter(User.username == "owner").one()
        owner_store = (
            db.query(Store)
            .join(UserStoreMembership, UserStoreMembership.store_id == Store.id)
            .filter(
                UserStoreMembership.user_id == owner.id,
                UserStoreMembership.active.is_(True),
                UserStoreMembership.can_write.is_(True),
            )
            .one()
        )
        foreign_tenant = Tenant(
            tenant_code="r244-foreign-tenant",
            tenant_name="R244 Foreign Tenant",
            active=True,
        )
        db.add(foreign_tenant)
        db.flush()
        foreign_company = Company(
            tenant_id=foreign_tenant.id,
            company_code="r244-foreign-company",
            company_name="R244 Foreign Company",
            active=True,
        )
        db.add(foreign_company)
        db.flush()
        foreign_store = Store(
            platform="jd",
            store_code="R244-FOREIGN",
            store_name="R244 Foreign Store",
            tenant_id=foreign_tenant.id,
            company_id=foreign_company.id,
            active=True,
        )
        db.add(foreign_store)
        db.flush()
        foreign_metric = MetricDaily(
            store_id=foreign_store.id,
            metric_date=date(2026, 8, 11),
            sales_amount=999999,
            source="r244-foreign",
        )
        foreign_jd_metric = JdDailyMetric(
            store_id=foreign_store.id,
            metric_date=date(2026, 8, 11),
            gmv=999999,
            source="r244-foreign",
        )
        foreign_audit = EmployeeLog(
            user_id=owner.id,
            store_id=foreign_store.id,
            action="metrics_import:r244-foreign-sentinel",
            detail='{"sentinel":"r244-foreign"}',
        )
        db.add_all([foreign_metric, foreign_jd_metric, foreign_audit])
        db.commit()
        owner_id = owner.id
        owner_store_id = owner_store.id
        foreign_store_id = foreign_store.id
        missing_store_id = max(owner_store_id, foreign_store_id) + 1_000_000
        assert db.get(Store, missing_store_id) is None

    def database_snapshot():
        with session_factory() as db:
            return {
                table.name: tuple(
                    tuple(row._mapping[column] for column in table.columns)
                    for row in db.execute(
                        select(*table.columns).order_by(*table.primary_key.columns)
                    )
                )
                for table in sorted(Base.metadata.tables.values(), key=lambda item: item.name)
            }

    baseline = database_snapshot()
    request_worker = contextvars.ContextVar("r244_request_worker", default=None)
    dml_phase = contextvars.ContextVar("r245_dml_phase", default=None)
    observations = {"worker-1": {}, "worker-2": {}}
    observation_lock = Lock()
    concurrency_counts = {"barrier_timeout": 0, "future_timeout": 0}
    sql_counts = {"foreign": 0, "missing": 0, "get": 0}
    dml_counts = {"foreign": 0, "missing": 0, "get": 0}
    engine = session_factory.kw["bind"]
    previous_override = app.dependency_overrides[get_db]

    def update(worker, **values):
        with observation_lock:
            observations[worker].update(values)

    def isolated_db():
        db = session_factory()
        db.execute(text("SET LOCAL statement_timeout = '10s'"))
        worker = request_worker.get()
        if worker:
            update(worker, session_identity=id(db))
        try:
            yield db
        finally:
            db.close()

    class CorrelatedApp:
        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await self.inner(scope, receive, send)
            headers = {key.lower(): value for key, value in scope.get("headers", [])}
            worker = headers.get(b"x-r244-diagnostic-id", b"").decode("ascii", "strict")
            phase = headers.get(b"x-r245-dml-phase", b"").decode("ascii", "strict")
            worker_token = request_worker.set(worker) if worker in observations else None
            phase_token = dml_phase.set(phase) if phase in dml_counts else None
            if worker_token is not None:
                update(
                    worker,
                    request_start=monotonic(),
                    auth_path="bearer",
                    authorization_present=headers.get(b"authorization", b"").startswith(b"Bearer "),
                    cookie_present=b"cookie" in headers,
                )
            try:
                async with asyncio.timeout(15):
                    return await self.inner(scope, receive, send)
            finally:
                if worker_token is not None:
                    update(worker, request_end=monotonic())
                    request_worker.reset(worker_token)
                if phase_token is not None:
                    dml_phase.reset(phase_token)

    app.dependency_overrides[get_db] = isolated_db
    request_app = CorrelatedApp(app)
    barrier = Barrier(2, timeout=10)

    def new_client():
        client = TestClient(request_app)
        with client_count_lock:
            client_counts["created"] += 1
        return client

    def upload(worker):
        worker_client = None
        try:
            worker_client = new_client()
            update(worker, cookie_count_before=len(worker_client.cookies), client_closed=False)
            assert len(worker_client.cookies) == 0
            headers = dict(owner_headers)
            headers["X-R244-Diagnostic-ID"] = worker
            try:
                barrier.wait(timeout=10)
            except BrokenBarrierError:
                with observation_lock:
                    concurrency_counts["barrier_timeout"] += 1
                raise
            response = worker_client.post(
                "/api/metrics/import",
                headers=headers,
                data={"store_id": str(owner_store_id)},
                files={"file": ("same.csv", csv_data, "text/csv")},
            )
            update(
                worker,
                cookie_count_after=len(worker_client.cookies),
                status=response.status_code,
                duplicate=response.json().get("duplicate"),
            )
            return response
        except BaseException:
            barrier.abort()
            raise
        finally:
            if worker_client is not None:
                close_client(worker_client)
                update(worker, client_closed=True)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(upload, worker) for worker in observations]
            done, not_done = wait(futures, timeout=30)
            if not_done:
                concurrency_counts["future_timeout"] += len(not_done)
                barrier.abort()
                for future in not_done:
                    future.cancel()
                raise AssertionError("concurrent import futures exceeded 30 seconds")
            responses = [future.result() for future in futures]

        assert [response.status_code for response in responses] == [200, 200]
        assert sorted(response.json()["duplicate"] for response in responses) == [False, True]
        assert max(row["request_start"] for row in observations.values()) < min(
            row["request_end"] for row in observations.values()
        )
        assert len({row["session_identity"] for row in observations.values()}) == 2
        assert all(
            row["authorization_present"]
            and row["auth_path"] == "bearer"
            and not row["cookie_present"]
            and row["cookie_count_before"] == row["cookie_count_after"] == 0
            and row["client_closed"]
            for row in observations.values()
        )
        assert concurrency_counts == {"barrier_timeout": 0, "future_timeout": 0}

        after_import = database_snapshot()
        assert {
            table for table in baseline if baseline[table] != after_import[table]
        } == write_set_table_manifest
        assert all(
            len(after_import[table]) == len(baseline[table]) + 1
            for table in write_set_table_manifest
        )
        assert all(
            row in after_import[table]
            for table in write_set_table_manifest
            for row in baseline[table]
        )

        with session_factory() as db:
            owner_metric = db.query(MetricDaily).filter(
                MetricDaily.store_id == owner_store_id,
                MetricDaily.metric_date == date(2026, 8, 11),
            ).one()
            owner_jd_metric = db.query(JdDailyMetric).filter(
                JdDailyMetric.store_id == owner_store_id,
                JdDailyMetric.metric_date == date(2026, 8, 11),
            ).one()
            owner_audit = db.query(EmployeeLog).filter(
                EmployeeLog.store_id == owner_store_id,
                EmployeeLog.action.like("metrics_import:%"),
            ).one()
            assert owner_metric.created_by == owner_id
            assert owner_jd_metric.store_id == owner_store_id
            assert owner_audit.user_id == owner_id
            assert credential not in (owner_audit.action + (owner_audit.detail or ""))

        def count_dml(_connection, _cursor, statement, _parameters, _context, _executemany):
            phase = dml_phase.get()
            if phase is None:
                return
            sql_counts[phase] += 1
            if statement.lstrip().partition(" ")[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
                dml_counts[phase] += 1

        forbidden_before = database_snapshot()
        listener_installed = False
        verification_client = new_client()
        try:
            assert len(verification_client.cookies) == 0
            event.listen(engine, "before_cursor_execute", count_dml)
            listener_installed = True

            foreign_headers = dict(owner_headers)
            foreign_headers["X-R245-DML-Phase"] = "foreign"
            foreign = verification_client.post(
                "/api/metrics/import",
                headers=foreign_headers,
                data={"store_id": str(foreign_store_id)},
                files={"file": ("same.csv", csv_data, "text/csv")},
            )
            missing_headers = dict(owner_headers)
            missing_headers["X-R245-DML-Phase"] = "missing"
            missing = verification_client.post(
                "/api/metrics/import",
                headers=missing_headers,
                data={"store_id": str(missing_store_id)},
                files={"file": ("same.csv", csv_data, "text/csv")},
            )

            get_headers = dict(owner_headers)
            get_headers["X-R245-DML-Phase"] = "get"
            records = verification_client.get("/api/metrics/import-records", headers=get_headers)
            business = verification_client.get(
                "/api/business-center/metrics?date_from=2026-08-11&date_to=2026-08-11",
                headers=get_headers,
            )
            owner_refresh = verification_client.get(
                f"/api/business-center/metrics?store_id={owner_store_id}"
                "&date_from=2026-08-11&date_to=2026-08-11",
                headers=get_headers,
            )

            assert foreign.status_code == missing.status_code == 403
            assert foreign.json() == missing.json() == {"detail": "没有店铺访问权限"}
            assert records.status_code == business.status_code == 200
            assert owner_refresh.status_code == 200
            assert len(records.json()["records"]) == 1
            assert business.json()["total"] == 1
            assert business.json()["summary"]["sales_amount"] == 100.0
            assert [row["store_id"] for row in business.json()["rows"]] == [owner_store_id]
            assert owner_refresh.json() == business.json()
            checked_responses = (*responses, foreign, missing, records, business, owner_refresh)
            assert all("r244-foreign" not in response.text.lower() for response in checked_responses)
            assert all(credential not in response.text for response in checked_responses)
            assert len(verification_client.cookies) == 0
        finally:
            try:
                if listener_installed:
                    event.remove(engine, "before_cursor_execute", count_dml)
            finally:
                close_client(verification_client)

        assert not event.contains(engine, "before_cursor_execute", count_dml)
        assert all(count > 0 for count in sql_counts.values())
        assert dml_counts == {"foreign": 0, "missing": 0, "get": 0}
        assert database_snapshot() == forbidden_before == after_import
    finally:
        app.dependency_overrides[get_db] = previous_override
        assert client_counts["created"] == client_counts["closed"]


def test_blank_required_values_do_not_overwrite_existing_metric(client, owner_headers):
    valid = b"metric_date,sales_amount,ad_spend,orders_count\n2026-08-12,321,32,3\n"
    blank = b"metric_date,sales_amount,ad_spend,orders_count\n2026-08-12,,,\n"
    for content in (valid, blank):
        response = client.post(
            "/api/metrics/import",
            headers=owner_headers,
            data={"store_id": "1"},
            files={"file": ("metrics.csv", content, "text/csv")},
        )
        assert response.status_code == 200

    assert response.json()["status"] == "failed"
    assert response.json()["errors"] == [{"row": 2, "reason": "销售额不能为空"}]
    business = client.get(
        "/api/business-center/metrics?store_id=1&date_from=2026-08-12&date_to=2026-08-12",
        headers=owner_headers,
    ).json()
    assert business["summary"]["sales_amount"] == 321.0
    assert business["summary"]["orders_count"] == 3
    assert business["summary"]["ad_spend"] == 32.0


def test_owner_cannot_write_store_without_explicit_membership(client, owner_headers, test_db):
    with test_db() as db:
        owner = db.query(User).filter(User.username == "owner").one()
        store = Store(platform="jd", store_code="UNAUTHORIZED", store_name="Unauthorized", tenant_id=owner.tenant_id, company_id=owner.company_id, active=True)
        db.add(store)
        db.commit()
        store_id = store.id

    response = client.post(
        "/api/metrics/manual",
        headers=owner_headers,
        json={
            "store_id": store_id,
            "metric_date": "2026-08-10",
            "sales_amount": 100,
        },
    )

    assert response.status_code == 403
    with test_db() as db:
        assert db.query(MetricDaily).filter(MetricDaily.store_id == store_id).count() == 0
