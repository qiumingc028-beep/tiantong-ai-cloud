import asyncio
import contextvars
from datetime import date
from io import BytesIO
from multiprocessing import get_context
import os
from queue import Empty
from threading import Lock
from time import monotonic
from types import MappingProxyType

import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from backend.database import Base, get_db
from backend.main import app
from backend.models import Company, EmployeeLog, JdDailyMetric, MetricDaily, Permission, Role, Store, Tenant, User, UserStoreMembership


def _r248_child_import(worker, owner_headers, store_id, csv_data, entry_barrier, lock_barrier, results):
    client = None
    listener_installed = False
    original_persist = None
    original_call_count = 0
    observation = {
        "kind": "final",
        "worker": worker,
        "process_pid": os.getpid(),
        "client_created": 0,
        "client_closed": 0,
        "forced_termination": 0,
    }
    try:
        from backend.database import engine
        from backend.main import app as child_app
        from backend.routers import metrics

        original_persist = metrics.persist_metric_import
        observation["import_lock_id"] = id(metrics.IMPORT_LOCK)

        def synchronize_store_lock(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.upper().split())
            if observation.get("store_for_update_reached") or "FROM STORES" not in normalized or "FOR UPDATE" not in normalized:
                return
            observation["store_for_update_reached"] = True
            lock_barrier.wait(timeout=15)

        def instrumented_persist(db, user, content, rows, selected_store_id):
            nonlocal original_call_count
            assert metrics.IMPORT_LOCK.locked()
            db.execute(text("SET LOCAL statement_timeout = '15s'"))
            pg_backend_pid, transaction_id, isolation = db.execute(
                text("SELECT pg_backend_pid(), txid_current(), current_setting('transaction_isolation')")
            ).one()
            observation.update(
                pg_backend_pid=pg_backend_pid,
                transaction_id=transaction_id,
                transaction_isolation=isolation,
                transaction_open=True,
            )
            results.put({
                "kind": "ready",
                "worker": worker,
                "process_pid": observation["process_pid"],
                "import_lock_id": observation["import_lock_id"],
                "pg_backend_pid": pg_backend_pid,
                "transaction_id": transaction_id,
            })
            entry_barrier.wait(timeout=20)
            observation["persist_start"] = monotonic()
            original_call_count += 1
            try:
                return original_persist(db, user, content, rows, selected_store_id)
            finally:
                observation["persist_end"] = monotonic()

        event.listen(engine, "before_cursor_execute", synchronize_store_lock)
        listener_installed = True
        metrics.persist_metric_import = instrumented_persist
        client = TestClient(child_app)
        observation["client_created"] = 1
        observation["cookie_count_before"] = len(client.cookies)
        assert observation["cookie_count_before"] == 0
        headers = dict(owner_headers)
        assert headers.get("Authorization", "").startswith("Bearer ")
        response = client.post(
            "/api/metrics/import",
            headers=headers,
            data={"store_id": str(store_id)},
            files={"file": ("same.csv", csv_data, "text/csv")},
        )
        observation.update(
            auth_path="bearer",
            authorization_present=True,
            cookie_count_after=len(client.cookies),
            status=response.status_code,
            response_json=response.json(),
            duplicate=response.json().get("duplicate"),
        )
    except BaseException as exc:
        observation["error_type"] = type(exc).__name__
    finally:
        if client is not None:
            client.close()
            observation["client_closed"] = 1
        if original_persist is not None:
            metrics.persist_metric_import = original_persist
        if listener_installed:
            event.remove(engine, "before_cursor_execute", synchronize_store_lock)
            observation["listener_removed"] = not event.contains(
                engine, "before_cursor_execute", synchronize_store_lock
            )
        observation["original_call_count"] = original_call_count
        if "engine" in locals():
            engine.dispose()
        results.put(observation)


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

    def _r248_assert_secret_absent(*values):
        if any(credential in value for value in values):
            raise AssertionError("credential exposure detected")

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
    dml_phase = contextvars.ContextVar("r245_dml_phase", default=None)
    process_timeout_counts = {"barrier": 0, "future": 0, "process": 0}
    forced_target_process_termination_count = 0
    sql_counts = {"foreign": 0, "missing": 0, "get": 0}
    dml_counts = {"foreign": 0, "missing": 0, "get": 0}
    engine = session_factory.kw["bind"]
    previous_override = app.dependency_overrides[get_db]

    def isolated_db():
        db = session_factory()
        db.execute(text("SET LOCAL statement_timeout = '10s'"))
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
            phase = headers.get(b"x-r245-dml-phase", b"").decode("ascii", "strict")
            phase_token = dml_phase.set(phase) if phase in dml_counts else None
            try:
                async with asyncio.timeout(15):
                    return await self.inner(scope, receive, send)
            finally:
                if phase_token is not None:
                    dml_phase.reset(phase_token)

    app.dependency_overrides[get_db] = isolated_db
    request_app = CorrelatedApp(app)

    def new_client():
        client = TestClient(request_app)
        with client_count_lock:
            client_counts["created"] += 1
        return client

    try:
        spawn = get_context("spawn")
        result_queue = spawn.Queue()
        entry_barrier = spawn.Barrier(3, timeout=20)
        lock_barrier = spawn.Barrier(2, timeout=15)
        database_url = engine.url.render_as_string(hide_password=False)
        previous_database_url = os.environ.get("DATABASE_URL")
        processes = [
            spawn.Process(
                target=_r248_child_import,
                args=(
                    worker,
                    dict(owner_headers),
                    owner_store_id,
                    csv_data,
                    entry_barrier,
                    lock_barrier,
                    result_queue,
                ),
                name=f"r248-{worker}",
            )
            for worker in ("worker-1", "worker-2")
        ]
        ready = {}
        observations = {}
        os.environ["DATABASE_URL"] = database_url
        try:
            for process in processes:
                process.start()
            while len(ready) < 2:
                try:
                    message = result_queue.get(timeout=30)
                except Empty:
                    process_timeout_counts["process"] += 1
                    raise AssertionError("R248 child readiness exceeded 30 seconds")
                if message["kind"] == "ready":
                    ready[message["worker"]] = message
                else:
                    observations[message["worker"]] = message
                    raise AssertionError(f"{message['worker']} failed before persistence: {message.get('error_type')}")

            with session_factory() as db:
                activity = db.execute(
                    text(
                        "SELECT pid, state, xact_start IS NOT NULL AS transaction_open "
                        "FROM pg_stat_activity WHERE pid IN (:pid_1, :pid_2)"
                    ),
                    {
                        "pid_1": ready["worker-1"]["pg_backend_pid"],
                        "pid_2": ready["worker-2"]["pg_backend_pid"],
                    },
                ).mappings().all()
            assert len(activity) == 2
            assert all(row["transaction_open"] and row["state"] == "idle in transaction" for row in activity)
            try:
                entry_barrier.wait(timeout=20)
            except Exception:
                process_timeout_counts["barrier"] += 1
                raise

            while len(observations) < 2:
                try:
                    message = result_queue.get(timeout=40)
                except Empty:
                    process_timeout_counts["process"] += 1
                    raise AssertionError("R248 child result exceeded 40 seconds")
                assert message["kind"] == "final"
                observations[message["worker"]] = message

            for process in processes:
                process.join(timeout=10)
                if process.is_alive():
                    process_timeout_counts["process"] += 1
                    raise AssertionError(f"{process.name} did not exit within 10 seconds")
                assert process.exitcode == 0
        finally:
            cleanup_failures = []
            try:
                for barrier in (entry_barrier, lock_barrier):
                    try:
                        barrier.abort()
                    except BaseException as exc:
                        cleanup_failures.append(type(exc).__name__)
                for process in processes:
                    try:
                        if process.is_alive():
                            process.terminate()
                            process.join(timeout=5)
                            forced_target_process_termination_count += 1
                        if process.is_alive():
                            process.kill()
                            process.join(timeout=5)
                        if process.is_alive():
                            cleanup_failures.append("ProcessStillAlive")
                    except BaseException as exc:
                        cleanup_failures.append(type(exc).__name__)
                for process in processes:
                    try:
                        if not process.is_alive():
                            process.close()
                    except BaseException as exc:
                        cleanup_failures.append(type(exc).__name__)
            finally:
                try:
                    if previous_database_url is None:
                        os.environ.pop("DATABASE_URL", None)
                    else:
                        os.environ["DATABASE_URL"] = previous_database_url
                finally:
                    result_queue.close()
                    result_queue.join_thread()
            if cleanup_failures:
                raise AssertionError("R248 target-process cleanup failed")

        assert all("error_type" not in row for row in observations.values())
        assert [observations[worker]["status"] for worker in ("worker-1", "worker-2")] == [200, 200]
        assert sorted(row["duplicate"] for row in observations.values()) == [False, True]
        response_payloads = [observations[worker]["response_json"] for worker in ("worker-1", "worker-2")]
        assert len({row["process_pid"] for row in observations.values()}) == 2
        assert len({(row["process_pid"], row["import_lock_id"]) for row in observations.values()}) == 2
        assert len({row["pg_backend_pid"] for row in observations.values()}) == 2
        assert len({row["transaction_id"] for row in observations.values()}) == 2
        assert all(row["transaction_open"] and row["transaction_isolation"] == "read committed" for row in observations.values())
        assert max(row["persist_start"] for row in observations.values()) < min(
            row["persist_end"] for row in observations.values()
        )
        assert all(
            row["authorization_present"]
            and row["auth_path"] == "bearer"
            and row["cookie_count_before"] == row["cookie_count_after"] == 0
            and row["client_created"] == row["client_closed"] == 1
            and row["store_for_update_reached"]
            and row["listener_removed"]
            and row["original_call_count"] == 1
            for row in observations.values()
        )
        assert process_timeout_counts == {"barrier": 0, "future": 0, "process": 0}
        assert forced_target_process_termination_count == 0
        with client_count_lock:
            client_counts["created"] += sum(row["client_created"] for row in observations.values())
            client_counts["closed"] += sum(row["client_closed"] for row in observations.values())

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
            _r248_assert_secret_absent(owner_audit.action + (owner_audit.detail or ""))

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
            checked_response_texts = [
                *(repr(payload) for payload in response_payloads),
                foreign.text,
                missing.text,
                records.text,
                business.text,
                owner_refresh.text,
            ]
            assert all("r244-foreign" not in response_text.lower() for response_text in checked_response_texts)
            _r248_assert_secret_absent(*checked_response_texts)
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
