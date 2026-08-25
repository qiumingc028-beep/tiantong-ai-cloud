import asyncio
import base64
import contextvars
from datetime import date
from io import BytesIO
import json
import os
from pathlib import Path
import select as select_io
import selectors
import subprocess
import sys
from threading import Lock
from time import monotonic
from types import MappingProxyType

import openpyxl
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from backend.config import get_settings
from backend.database import Base, get_db
from backend.main import app
from backend.models import Company, EmployeeLog, JdDailyMetric, MetricDaily, Permission, Role, Store, Tenant, User, UserStoreMembership


_r250_bootstrap_code = r"""
import importlib.util
import json
import os
from pathlib import Path
import select
import sys
from time import monotonic

worker = "bootstrap"
try:
    deadline = monotonic() + 15
    bootstrap_bytes = bytearray()
    while b"\n" not in bootstrap_bytes:
        remaining = deadline - monotonic()
        if remaining <= 0 or not select.select([sys.stdin], [], [], remaining)[0]:
            raise TimeoutError("bootstrap input timeout")
        chunk = os.read(sys.stdin.fileno(), 4096)
        if not chunk:
            raise RuntimeError("bootstrap input closed")
        bootstrap_bytes.extend(chunk)
        if len(bootstrap_bytes) > 1_048_576:
            raise RuntimeError("bootstrap input too large")
    bootstrap_line, trailing_bytes = bootstrap_bytes.split(b"\n", 1)
    if trailing_bytes:
        raise RuntimeError("unexpected bootstrap input")
    config = json.loads(bootstrap_line.decode("utf-8"))
    worker = config.get("worker", worker)
    backend_imported_before = any(
        name == "backend" or name.startswith("backend.") for name in sys.modules
    )
    if backend_imported_before:
        raise RuntimeError("backend imported before bootstrap")
    repo_root = Path(config.pop("repo_root")).resolve()
    test_file = (repo_root / "tests" / "test_usable_v1_jd_import_slice.py").resolve()
    if test_file.parent.parent != repo_root:
        raise RuntimeError("invalid repository root")
    os.environ["APP_ENV"] = "test"
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    os.environ["DATABASE_URL"] = config.pop("database_url")
    os.environ["JWT_SECRET"] = config.pop("jwt_secret")
    sys.path.insert(0, str(repo_root))
    spec = importlib.util.spec_from_file_location("_r250_jd_import_child", test_file)
    if spec is None or spec.loader is None:
        raise RuntimeError("child module loader unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module._r250_child_main(config, sys.stdin, sys.stdout, backend_imported_before)
except BaseException as exc:
    sys.stdout.write(json.dumps({
        "kind": "RESULT",
        "worker": worker,
        "error_type": type(exc).__name__,
    }, separators=(",", ":")) + "\n")
    sys.stdout.flush()
"""


def _r250_child_main(config, control_in, result_out, backend_imported_before):
    client = None
    listener_installed = False
    original_persist = None
    original_call_count = 0
    cleanup_failures = []
    control_buffer = bytearray()
    worker = config.pop("worker")
    authorization = config.pop("authorization")
    store_id = int(config.pop("store_id"))
    csv_data = base64.b64decode(config.pop("csv_data"), validate=True)
    config.clear()
    observation = {
        "kind": "RESULT",
        "worker": worker,
        "process_pid": os.getpid(),
        "client_created": 0,
        "client_closed": 0,
        "backend_imported_after_bootstrap": not backend_imported_before and "backend" in sys.modules,
    }

    def send_ready(phase, **values):
        result_out.write(json.dumps({
            "kind": "READY",
            "phase": phase,
            "worker": worker,
            **values,
        }, separators=(",", ":")) + "\n")
        result_out.flush()

    def wait_for_go(phase, timeout):
        deadline = monotonic() + timeout
        while b"\n" not in control_buffer:
            remaining = deadline - monotonic()
            if remaining <= 0 or not select_io.select([control_in], [], [], remaining)[0]:
                raise TimeoutError(f"{phase} GO timeout")
            chunk = os.read(control_in.fileno(), 4096)
            if not chunk:
                raise RuntimeError("child control pipe closed")
            control_buffer.extend(chunk)
            if len(control_buffer) > 65_536:
                raise RuntimeError("child control message too large")
        line, remainder = control_buffer.split(b"\n", 1)
        control_buffer[:] = remainder
        command = json.loads(line.decode("utf-8"))
        if command != {"kind": "GO", "phase": phase}:
            raise RuntimeError(f"invalid {phase} GO command")

    try:
        from backend.database import engine
        from backend.main import app as child_app
        from backend.routers import metrics

        route_endpoint = next(
            route.endpoint
            for route in metrics.router.routes
            if route.path == "/api/metrics/import" and "POST" in route.methods
        )
        route_globals = route_endpoint.__globals__
        original_persist = route_globals["persist_metric_import"]
        observation.update(
            route_module_path_match=(
                Path(metrics.__file__).resolve()
                == (Path(__file__).resolve().parents[1] / "backend" / "routers" / "metrics.py").resolve()
            ),
            route_endpoint_binding=route_endpoint is metrics.import_metrics_file,
            route_module_lock_binding=route_globals["IMPORT_LOCK"] is metrics.IMPORT_LOCK,
            original_persist_identity=(
                original_persist is metrics.persist_metric_import
                and original_persist.__module__ == metrics.__name__
                and original_persist.__name__ == "persist_metric_import"
            ),
        )

        def synchronize_store_lock(_connection, _cursor, statement, _parameters, _context, _executemany):
            normalized = " ".join(statement.upper().split())
            if observation.get("store_for_update_reached") or "FROM STORES" not in normalized or "FOR UPDATE" not in normalized:
                return
            observation["store_for_update_reached"] = True
            send_ready("store_lock")
            wait_for_go("store_lock", 15)

        def instrumented_persist(db, user, content, rows, selected_store_id):
            nonlocal original_call_count
            observation["lock_held_at_wrapper_entry"] = metrics.IMPORT_LOCK.locked()
            if not observation["lock_held_at_wrapper_entry"]:
                raise AssertionError("route import lock not held")
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
            send_ready(
                "transaction",
                process_pid=observation["process_pid"],
                pg_backend_pid=pg_backend_pid,
                transaction_id=transaction_id,
            )
            wait_for_go("transaction", 20)
            observation["persist_start"] = monotonic()
            original_call_count += 1
            try:
                return original_persist(db, user, content, rows, selected_store_id)
            finally:
                observation["persist_end"] = monotonic()

        event.listen(engine, "before_cursor_execute", synchronize_store_lock)
        listener_installed = True
        metrics.persist_metric_import = instrumented_persist
        observation["route_persist_wrapper_binding"] = (
            route_globals["persist_metric_import"] is instrumented_persist
        )
        client = TestClient(child_app)
        observation["client_created"] = 1
        observation["cookie_count_before"] = len(client.cookies)
        assert observation["cookie_count_before"] == 0
        headers = {"Authorization": authorization}
        assert authorization.startswith("Bearer ")
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
        try:
            if client is not None:
                client.close()
                observation["client_closed"] = 1
        except BaseException as exc:
            cleanup_failures.append(type(exc).__name__)
        try:
            if original_persist is not None:
                metrics.persist_metric_import = original_persist
        except BaseException as exc:
            cleanup_failures.append(type(exc).__name__)
        try:
            if listener_installed:
                event.remove(engine, "before_cursor_execute", synchronize_store_lock)
                observation["listener_removed"] = not event.contains(
                    engine, "before_cursor_execute", synchronize_store_lock
                )
        except BaseException as exc:
            cleanup_failures.append(type(exc).__name__)
        observation["original_call_count"] = original_call_count
        try:
            if "engine" in locals():
                engine.dispose()
        except BaseException as exc:
            cleanup_failures.append(type(exc).__name__)
        authorization = ""
        if "headers" in locals():
            headers.clear()
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("JWT_SECRET", None)
        if cleanup_failures:
            observation["error_type"] = "CleanupError"
        result_out.write(json.dumps(observation, separators=(",", ":")) + "\n")
        result_out.flush()


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

    def _r250_assert_secret_absent(secrets, *values):
        if any(secret and secret in value for secret in secrets for value in values):
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
    ipc_timeout_counts = {"ready": 0, "go": 0, "result": 0, "wait": 0}
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
        database_url = engine.url.render_as_string(hide_password=False)
        jwt_secret = get_settings().JWT_SECRET
        sensitive_values = (credential, database_url, jwt_secret)
        repo_root = Path(__file__).resolve().parents[1]
        child_env = {
            key: os.environ[key]
            for key in ("HOME", "LANG", "LC_ALL", "PATH", "TMPDIR")
            if os.environ.get(key)
        }
        child_env["PYTHONUNBUFFERED"] = "1"
        child_env["APP_ENV"] = "test"
        child_env["PYTHON_DOTENV_DISABLED"] = "1"
        _r250_assert_secret_absent(sensitive_values, repr(child_env))
        assert not {
            "DATABASE_URL", "REDIS_URL", "JWT_SECRET", "AUTHORIZATION", "COOKIE"
        }.intersection(child_env)
        argv = (sys.executable, "-u", "-c", _r250_bootstrap_code)
        _r250_assert_secret_absent(sensitive_values, *argv)
        children = {}
        observations = {}
        stderr_chunks = {"worker-1": [], "worker-2": []}
        stream_buffers = {}
        child_output_bytes = {"worker-1": 0, "worker-2": 0}
        selector = selectors.DefaultSelector()
        cleanup_failures = []
        max_ipc_buffer_bytes = 1_048_576

        def append_stream_chunk(worker, stream_kind, chunk):
            child_output_bytes[worker] += len(chunk)
            if child_output_bytes[worker] > max_ipc_buffer_bytes:
                raise AssertionError("R250 child output limit exceeded")
            buffer = stream_buffers[(worker, stream_kind)]
            buffer.extend(chunk)
            if len(buffer) > max_ipc_buffer_bytes:
                raise AssertionError("R250 child IPC buffer limit exceeded")
            return buffer

        def send_message(process, message, timeout, timeout_key):
            _, writable, _ = select_io.select([], [process.stdin], [], timeout)
            if not writable:
                ipc_timeout_counts[timeout_key] += 1
                raise AssertionError("R250 child control pipe timeout")
            process.stdin.write(
                (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
            )
            process.stdin.flush()

        def read_stage(kind, phase, timeout, timeout_key):
            deadline = monotonic() + timeout
            pending = set(children)
            messages = {}
            while pending:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    ipc_timeout_counts[timeout_key] += 1
                    raise AssertionError(f"R250 {kind} {phase or ''} timeout")
                events = selector.select(remaining)
                if not events:
                    ipc_timeout_counts[timeout_key] += 1
                    raise AssertionError(f"R250 {kind} {phase or ''} timeout")
                for key, _mask in events:
                    worker, stream_kind = key.data
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        if stream_kind == "stdout" and worker in pending:
                            raise AssertionError("R250 child stdout closed before protocol completion")
                        continue
                    buffer = append_stream_chunk(worker, stream_kind, chunk)
                    while b"\n" in buffer:
                        line, remainder = buffer.split(b"\n", 1)
                        buffer[:] = remainder
                        if stream_kind == "stderr":
                            stderr_chunks[worker].append(line.decode("utf-8", "replace"))
                            continue
                        try:
                            message = json.loads(line.decode("utf-8"))
                        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                            raise AssertionError("R250 child emitted invalid JSON stdout") from exc
                        if message.get("kind") == "RESULT" and kind != "RESULT":
                            observations[worker] = message
                            raise AssertionError("R250 child failed before protocol completion")
                        if (
                            message.get("kind") != kind
                            or (phase is not None and message.get("phase") != phase)
                            or message.get("worker") != worker
                            or worker not in pending
                        ):
                            raise AssertionError("R250 child protocol mismatch")
                        messages[worker] = message
                        pending.remove(worker)
            return messages

        def drain_child_streams(timeout):
            deadline = monotonic() + timeout
            open_streams = {
                (key.data[0], key.data[1]) for key in selector.get_map().values()
            }
            while open_streams:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    ipc_timeout_counts["wait"] += 1
                    raise AssertionError("R250 child output drain timeout")
                events = selector.select(remaining)
                if not events:
                    ipc_timeout_counts["wait"] += 1
                    raise AssertionError("R250 child output drain timeout")
                for key, _mask in events:
                    worker, stream_kind = key.data
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        open_streams.discard((worker, stream_kind))
                        continue
                    append_stream_chunk(worker, stream_kind, chunk)

        try:
            for worker in ("worker-1", "worker-2"):
                process = subprocess.Popen(
                    argv,
                    cwd=repo_root,
                    env=child_env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,
                    bufsize=0,
                    shell=False,
                )
                children[worker] = process
                stream_buffers[(worker, "stdout")] = bytearray()
                stream_buffers[(worker, "stderr")] = bytearray()
                selector.register(process.stdout, selectors.EVENT_READ, (worker, "stdout"))
                selector.register(process.stderr, selectors.EVENT_READ, (worker, "stderr"))

            bootstrap_payloads = {
                worker: {
                    "worker": worker,
                    "repo_root": str(repo_root),
                    "database_url": database_url,
                    "jwt_secret": jwt_secret,
                    "authorization": owner_headers["Authorization"],
                    "store_id": owner_store_id,
                    "csv_data": base64.b64encode(csv_data).decode("ascii"),
                }
                for worker in children
            }
            for worker, process in children.items():
                send_message(process, bootstrap_payloads[worker], 5, "go")
            bootstrap_payloads.clear()
            del bootstrap_payloads

            ready = read_stage("READY", "transaction", 30, "ready")

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
            for process in children.values():
                send_message(process, {"kind": "GO", "phase": "transaction"}, 5, "go")

            read_stage("READY", "store_lock", 30, "ready")
            for process in children.values():
                send_message(process, {"kind": "GO", "phase": "store_lock"}, 5, "go")

            observations.update(read_stage("RESULT", None, 40, "result"))
            drain_child_streams(10)
            stdout_tails = []
            for worker, process in children.items():
                try:
                    exit_code = process.wait(timeout=1)
                except subprocess.TimeoutExpired as exc:
                    ipc_timeout_counts["wait"] += 1
                    raise AssertionError("R250 child process wait timeout") from exc
                assert exit_code == 0
                buffered_stdout = bytes(stream_buffers[(worker, "stdout")])
                buffered_stderr = bytes(stream_buffers[(worker, "stderr")])
                stdout_tails.append(buffered_stdout.decode("utf-8", "strict"))
                stderr_chunks[worker].append(buffered_stderr.decode("utf-8", "replace"))
            assert all(not tail.strip() for tail in stdout_tails)
            serialized_results = [json.dumps(row, sort_keys=True) for row in observations.values()]
            _r250_assert_secret_absent(sensitive_values, *serialized_results, *stdout_tails)
            _r250_assert_secret_absent(
                sensitive_values,
                *(chunk for chunks in stderr_chunks.values() for chunk in chunks),
            )
        finally:
            try:
                selector.close()
                for process in children.values():
                    try:
                        if process.poll() is None:
                            process.terminate()
                            process.wait(timeout=5)
                            forced_target_process_termination_count += 1
                    except BaseException as exc:
                        cleanup_failures.append(type(exc).__name__)
                    try:
                        if process.poll() is None:
                            process.kill()
                            process.wait(timeout=5)
                    except BaseException as exc:
                        cleanup_failures.append(type(exc).__name__)
            finally:
                for process in children.values():
                    for stream in (process.stdin, process.stdout, process.stderr):
                        try:
                            if stream is not None and not stream.closed:
                                stream.close()
                        except BaseException as exc:
                            cleanup_failures.append(type(exc).__name__)
            if cleanup_failures:
                raise AssertionError("R250 target-process cleanup failed")

        assert all("error_type" not in row for row in observations.values())
        assert [observations[worker]["status"] for worker in ("worker-1", "worker-2")] == [200, 200]
        assert sorted(row["duplicate"] for row in observations.values()) == [False, True]
        response_payloads = [observations[worker]["response_json"] for worker in ("worker-1", "worker-2")]
        assert len({row["process_pid"] for row in observations.values()}) == 2
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
            and row["backend_imported_after_bootstrap"]
            and row["route_module_path_match"]
            and row["route_endpoint_binding"]
            and row["route_module_lock_binding"]
            and row["route_persist_wrapper_binding"]
            and row["original_persist_identity"]
            and row["lock_held_at_wrapper_entry"]
            and row["store_for_update_reached"]
            and row["listener_removed"]
            and row["original_call_count"] == 1
            for row in observations.values()
        )
        assert ipc_timeout_counts == {"ready": 0, "go": 0, "result": 0, "wait": 0}
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
            _r250_assert_secret_absent(
                sensitive_values,
                owner_audit.action + (owner_audit.detail or ""),
            )

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
            _r250_assert_secret_absent(sensitive_values, *checked_response_texts)
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
