"""PostgreSQL-only historical migration and uniqueness regression tests.

These tests create disposable databases and execute Alembic.  They never use
SQLite and never permit a drift-skip environment variable.
"""

from __future__ import annotations

import hashlib
import io
import importlib.util
import json
import os
import re
import subprocess
import sys
import tarfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError, IntegrityError, PendingRollbackError
from sqlalchemy.orm import Session, sessionmaker
from tests.test_helpers import latest_alembic_head_line


ROOT = Path(__file__).resolve().parents[1]
FIX_COMMIT_ENV = "MIGRATION_CODE_FIX_COMMIT"
ADMIN_URL_ENV = "V2_ALPHA_POSTGRES_ADMIN_URL"
KNOWN_BROKEN_HISTORICAL_BASELINE = "2ca1a2579569324ce3ca82f68332fb7f96be004d"
FINAL_REVISION = "0042_v2_alpha_workflow_unique_constraints"
FROZEN_0037_COMMIT = "85586868bad3dd5d0fecba5f840383feccdc1c78"
EXPECTED_UNIQUES = {
    "uq_alpha_workflow_runs_root_span_id": ("root_span_id",),
    "uq_alpha_workflow_runs_workflow_id": ("workflow_id",),
    "uq_alpha_workflow_runs_orchestrator_run_id": ("orchestrator_run_id",),
    "uq_alpha_workflow_runs_research_report_id": ("research_report_id",),
    "uq_alpha_workflow_runs_skill_invocation_id": ("skill_invocation_id",),
}
EXPECTED_0042_COLUMNS = {
    "workflow_id",
    "root_span_id",
    "orchestrator_run_id",
    "research_report_id",
    "skill_invocation_id",
}
ALPHA_FLAGS = {
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


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True
    ).stdout.strip()


def load_migration(filename: str):
    path = ROOT / "alembic/versions" / filename
    spec = importlib.util.spec_from_file_location(f"qa_{path.stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def alembic(cwd: Path, database_url: str, *args: str, check: bool = True):
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    for key in tuple(env):
        assert "DRIFT" not in key or "SKIP" not in key, f"禁止Drift跳过变量：{key}"
    env.pop("ALEMBIC_SKIP_SQLITE_DRIFT", None)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=check,
    )


@pytest.fixture(scope="module")
def postgres_database_factory():
    raw_admin_url = os.getenv(ADMIN_URL_ENV)
    assert raw_admin_url, f"真实PostgreSQL专项要求设置 {ADMIN_URL_ENV}"
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


@pytest.fixture(scope="module")
def migration_fix_commit():
    commit = os.getenv(FIX_COMMIT_ENV)
    assert commit, f"收到修复后必须设置 {FIX_COMMIT_ENV}"
    subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT, check=True)
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=ROOT
    ).returncode == 0, "MIGRATION_CODE_FIX_COMMIT尚未合并到测试分支"
    return commit


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
    from conftest import FakeRedis, seed_database
    from backend.database import get_db
    from backend.main import app

    database_url = postgres_database_factory("alpha_api")
    alembic(ROOT, database_url, "upgrade", "head")
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


def extract_git_tree(commit: str, destination: Path) -> None:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", commit], cwd=ROOT, check=True, capture_output=True
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        bundle.extractall(destination, filter="data")


def test_0037_blob_matches_frozen_baseline():
    relative = "alembic/versions/0037_v2_execution_observability_security_ops.py"
    frozen = subprocess.run(["git", "show", f"{FROZEN_0037_COMMIT}:{relative}"], cwd=ROOT, check=True, capture_output=True).stdout
    assert (ROOT / relative).read_bytes() == frozen, "0037在冻结基线后被再次改写"


def test_0042_declares_exact_architecture_constraint_set():
    migration = load_migration("0042_v2_alpha_workflow_unique_constraints.py")
    declared = {column for _name, column in migration._UNIQUE_COLUMNS}
    assert declared == EXPECTED_0042_COLUMNS
    assert "knowledge_asset_id" not in declared


def test_real_merge_base_0037_boolean_failure_is_reproduced_and_fixed(
    tmp_path, postgres_database_factory, migration_fix_commit
):
    historical_tree = tmp_path / "merge-base"
    historical_tree.mkdir()
    extract_git_tree(KNOWN_BROKEN_HISTORICAL_BASELINE, historical_tree)

    historical_url = postgres_database_factory("boolean_history")
    assert make_url(historical_url).get_backend_name() == "postgresql"
    failed = alembic(historical_tree, historical_url, "upgrade", "0037_v2_execution_observability_security_ops", check=False)
    combined = f"{failed.stdout}\n{failed.stderr}"
    assert failed.returncode != 0, "真实Merge Base的0037 Boolean缺陷未被复现"
    assert any(marker in combined.casefold() for marker in ("boolean", "datatype mismatch", "invalid input syntax")), combined

    fixed_url = postgres_database_factory("boolean_fixed")
    upgraded = alembic(ROOT, fixed_url, "upgrade", "head")
    assert upgraded.returncode == 0
    current = alembic(ROOT, fixed_url, "current").stdout
    assert current.strip() == latest_alembic_head_line()


def constraint_columns(connection) -> dict[str, tuple[str, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT con.conname, array_agg(att.attname ORDER BY key_cols.ordinality)
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN unnest(con.conkey) WITH ORDINALITY AS key_cols(attnum, ordinality) ON TRUE
            JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = key_cols.attnum
            WHERE rel.relname = 'alpha_workflow_runs' AND con.contype = 'u'
            GROUP BY con.conname
            """
        )
        return {name: tuple(columns) for name, columns in cursor.fetchall()}


def unique_indexes(connection) -> dict[str, tuple[bool, tuple[str, ...]]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT idx.relname, i.indisunique,
                   array_agg(att.attname ORDER BY key_cols.ordinality)
            FROM pg_index i
            JOIN pg_class rel ON rel.oid = i.indrelid
            JOIN pg_class idx ON idx.oid = i.indexrelid
            JOIN pg_namespace ns ON ns.oid = rel.relnamespace
            JOIN unnest(i.indkey) WITH ORDINALITY AS key_cols(attnum, ordinality) ON key_cols.attnum > 0
            JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = key_cols.attnum
            WHERE ns.nspname = 'public' AND rel.relname = 'alpha_workflow_runs'
            GROUP BY idx.relname, i.indisunique
            """
        )
        return {name: (is_unique, tuple(columns)) for name, is_unique, columns in cursor.fetchall()}


def constraint_backing_indexes(connection) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT idx.relname
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_class idx ON idx.oid = con.conindid
            WHERE rel.relname = 'alpha_workflow_runs' AND con.contype IN ('p', 'u')
            """
        )
        return {row[0] for row in cursor.fetchall()}


def assert_expected_constraints(connection) -> None:
    actual = constraint_columns(connection)
    for name, columns in EXPECTED_UNIQUES.items():
        assert actual.get(name) == columns, f"唯一约束缺失或列错误：{name} expected={columns} actual={actual.get(name)}"


def seed_scenario(connection) -> str:
    scenario_id = f"scenario-{uuid.uuid4().hex[:20]}"
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO alpha_workflow_scenarios (scenario_id, scenario_code, title, enabled) VALUES (%s, %s, %s, true)",
            (scenario_id, f"code-{uuid.uuid4().hex}", "PostgreSQL uniqueness regression"),
        )
    connection.commit()
    return scenario_id


def run_values(suffix: str) -> dict[str, object]:
    return {
        "trace_id": f"trace-{suffix}",
        "root_span_id": f"root-{suffix}",
        "workflow_id": f"workflow-{suffix}",
        "orchestrator_run_id": f"orchestrator-{suffix}",
        "research_report_id": str(uuid.uuid4()),
        "knowledge_asset_id": str(uuid.uuid4()),
        "skill_invocation_id": int(uuid.uuid4().int % 1_000_000_000),
    }


def insert_run(connection, scenario_id: str, run_id: str, values: dict[str, object], conflict_constraint: str | None = None):
    columns = ["run_id", "scenario_id", "status", *values.keys()]
    params = [run_id, scenario_id, "运行中", *values.values()]
    statement = sql.SQL("INSERT INTO alpha_workflow_runs ({}) VALUES ({})").format(
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )
    if conflict_constraint:
        statement += sql.SQL(" ON CONFLICT ON CONSTRAINT {} DO NOTHING").format(sql.Identifier(conflict_constraint))
    with connection.cursor() as cursor:
        cursor.execute(statement, params)
        return cursor.rowcount


def test_final_head_unique_constraints_reject_duplicates_and_allow_multiple_nulls(
    postgres_database_factory, migration_fix_commit
):
    del migration_fix_commit
    database_url = postgres_database_factory("uniques")
    alembic(ROOT, database_url, "upgrade", "head")
    dsn = make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)

    with psycopg2.connect(dsn) as connection:
        assert_expected_constraints(connection)
        scenario_id = seed_scenario(connection)
        for constraint, columns in EXPECTED_UNIQUES.items():
            original = run_values(uuid.uuid4().hex)
            assert insert_run(connection, scenario_id, str(uuid.uuid4()), original) == 1
            connection.commit()
            retry = run_values(uuid.uuid4().hex)
            for column in columns:
                retry[column] = original[column]
            with pytest.raises(psycopg2.errors.UniqueViolation):
                insert_run(connection, scenario_id, str(uuid.uuid4()), retry)
            connection.rollback()
            assert insert_run(connection, scenario_id, str(uuid.uuid4()), retry, constraint) == 0
            connection.commit()

        for _constraint, columns in EXPECTED_UNIQUES.items():
            nullable_column = columns[0]
            first, second = run_values(uuid.uuid4().hex), run_values(uuid.uuid4().hex)
            first[nullable_column] = None
            second[nullable_column] = None
            assert insert_run(connection, scenario_id, str(uuid.uuid4()), first) == 1
            assert insert_run(connection, scenario_id, str(uuid.uuid4()), second) == 1
            connection.commit()

def test_model_allows_knowledge_asset_reuse_across_runs():
    from sqlalchemy import UniqueConstraint
    from backend.alpha_workflow.models import AlphaWorkflowRun

    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in AlphaWorkflowRun.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    expected = {(column,) for column in EXPECTED_0042_COLUMNS | {"trace_id"}}
    assert unique_columns == expected
    assert ("knowledge_asset_id",) not in unique_columns


def _alpha_state_counts(db):
    from backend.agent_runtime.models import AgentExecution
    from backend.alpha_workflow.models import AlphaWorkflowEvent, AlphaWorkflowRun, AlphaWorkflowScenario
    from backend.brain_orchestrator.models import BrainOrchestratorLog, BrainTaskEdge, BrainTaskGraph, BrainTaskNode
    from backend.knowledge_center.models import KnowledgeAsset, KnowledgeVersion
    from backend.models import AiEmployee, TaskCenterResult, TaskCenterTask
    from backend.research_runtime.models import ResearchExecution
    from backend.skills_engine.models import SkillInvocation

    models = {
        "runs": AlphaWorkflowRun,
        "graphs": BrainTaskGraph,
        "nodes": BrainTaskNode,
        "edges": BrainTaskEdge,
        "logs": BrainOrchestratorLog,
        "events": AlphaWorkflowEvent,
        "employees": AiEmployee,
        "scenarios": AlphaWorkflowScenario,
        "tasks": TaskCenterTask,
        "task_results": TaskCenterResult,
        "agent_executions": AgentExecution,
        "research_executions": ResearchExecution,
        "knowledge_assets": KnowledgeAsset,
        "knowledge_versions": KnowledgeVersion,
        "skill_invocations": SkillInvocation,
    }
    return {name: db.query(model).count() for name, model in models.items()}


def _r49_alpha_object_state(db):
    from backend.agent_runtime.models import AgentExecution
    from backend.alpha_workflow.models import AlphaWorkflowEvent, AlphaWorkflowRun, AlphaWorkflowScenario
    from backend.brain_orchestrator.models import BrainOrchestratorLog, BrainTaskEdge, BrainTaskGraph, BrainTaskNode
    from backend.knowledge_center.models import KnowledgeAsset, KnowledgeVersion
    from backend.models import AiEmployee, TaskCenterResult, TaskCenterTask
    from backend.research_runtime.models import ResearchExecution
    from backend.skills_engine.models import SkillInvocation

    models = {
        "runs": AlphaWorkflowRun,
        "graphs": BrainTaskGraph,
        "nodes": BrainTaskNode,
        "edges": BrainTaskEdge,
        "logs": BrainOrchestratorLog,
        "events": AlphaWorkflowEvent,
        "employees": AiEmployee,
        "scenarios": AlphaWorkflowScenario,
        "tasks": TaskCenterTask,
        "task_results": TaskCenterResult,
        "agent_executions": AgentExecution,
        "research_executions": ResearchExecution,
        "knowledge_assets": KnowledgeAsset,
        "knowledge_versions": KnowledgeVersion,
        "skill_invocations": SkillInvocation,
    }

    def canonical(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

    state = {}
    for name, model in models.items():
        primary_key = tuple(model.__table__.primary_key.columns)
        rows = db.query(model).order_by(*primary_key).all()
        objects = {}
        payloads = []
        for row in rows:
            identity = canonical([getattr(row, column.name) for column in primary_key])
            payload = {column.name: getattr(row, column.name) for column in model.__table__.columns}
            serialized = canonical(payload)
            objects[identity] = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
            payloads.append(payload)
        state[name] = {
            "primary_keys": tuple(objects),
            "objects": objects,
            "content_sha256": hashlib.sha256(canonical(payloads).encode("utf-8")).hexdigest(),
        }
    return state


def _assert_r49_existing_objects_unchanged(before, after):
    for name, previous in before.items():
        assert set(previous["primary_keys"]) <= set(after[name]["primary_keys"]), name
        for identity, digest in previous["objects"].items():
            assert after[name]["objects"][identity] == digest, (name, identity)


def _r49_request_hash(identity):
    payload = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _assert_one_canonical_graph(db, run_id: str):
    from backend.brain_orchestrator.models import BrainOrchestratorLog, BrainTaskEdge, BrainTaskGraph, BrainTaskNode

    graph = db.query(BrainTaskGraph).filter(BrainTaskGraph.canonical_run_id == run_id).one()
    assert db.query(BrainOrchestratorLog).filter(BrainOrchestratorLog.graph_id == graph.graph_id).count() == 1
    assert db.query(BrainTaskNode).filter(BrainTaskNode.graph_id == graph.graph_id).count() > 0
    assert db.query(BrainTaskEdge).filter(BrainTaskEdge.graph_id == graph.graph_id).count() > 0
    assert db.query(BrainTaskGraph).filter(BrainTaskGraph.canonical_run_id.is_(None)).count() == 0
    return graph


def _create_scoped_owner(client, test_db, label, *, tenant_id=None, company_id=None, store_id=None):
    from backend.auth import hash_password
    from backend.models import Company, Store, Tenant, User, UserStoreMembership

    with test_db() as db:
        if tenant_id is None:
            tenant = Tenant(tenant_code=f"r48-{label}", tenant_name=label, active=True)
            db.add(tenant)
            db.flush()
            tenant_id = tenant.id
        if company_id is None:
            company = Company(
                tenant_id=tenant_id,
                company_code=f"r48-{label}",
                company_name=label,
                active=True,
            )
            db.add(company)
            db.flush()
            company_id = company.id
        if store_id is None:
            store = Store(
                platform="jd",
                store_code=f"r48-{label}",
                store_name=label,
                tenant_id=tenant_id,
                company_id=company_id,
                active=True,
            )
            db.add(store)
            db.flush()
            store_id = store.id
        user = User(
            username=f"r48-{label}",
            password_hash=hash_password("password"),
            role="owner",
            display_name=label,
            tenant_id=tenant_id,
            company_id=company_id,
            active=True,
        )
        db.add(user)
        db.flush()
        db.add(UserStoreMembership(user_id=user.id, store_id=store_id, active=True, can_read=True, can_write=True))
        db.commit()
        user_id = user.id
    login = client.post("/api/login", json={"username": f"r48-{label}", "password": "password"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}, (user_id, tenant_id, company_id, store_id)


def test_r48_run_routes_fail_closed_for_foreign_ownership(postgres_alpha_runtime):
    from backend.alpha_workflow.models import AlphaWorkflowRun
    from backend.models import User, UserStoreMembership

    client, boss_headers, test_db = postgres_alpha_runtime
    created = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "R48 ownership source", "trace_id": f"r48-owner-{uuid.uuid4()}"},
    )
    assert created.status_code == 200
    run_id = created.json()["run"]["run_id"]
    with test_db() as db:
        boss = db.query(User).filter(User.username == "boss").one()
        boss_store_id = db.query(UserStoreMembership.store_id).filter(
            UserStoreMembership.user_id == boss.id,
            UserStoreMembership.active.is_(True),
            UserStoreMembership.can_read.is_(True),
        ).one()[0]
        boss_scope = (boss.tenant_id, boss.company_id, boss_store_id)
        run = db.get(AlphaWorkflowRun, run_id)
        run.status = "已失败"
        run.recovery_status = "待恢复"
        db.commit()

    tenant_headers, _ = _create_scoped_owner(client, test_db, "foreign-tenant")
    company_headers, _ = _create_scoped_owner(
        client, test_db, "foreign-company", tenant_id=boss_scope[0]
    )
    shop_headers, _ = _create_scoped_owner(
        client,
        test_db,
        "foreign-shop",
        tenant_id=boss_scope[0],
        company_id=boss_scope[1],
    )
    requester_headers, _ = _create_scoped_owner(
        client,
        test_db,
        "foreign-requester",
        tenant_id=boss_scope[0],
        company_id=boss_scope[1],
        store_id=boss_scope[2],
    )
    foreign_headers = [tenant_headers, company_headers, shop_headers, requester_headers]
    with test_db() as db:
        before = _alpha_state_counts(db)
        original_status = db.get(AlphaWorkflowRun, run_id).status

    read_suffixes = ("", "/trace", "/audit", "/report", "/stages")
    for headers in foreign_headers:
        listed = client.get("/api/v2/alpha-workflows/runs", headers=headers)
        assert listed.status_code == 200
        assert run_id not in {item["run_id"] for item in listed.json()["items"]}
        health = client.get("/api/v2/alpha-workflows/health", headers=headers)
        dashboard = client.get("/api/v2/alpha-workflows/dashboard", headers=headers)
        assert health.status_code == dashboard.status_code == 200
        assert health.json()["latest_run"] is None and health.json()["run_count"] == 0
        assert dashboard.json()["latest_run"] is None and dashboard.json()["run_count"] == 0
        for suffix in read_suffixes:
            missing = client.get(f"/api/v2/alpha-workflows/runs/missing-r48{suffix}", headers=headers)
            foreign = client.get(f"/api/v2/alpha-workflows/runs/{run_id}{suffix}", headers=headers)
            assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json()) == (
                404,
                {"detail": "Alpha Workflow 运行记录不存在"},
            )
        for action in ("recover", "cancel"):
            missing = client.post(
                f"/api/v2/alpha-workflows/runs/missing-r48/{action}",
                headers=headers,
                json={"reason": "foreign request"},
            )
            foreign = client.post(
                f"/api/v2/alpha-workflows/runs/{run_id}/{action}",
                headers=headers,
                json={"reason": "foreign request"},
            )
            assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json()) == (
                404,
                {"detail": "Alpha Workflow 运行记录不存在"},
            )

    with test_db() as db:
        assert _alpha_state_counts(db) == before
        assert db.get(AlphaWorkflowRun, run_id).status == original_status


def test_r48_missing_trace_is_stable_scoped_and_concurrent(postgres_alpha_runtime):
    from backend.alpha_workflow.models import AlphaWorkflowRun
    from backend.brain_orchestrator.models import BrainTaskGraph
    from backend.brain_orchestrator.planner import resolve_graph_ownership
    from backend.models import User, UserStoreMembership

    client, boss_headers, test_db = postgres_alpha_runtime
    payload = {"input_text": "R48 stable missing trace"}
    first = client.post("/api/v2/alpha-workflows/demo", headers=boss_headers, json=payload)
    assert first.status_code == 200
    effective_trace = first.json()["run"]["trace_id"]
    assert re.fullmatch(r"auto-[0-9a-f]{64}", effective_trace)
    assert len(effective_trace) == 69 <= 120
    with test_db() as db:
        before_replay = _alpha_state_counts(db)
        boss = db.query(User).filter(User.username == "boss").one()
        scope = resolve_graph_ownership(db, boss)
        store_id = db.query(UserStoreMembership.store_id).filter(
            UserStoreMembership.user_id == boss.id,
            UserStoreMembership.active.is_(True),
            UserStoreMembership.can_read.is_(True),
        ).one()[0]
        boss_scope = (boss.tenant_id, boss.company_id, store_id)
    replay = client.post("/api/v2/alpha-workflows/demo", headers=boss_headers, json=payload)
    assert replay.status_code == 200
    assert replay.json()["run"]["run_id"] == first.json()["run"]["run_id"]
    with test_db() as db:
        assert _alpha_state_counts(db) == before_replay

    identity = {"input_text": payload["input_text"], "scenario_code": "apple_latest_ai_strategy"}
    expected_payload = {
        "domain": "alpha-workflow-auto-trace:v1",
        "ownership_scope_key": scope.ownership_scope_key,
        "request_identity": identity,
    }
    script = (
        "import hashlib,json,sys;"
        "p=json.loads(sys.argv[1]);"
        "print('auto-'+hashlib.sha256(json.dumps(p,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest())"
    )
    derived = subprocess.run(
        [sys.executable, "-c", script, json.dumps(expected_payload, ensure_ascii=False)],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    assert effective_trace == derived

    concurrent_payload = {"input_text": "R48 four-way missing trace"}
    with test_db() as db:
        before_concurrent = _alpha_state_counts(db)
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(
                lambda _index: client.post(
                    "/api/v2/alpha-workflows/demo", headers=boss_headers, json=concurrent_payload
                ),
                range(4),
            )
        )
    assert {response.status_code for response in responses} == {200}
    assert len({response.json()["run"]["run_id"] for response in responses}) == 1
    with test_db() as db:
        after_concurrent = _alpha_state_counts(db)
        assert after_concurrent["runs"] - before_concurrent["runs"] == 1
        assert after_concurrent["graphs"] - before_concurrent["graphs"] == 1
        assert after_concurrent["logs"] - before_concurrent["logs"] == 1
        assert after_concurrent["tasks"] - before_concurrent["tasks"] == 1
        assert after_concurrent["research_executions"] - before_concurrent["research_executions"] == 1
        assert after_concurrent["knowledge_assets"] - before_concurrent["knowledge_assets"] == 1
        assert after_concurrent["skill_invocations"] - before_concurrent["skill_invocations"] == 1
        concurrent_run = db.query(AlphaWorkflowRun).filter(
            AlphaWorkflowRun.trace_id == responses[0].json()["run"]["trace_id"]
        ).one()
        assert db.query(BrainTaskGraph).filter(BrainTaskGraph.canonical_run_id == concurrent_run.run_id).count() == 1

    different = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "R48 different normalized payload"},
    )
    assert different.status_code == 200
    assert different.json()["run"]["trace_id"] != effective_trace
    requester_headers, _ = _create_scoped_owner(
        client,
        test_db,
        "missing-trace-requester",
        tenant_id=boss_scope[0],
        company_id=boss_scope[1],
        store_id=boss_scope[2],
    )
    other_scope = client.post("/api/v2/alpha-workflows/demo", headers=requester_headers, json=payload)
    assert other_scope.status_code == 200
    assert other_scope.json()["run"]["trace_id"] != effective_trace


def test_r48_default_scenario_is_inside_canonical_transaction(postgres_alpha_runtime, monkeypatch):
    client, boss_headers, test_db = postgres_alpha_runtime
    with test_db() as db:
        before_failure = _alpha_state_counts(db)

    def fail_planning(*_args, **_kwargs):
        raise RuntimeError("r48 injected planning failure")

    with monkeypatch.context() as patcher:
        patcher.setattr("backend.brain_orchestrator.orchestrator.plan_dry_run", fail_planning)
        with pytest.raises(RuntimeError, match="r48 injected planning failure"):
            client.post(
                "/api/v2/alpha-workflows/demo",
                headers=boss_headers,
                json={"input_text": "R48 scenario rollback"},
            )
    with test_db() as db:
        assert _alpha_state_counts(db) == before_failure

    payload = {"input_text": "R48 concurrent default scenario"}
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(
                lambda _index: client.post("/api/v2/alpha-workflows/demo", headers=boss_headers, json=payload),
                range(4),
            )
        )
    assert {response.status_code for response in responses} == {200}
    assert len({response.json()["run"]["run_id"] for response in responses}) == 1
    with test_db() as db:
        after_default = _alpha_state_counts(db)
        assert after_default["scenarios"] - before_failure["scenarios"] == 1

    explicit_trace = f"r48-scenario-conflict-{uuid.uuid4()}"
    first = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "R48 scenario first", "trace_id": explicit_trace},
    )
    assert first.status_code == 200
    with test_db() as db:
        before_conflict = _alpha_state_counts(db)
    conflict = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "R48 scenario different", "trace_id": explicit_trace},
    )
    assert conflict.status_code == 409
    with test_db() as db:
        assert _alpha_state_counts(db) == before_conflict


def test_r48_recovery_trace_is_stable_bounded_and_owned(postgres_alpha_runtime):
    from backend.alpha_workflow.models import AlphaWorkflowEvent, AlphaWorkflowRun

    client, boss_headers, test_db = postgres_alpha_runtime
    original_trace = "r" * 114
    created = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "R48 recovery trace boundary", "trace_id": original_trace},
    )
    assert created.status_code == 200
    run_id = created.json()["run"]["run_id"]
    with test_db() as db:
        run = db.get(AlphaWorkflowRun, run_id)
        run.status = "已失败"
        run.recovery_status = "待恢复"
        db.commit()

    payload = {"reason": "stable recovery request"}
    first = client.post(
        f"/api/v2/alpha-workflows/runs/{run_id}/recover", headers=boss_headers, json=payload
    )
    assert first.status_code == 200
    recovered = first.json()["run"]
    assert re.fullmatch(r"recovery-[0-9a-f]{64}", recovered["trace_id"])
    assert len(recovered["trace_id"]) == 73 <= 120
    assert recovered["recovered_from_run_id"] == run_id
    assert recovered["workflow_context"]["recovery_from_run_id"] == run_id
    with test_db() as db:
        stored = db.get(AlphaWorkflowRun, run_id)
        assert stored.trace_id == original_trace
        assert stored.root_span_id == f"{original_trace}:root"
        assert db.query(AlphaWorkflowEvent).filter(
            AlphaWorkflowEvent.run_id == run_id,
            AlphaWorkflowEvent.trace_id == recovered["trace_id"],
            AlphaWorkflowEvent.event_code == "workflow_recovered",
        ).count() == 1
        before_replay = _alpha_state_counts(db)

    replay = client.post(
        f"/api/v2/alpha-workflows/runs/{run_id}/recover", headers=boss_headers, json=payload
    )
    assert replay.status_code == 200
    assert replay.json()["run"]["trace_id"] == recovered["trace_id"]
    with test_db() as db:
        assert _alpha_state_counts(db) == before_replay

    different = client.post(
        f"/api/v2/alpha-workflows/runs/{run_id}/recover",
        headers=boss_headers,
        json={"reason": "different recovery request"},
    )
    assert different.status_code == 409
    tenant_headers, _ = _create_scoped_owner(client, test_db, "recovery-foreign-tenant")
    with test_db() as db:
        before_foreign = _alpha_state_counts(db)
    missing = client.post(
        "/api/v2/alpha-workflows/runs/missing-r48/recover", headers=tenant_headers, json=payload
    )
    foreign = client.post(
        f"/api/v2/alpha-workflows/runs/{run_id}/recover", headers=tenant_headers, json=payload
    )
    assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json()) == (
        404,
        {"detail": "Alpha Workflow 运行记录不存在"},
    )
    with test_db() as db:
        assert _alpha_state_counts(db) == before_foreign
        assert db.get(AlphaWorkflowRun, run_id).trace_id == original_trace


@pytest.mark.parametrize(
    "corruption",
    (
        "identity_missing",
        "identity_empty",
        "identity_unparseable",
        "identity_incomplete",
        "identity_not_normalized",
        "hash_missing",
        "hash_empty",
        "hash_wrong_length",
        "hash_not_hex",
        "identity_hash_mismatch",
        "incoming_hash_mismatch",
        "incoming_identity_mismatch",
    ),
)
def test_r49_corrupt_replay_identity_metadata_fails_closed(
    postgres_alpha_runtime,
    corruption,
):
    from backend.alpha_workflow.models import AlphaWorkflowRun

    client, boss_headers, test_db = postgres_alpha_runtime
    trace_id = f"r49-replay-{uuid.uuid4()}"
    original_input = f"R49 strict replay metadata {corruption}"
    created = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": original_input, "trace_id": trace_id},
    )
    assert created.status_code == 200
    run_id = created.json()["run"]["run_id"]
    incoming_input = original_input

    with test_db() as db:
        run = db.get(AlphaWorkflowRun, run_id)
        context = json.loads(run.workflow_context_json)
        linked_ids = context["linked_ids"]
        valid_identity = linked_ids["request_identity"]
        if corruption == "identity_missing":
            linked_ids.pop("request_identity")
        elif corruption == "identity_empty":
            linked_ids["request_identity"] = {}
        elif corruption == "identity_unparseable":
            linked_ids["request_identity"] = ["not", "an", "identity"]
        elif corruption == "identity_incomplete":
            linked_ids["request_identity"] = {"input_text": original_input}
        elif corruption == "identity_not_normalized":
            damaged = {**valid_identity, "input_text": f" {original_input} "}
            linked_ids["request_identity"] = damaged
            linked_ids["request_hash"] = _r49_request_hash(damaged)
        elif corruption == "hash_missing":
            linked_ids.pop("request_hash")
        elif corruption == "hash_empty":
            linked_ids["request_hash"] = ""
        elif corruption == "hash_wrong_length":
            linked_ids["request_hash"] = "0" * 63
        elif corruption == "hash_not_hex":
            linked_ids["request_hash"] = "g" * 64
        elif corruption == "identity_hash_mismatch":
            linked_ids["request_identity"] = {**valid_identity, "input_text": "damaged identity"}
        elif corruption == "incoming_hash_mismatch":
            linked_ids["request_hash"] = "0" * 64
        elif corruption == "incoming_identity_mismatch":
            incoming_input = f"{original_input} changed"
        run.workflow_context_json = json.dumps(context, ensure_ascii=False)
        db.commit()
        before = _r49_alpha_object_state(db)

    conflict = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": incoming_input, "trace_id": trace_id},
    )
    assert (conflict.status_code, conflict.json()) == (
        409,
        {"detail": "Alpha Workflow 已存在相同Trace但请求内容不同"},
    )
    with test_db() as db:
        assert _r49_alpha_object_state(db) == before


def test_r49_missing_trace_ownership_scope_matrix(postgres_alpha_runtime):
    from backend.alpha_workflow.models import AlphaWorkflowRun
    from backend.brain_orchestrator.models import BrainTaskGraph
    from backend.brain_orchestrator.planner import resolve_graph_ownership
    from backend.models import TaskCenterResult, User, UserStoreMembership
    from backend.skills_engine.models import SkillInvocation

    client, boss_headers, test_db = postgres_alpha_runtime
    with test_db() as db:
        boss = db.query(User).filter(User.username == "boss").one()
        boss_store_id = db.query(UserStoreMembership.store_id).filter(
            UserStoreMembership.user_id == boss.id,
            UserStoreMembership.active.is_(True),
            UserStoreMembership.can_read.is_(True),
        ).one()[0]
        boss_ids = (boss.id, boss.tenant_id, boss.company_id, boss_store_id)

    tenant_headers, tenant_ids = _create_scoped_owner(client, test_db, "r49-trace-tenant")
    company_headers, company_ids = _create_scoped_owner(
        client, test_db, "r49-trace-company", tenant_id=boss_ids[1]
    )
    shop_headers, shop_ids = _create_scoped_owner(
        client,
        test_db,
        "r49-trace-shop",
        tenant_id=boss_ids[1],
        company_id=boss_ids[2],
    )
    requester_headers, requester_ids = _create_scoped_owner(
        client,
        test_db,
        "r49-trace-requester",
        tenant_id=boss_ids[1],
        company_id=boss_ids[2],
        store_id=boss_ids[3],
    )
    client.cookies.clear()
    scopes = (
        ("baseline", boss_headers, boss_ids),
        ("tenant", tenant_headers, tenant_ids),
        ("company", company_headers, company_ids),
        ("shop", shop_headers, shop_ids),
        ("requester", requester_headers, requester_ids),
    )
    request = {
        "input_text": "R49 identical missing trace ownership matrix",
        "tenant_id": boss_ids[1],
        "company_id": boss_ids[2],
        "store_ids": [boss_ids[3]],
        "requester_id": boss_ids[0],
    }
    with test_db() as db:
        initial = _r49_alpha_object_state(db)

    identities = {}
    for dimension, headers, scope_ids in scopes:
        response = client.post("/api/v2/alpha-workflows/demo", headers=headers, json=request)
        assert response.status_code == 200, (dimension, response.text)
        run = response.json()["run"]
        assert re.fullmatch(r"auto-[0-9a-f]{64}", run["trace_id"])
        assert len(run["trace_id"]) == 69 <= 120
        with test_db() as db:
            stored_run = db.get(AlphaWorkflowRun, run["run_id"])
            graph = db.query(BrainTaskGraph).filter(
                BrainTaskGraph.canonical_run_id == run["run_id"]
            ).one()
            owner = db.get(User, scope_ids[0])
            resolved = resolve_graph_ownership(db, owner)
            assert stored_run.user_id == scope_ids[0]
            assert graph.graph_id == stored_run.orchestrator_run_id
            assert graph.ownership_scope_key == resolved.ownership_scope_key
            assert graph.tenant_id == resolved.tenant_id == scope_ids[1]
            assert graph.company_id == resolved.company_id == scope_ids[2]
            assert graph.requester_id == resolved.requester_id == scope_ids[0]
            assert graph.store_scope_key == resolved.store_scope_key
            effective_trace_payload = {
                "domain": "alpha-workflow-auto-trace:v1",
                "ownership_scope_key": resolved.ownership_scope_key,
                "request_identity": {
                    "input_text": request["input_text"],
                    "scenario_code": "apple_latest_ai_strategy",
                },
            }
            expected_trace = "auto-" + hashlib.sha256(
                json.dumps(
                    effective_trace_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            assert run["trace_id"] == expected_trace
            before_replay = _r49_alpha_object_state(db)
        replay = client.post("/api/v2/alpha-workflows/demo", headers=headers, json=request)
        assert replay.status_code == 200
        assert replay.json()["run"]["run_id"] == run["run_id"]
        assert replay.json()["run"]["trace_id"] == run["trace_id"]
        with test_db() as db:
            assert _r49_alpha_object_state(db) == before_replay
        identities[dimension] = (run["run_id"], run["orchestrator_run_id"], run["trace_id"])

    assert len({identity[0] for identity in identities.values()}) == len(scopes)
    assert len({identity[1] for identity in identities.values()}) == len(scopes)
    assert len({identity[2] for identity in identities.values()}) == len(scopes)

    with test_db() as db:
        after_creation = _r49_alpha_object_state(db)
        _assert_r49_existing_objects_unchanged(initial, after_creation)
        for name in (
            "runs",
            "graphs",
            "logs",
            "tasks",
            "agent_executions",
            "research_executions",
            "knowledge_assets",
            "knowledge_versions",
            "skill_invocations",
        ):
            assert len(after_creation[name]["primary_keys"]) - len(initial[name]["primary_keys"]) == len(scopes), name
        new_runs = db.query(AlphaWorkflowRun).filter(
            AlphaWorkflowRun.run_id.in_([identity[0] for identity in identities.values()])
        ).all()
        assert len(new_runs) == len(scopes)
        runs_by_task_id = {run.task_id: run for run in new_runs}
        assert None not in runs_by_task_id
        assert len(runs_by_task_id) == len(scopes)

        results_by_task_id = {task_id: [] for task_id in runs_by_task_id}
        new_results = db.query(TaskCenterResult).filter(
            TaskCenterResult.task_id.in_(runs_by_task_id)
        ).all()
        for result in new_results:
            results_by_task_id[result.task_id].append(result)

        result_ids = set()
        semantic_identities = set()
        for task_id, results in results_by_task_id.items():
            run = runs_by_task_id[task_id]
            assert len(results) == 2
            assert len({result.id for result in results}) == 2
            assert len(
                {
                    hashlib.sha256(result.result_content.encode("utf-8")).hexdigest()
                    for result in results
                }
            ) == 2

            invocation = db.get(SkillInvocation, run.skill_invocation_id)
            assert invocation is not None
            assert invocation.task_id == task_id
            assert invocation.output_summary
            context = json.loads(run.workflow_context_json)
            assert context["report_content"]
            assert context["report_hash"] == hashlib.sha256(
                context["report_content"].encode("utf-8")
            ).hexdigest()

            skill_results = [
                result
                for result in results
                if result.result_content == invocation.output_summary
                and result.submitted_by_id is None
                and json.loads(result.attachments_json) == []
            ]
            report_results = [
                result
                for result in results
                if result.result_content == context["report_content"]
                and result.submitted_by_id == run.user_id
                and json.loads(result.attachments_json) == [context["report_hash"]]
            ]
            assert len(skill_results) == 1
            assert len(report_results) == 1
            assert skill_results[0].id != report_results[0].id

            result_ids.update(result.id for result in results)
            semantic_identities.update(
                {
                    ("skill_invocation_output", run.skill_invocation_id),
                    ("alpha_final_research_report", run.research_report_id),
                }
            )

        assert len(new_results) == 2 * len(scopes)
        assert len(result_ids) == 2 * len(scopes)
        assert len(semantic_identities) == 2 * len(scopes)
        assert len(after_creation["scenarios"]["primary_keys"]) - len(initial["scenarios"]["primary_keys"]) == 1
        before_rejected_reads = after_creation

    read_suffixes = ("", "/trace", "/report", "/stages")
    for dimension, headers, _scope_ids in scopes:
        own_run_id = identities[dimension][0]
        for foreign_dimension, (foreign_run_id, _graph_id, _trace_id) in identities.items():
            if foreign_run_id == own_run_id:
                continue
            for suffix in read_suffixes:
                missing = client.get(
                    f"/api/v2/alpha-workflows/runs/missing-r49{suffix}", headers=headers
                )
                foreign = client.get(
                    f"/api/v2/alpha-workflows/runs/{foreign_run_id}{suffix}", headers=headers
                )
                assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json()) == (
                    404,
                    {"detail": "Alpha Workflow 运行记录不存在"},
                ), (dimension, foreign_dimension, suffix)
    with test_db() as db:
        assert _r49_alpha_object_state(db) == before_rejected_reads


def test_same_idempotency_key_returns_existing_run_without_new_rows(
    postgres_alpha_runtime,
):
    client, boss_headers, test_db = postgres_alpha_runtime
    payload = {"input_text": "验证409幂等语义", "trace_id": f"pg-contract-{uuid.uuid4()}"}
    first = client.post("/api/v2/alpha-workflows/demo", headers=boss_headers, json=payload)
    with test_db() as db:
        before_replay = _alpha_state_counts(db)
    second = client.post("/api/v2/alpha-workflows/demo", headers=boss_headers, json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["run"]["run_id"] == first.json()["run"]["run_id"]
    with test_db() as db:
        assert _alpha_state_counts(db) == before_replay
        _assert_one_canonical_graph(db, first.json()["run"]["run_id"])


def test_concurrent_same_trace_replay_returns_one_run_without_duplicate_side_effects(
    postgres_alpha_runtime,
):
    from backend.agent_runtime.models import AgentExecution
    from backend.alpha_workflow.models import AlphaWorkflowEvent, AlphaWorkflowRun
    from backend.brain_orchestrator.models import BrainTaskGraph
    from backend.knowledge_center.models import KnowledgeAsset, KnowledgeVersion
    from backend.models import TaskCenterTask
    from backend.research_runtime.models import ResearchExecution
    from backend.skills_engine.models import SkillInvocation

    client, boss_headers, test_db = postgres_alpha_runtime
    payload = {"input_text": "验证并发幂等语义", "trace_id": f"pg-concurrent-{uuid.uuid4()}"}
    with test_db() as db:
        before = _alpha_state_counts(db)
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(
                lambda _index: client.post("/api/v2/alpha-workflows/demo", headers=boss_headers, json=payload),
                range(4),
            )
        )
    assert {response.status_code for response in responses} == {200}
    run_ids = {response.json()["run"]["run_id"] for response in responses}
    assert len(run_ids) == 1
    with test_db() as db:
        run = db.query(AlphaWorkflowRun).filter(AlphaWorkflowRun.trace_id == payload["trace_id"]).one()
        assert run.run_id in run_ids
        graph = db.query(BrainTaskGraph).filter(BrainTaskGraph.graph_id == run.orchestrator_run_id).one()
        assert graph.canonical_run_id == run.run_id
        assert graph.requester_id == run.user_id
        after = _alpha_state_counts(db)
        assert after["runs"] - before["runs"] == 1
        assert after["graphs"] - before["graphs"] == 1
        assert after["logs"] - before["logs"] == 1
        _assert_one_canonical_graph(db, run.run_id)
        assert db.query(TaskCenterTask).filter(TaskCenterTask.id == run.task_id).count() == 1
        assert db.query(AgentExecution).filter(AgentExecution.trace_id == payload["trace_id"]).count() == 1
        assert db.query(ResearchExecution).filter(ResearchExecution.trace_id == payload["trace_id"]).count() == 1
        assert db.query(KnowledgeAsset).filter(KnowledgeAsset.knowledge_id == run.knowledge_asset_id).count() == 1
        assert db.query(KnowledgeVersion).filter(KnowledgeVersion.knowledge_id == run.knowledge_asset_id).count() == 1
        assert db.query(SkillInvocation).filter(SkillInvocation.trace_id == payload["trace_id"]).count() == 1
        event_ids = [row.event_id for row in db.query(AlphaWorkflowEvent).filter(AlphaWorkflowEvent.run_id == run.run_id)]
        assert len(event_ids) == len(set(event_ids))


def test_same_trace_with_different_request_returns_409(postgres_alpha_runtime):
    client, boss_headers, test_db = postgres_alpha_runtime
    trace_id = f"pg-different-request-{uuid.uuid4()}"
    first = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "验证相同Trace的第一个请求", "trace_id": trace_id},
    )
    with test_db() as db:
        before_conflict = _alpha_state_counts(db)
    second = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "验证相同Trace的不同请求", "trace_id": trace_id},
    )
    assert first.status_code == 200
    assert second.status_code == 409
    with test_db() as db:
        assert _alpha_state_counts(db) == before_conflict
        _assert_one_canonical_graph(db, first.json()["run"]["run_id"])


def test_concurrent_mixed_payloads_persist_only_the_winner(postgres_alpha_runtime):
    from backend.alpha_workflow.models import AlphaWorkflowRun

    client, boss_headers, test_db = postgres_alpha_runtime
    trace_id = f"pg-mixed-{uuid.uuid4()}"
    payloads = [
        {"input_text": "混合并发请求A", "trace_id": trace_id},
        {"input_text": "混合并发请求B", "trace_id": trace_id},
        {"input_text": "混合并发请求C", "trace_id": trace_id},
        {"input_text": "混合并发请求D", "trace_id": trace_id},
    ]
    with test_db() as db:
        before = _alpha_state_counts(db)
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(lambda payload: client.post(
            "/api/v2/alpha-workflows/demo", headers=boss_headers, json=payload
        ), payloads))
    assert [response.status_code for response in responses].count(200) == 1
    assert [response.status_code for response in responses].count(409) == 3
    winner = next(response for response in responses if response.status_code == 200)
    with test_db() as db:
        after = _alpha_state_counts(db)
        assert after["runs"] - before["runs"] == 1
        assert after["graphs"] - before["graphs"] == 1
        assert after["logs"] - before["logs"] == 1
        run = db.query(AlphaWorkflowRun).filter(AlphaWorkflowRun.trace_id == trace_id).one()
        assert run.run_id == winner.json()["run"]["run_id"]
        _assert_one_canonical_graph(db, run.run_id)


def test_atomic_planning_failure_rolls_back_graph_and_run(postgres_alpha_runtime):
    from backend.alpha_workflow.registry import ensure_default_scenarios
    from backend.database import get_db
    from backend.main import app

    client, boss_headers, test_db = postgres_alpha_runtime
    with test_db() as db:
        ensure_default_scenarios(db)
        before = _alpha_state_counts(db)
    request_db = test_db()
    previous_override = app.dependency_overrides[get_db]
    fired = 0
    flushed_deltas = {}

    def override_request_db():
        yield request_db

    def fail_atomic_commit(session):
        nonlocal fired, flushed_deltas
        if fired:
            return
        assert session is request_db
        current = _alpha_state_counts(session)
        flushed_deltas = {name: current[name] - before[name] for name in before}
        assert flushed_deltas["runs"] == 1
        assert flushed_deltas["graphs"] == 1
        assert flushed_deltas["nodes"] > 0
        assert flushed_deltas["edges"] > 0
        assert flushed_deltas["logs"] == 1
        fired += 1
        raise RuntimeError("injected atomic persistence failure")

    app.dependency_overrides[get_db] = override_request_db
    event.listen(request_db, "before_commit", fail_atomic_commit)
    try:
        with pytest.raises(RuntimeError, match="injected atomic persistence failure"):
            client.post(
                "/api/v2/alpha-workflows/demo",
                headers=boss_headers,
                json={"input_text": "原子事务失败注入", "trace_id": f"pg-rollback-{uuid.uuid4()}"},
            )
        assert not request_db.in_transaction()
        assert request_db.is_active
    finally:
        event.remove(request_db, "before_commit", fail_atomic_commit)
        app.dependency_overrides[get_db] = previous_override
        request_db.close()
    assert not event.contains(request_db, "before_commit", fail_atomic_commit)
    assert fired == 1
    assert flushed_deltas["runs"] == 1
    assert flushed_deltas["graphs"] == 1
    with test_db() as db:
        assert _alpha_state_counts(db) == before


def test_trace_id_114_succeeds_and_115_is_zero_write_400(postgres_alpha_runtime):
    from backend.alpha_workflow.schemas import TRACE_ID_MAX_LENGTH
    from backend.brain_orchestrator.models import BrainTaskGraph

    client, boss_headers, test_db = postgres_alpha_runtime
    assert TRACE_ID_MAX_LENGTH == 114
    valid_trace = "t" * TRACE_ID_MAX_LENGTH
    accepted = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "验证Trace边界", "trace_id": valid_trace},
    )
    assert accepted.status_code == 200
    run = accepted.json()["run"]
    assert run["trace_id"] == valid_trace
    assert run["workflow_id"] == f"alpha-{valid_trace}"
    assert run["root_span_id"] == f"{valid_trace}:root"
    assert len(run["workflow_id"]) == 120
    assert len(run["root_span_id"]) == 119
    with test_db() as db:
        graph = db.query(BrainTaskGraph).filter(BrainTaskGraph.canonical_run_id == run["run_id"]).one()
        assert graph.execution_scope_key == f"trace:{valid_trace}"
        assert len(graph.execution_scope_key) == 120
        before_rejected = _alpha_state_counts(db)
    rejected = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "验证Trace超限", "trace_id": "t" * (TRACE_ID_MAX_LENGTH + 1)},
    )
    blank = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "验证Trace空白", "trace_id": "   "},
    )
    assert rejected.status_code == 400
    assert blank.status_code == 400
    with test_db() as db:
        assert _alpha_state_counts(db) == before_rejected


def test_graph_scope_and_full_semantic_identity_are_fail_closed(postgres_alpha_runtime, monkeypatch):
    from backend.auth import hash_password
    from backend.models import Company, Store, Tenant, User, UserStoreMembership

    client, _boss_headers, test_db = postgres_alpha_runtime

    def create_identity(
        label: str,
        *,
        tenant_id: int | None = None,
        company_id: int | None = None,
    ):
        with test_db() as db:
            if tenant_id is None:
                tenant = Tenant(tenant_code=f"tenant-{label}", tenant_name=label, active=True)
                db.add(tenant)
                db.flush()
                tenant_id = tenant.id
            if company_id is None:
                company = Company(
                    tenant_id=tenant_id,
                    company_code=f"company-{label}",
                    company_name=label,
                    active=True,
                )
                db.add(company)
                db.flush()
                company_id = company.id
            user = User(
                username=f"scope-{label}",
                password_hash=hash_password("password"),
                role="owner",
                display_name=label,
                tenant_id=tenant_id,
                company_id=company_id,
                active=True,
            )
            db.add(user)
            db.flush()
            store = Store(
                platform="jd",
                store_code=f"store-{label}",
                store_name=label,
                tenant_id=tenant_id,
                company_id=company_id,
                active=True,
            )
            db.add(store)
            db.flush()
            db.add(UserStoreMembership(user_id=user.id, store_id=store.id, active=True, can_read=True, can_write=True))
            db.commit()
            return user.id, tenant_id, company_id, store.id

    first_user = create_identity("tenant-a")
    second_user = create_identity("tenant-b")
    with test_db() as db:
        second_company = Company(
            tenant_id=first_user[1],
            company_code="company-other",
            company_name="Other Company",
            active=True,
        )
        db.add(second_company)
        db.flush()
        second_company_id = second_company.id
        db.commit()
    create_identity("company-other", tenant_id=first_user[1], company_id=second_company_id)

    def headers(label: str):
        login = client.post("/api/login", json={"username": f"scope-{label}", "password": "password"})
        assert login.status_code == 200
        return {"Authorization": f"Bearer {login.json()['token']}"}

    goal = "相同范围安全测试目标"
    tenant_a = client.post("/api/orchestrator/plan", headers=headers("tenant-a"), json={"request_text": goal})
    tenant_b = client.post("/api/orchestrator/plan", headers=headers("tenant-b"), json={"request_text": goal})
    company_b = client.post("/api/orchestrator/plan", headers=headers("company-other"), json={"request_text": goal})
    assert {tenant_a.status_code, tenant_b.status_code, company_b.status_code} == {200}
    assert len({tenant_a.json()["graph_id"], tenant_b.json()["graph_id"], company_b.json()["graph_id"]}) == 3
    assert client.get(
        f"/api/orchestrator/tasks/{tenant_a.json()['graph_id']}",
        headers=headers("tenant-b"),
    ).status_code == 404

    with test_db() as db:
        membership = db.query(UserStoreMembership).filter(UserStoreMembership.user_id == first_user[0]).one()
        membership.active = False
        replacement = Store(
            platform="jd",
            store_code="store-tenant-a-replacement",
            store_name="Replacement",
            tenant_id=first_user[1],
            company_id=first_user[2],
            active=True,
        )
        db.add(replacement)
        db.flush()
        db.add(UserStoreMembership(user_id=first_user[0], store_id=replacement.id, active=True, can_read=True, can_write=True))
        db.commit()
    changed_shop = client.post("/api/orchestrator/plan", headers=headers("tenant-a"), json={"request_text": goal})
    assert changed_shop.status_code == 200
    assert changed_shop.json()["graph_id"] != tenant_a.json()["graph_id"]

    short_prefix_hashes = iter(("a" * 12 + "b" * 52, "a" * 12 + "c" * 52))
    monkeypatch.setattr("backend.brain_orchestrator.planner._semantic_hash", lambda _payload: next(short_prefix_hashes))
    semantic_a = client.post("/api/orchestrator/plan", headers=headers("tenant-a"), json={"request_text": "语义输入A"})
    semantic_b = client.post("/api/orchestrator/plan", headers=headers("tenant-a"), json={"request_text": "语义输入B"})
    assert semantic_a.status_code == semantic_b.status_code == 200
    assert semantic_a.json()["graph_id"] != semantic_b.json()["graph_id"]

    monkeypatch.setattr("backend.brain_orchestrator.planner._semantic_hash", lambda _payload: "f" * 64)
    collision_a = client.post("/api/orchestrator/plan", headers=headers("tenant-a"), json={"request_text": "完整载荷碰撞A"})
    collision_b = client.post("/api/orchestrator/plan", headers=headers("tenant-a"), json={"request_text": "完整载荷碰撞B"})
    assert collision_a.status_code == 200
    assert collision_b.status_code == 409


def test_non_target_graph_unique_error_is_not_swallowed(postgres_alpha_runtime, monkeypatch):
    client, boss_headers, _test_db = postgres_alpha_runtime
    monkeypatch.setattr("backend.brain_orchestrator.planner.uuid4", lambda: uuid.UUID(int=0))
    first = client.post(
        "/api/orchestrator/plan",
        headers=boss_headers,
        json={"request_text": "非目标唯一约束测试A"},
    )
    assert first.status_code == 200
    with pytest.raises(IntegrityError):
        client.post(
            "/api/orchestrator/plan",
            headers=boss_headers,
            json={"request_text": "非目标唯一约束测试B"},
        )


def test_0044_to_0045_isolates_non_empty_legacy_graph(postgres_database_factory):
    database_url = postgres_database_factory("legacy_graph_scope")
    alembic(ROOT, database_url, "upgrade", "0044_tenant_company_store_authorization_scope")
    dsn = make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO brain_task_graphs (graph_id, user_request, goal, task_type, risk_level, "
                "approval_required, estimated_cost_level, status, dry_run, created_by) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                ("graph-legacy-ownerless", "legacy", "legacy", "business_analysis", "low", False, "low", "planned", True, "legacy"),
            )
            legacy_id = cursor.fetchone()[0]
        connection.commit()
    alembic(ROOT, database_url, "upgrade", "head")
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT ownership_scope_key, execution_scope_key, semantic_hash, semantic_payload_json, "
                "tenant_id, company_id, requester_id, store_scope_key FROM brain_task_graphs WHERE id=%s",
                (legacy_id,),
            )
            row = cursor.fetchone()
    assert row is not None
    assert row[0].startswith(f"legacy:{legacy_id}:")
    assert row[1] == f"legacy:{legacy_id}"
    assert len(row[2]) == 64 and row[3]
    assert row[4:7] == (None, None, None)
    assert row[7] == f"legacy:{legacy_id}"
    migration_source = (ROOT / "alembic/versions/0045_brain_task_graph_scope_identity.py").read_text()
    assert "cannot downgrade: BrainTaskGraph ownership identity data would be lost" in migration_source


@pytest.mark.parametrize("constraint_name", sorted(EXPECTED_UNIQUES))
def test_other_run_unique_conflicts_map_to_chinese_409(
    postgres_alpha_runtime, constraint_name
):
    from backend.alpha_workflow.models import AlphaWorkflowRun

    client, boss_headers, test_db = postgres_alpha_runtime
    occupied = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "先创建占用身份的Run", "trace_id": f"occupied-{uuid.uuid4()}"},
    )
    assert occupied.status_code == 200
    column_name = EXPECTED_UNIQUES[constraint_name][0]
    with test_db() as db:
        occupied_run = db.get(AlphaWorkflowRun, occupied.json()["run"]["run_id"])
        occupied_value = getattr(occupied_run, column_name)
        if occupied_value is None:
            occupied_value = int(uuid.uuid4().int % 1_000_000_000) if column_name == "skill_invocation_id" else str(uuid.uuid4())
            setattr(occupied_run, column_name, occupied_value)
            db.commit()
    fired = False

    def force_real_cross_run_conflict(session, _flush_context, _instances):
        nonlocal fired
        if fired:
            return
        new_run = next((row for row in session.new if isinstance(row, AlphaWorkflowRun)), None)
        if new_run is None:
            return
        setattr(new_run, column_name, occupied_value)
        fired = True

    event.listen(Session, "before_flush", force_real_cross_run_conflict)
    try:
        response = client.post(
            "/api/v2/alpha-workflows/demo",
            headers=boss_headers,
            json={"input_text": "唯一字段已被另一Run占用", "trace_id": f"conflict-{uuid.uuid4()}"},
        )
    finally:
        event.remove(Session, "before_flush", force_real_cross_run_conflict)
    assert fired, "故障注入未经过真实Service Session flush"
    assert response.status_code == 409
    detail = response.json().get("detail")
    assert isinstance(detail, str) and re.search(r"[\u4e00-\u9fff]", detail)
    assert "IntegrityError" not in detail and "duplicate key" not in detail.casefold()


def test_0041_legacy_knowledge_unique_is_removed_safely_by_0042(
    postgres_database_factory, migration_fix_commit
):
    del migration_fix_commit
    database_url = postgres_database_factory("legacy_0041")
    alembic(ROOT, database_url, "upgrade", "0041_v2_alpha_migration_history_repair")
    dsn = make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg2.connect(dsn) as connection:
        before_constraints = constraint_columns(connection)
        before_indexes = unique_indexes(connection)
        assert "uq_alpha_workflow_runs_knowledge_asset_id" in before_constraints or before_indexes.get("uq_alpha_workflow_runs_knowledge_asset_id", (False, ()))[0]
        scenario_id = seed_scenario(connection)
        assert insert_run(connection, scenario_id, str(uuid.uuid4()), run_values(uuid.uuid4().hex)) == 1
        connection.commit()
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM alpha_workflow_runs")
            before_count = cursor.fetchone()[0]

    alembic(ROOT, database_url, "upgrade", "head")
    with psycopg2.connect(dsn) as connection:
        assert "uq_alpha_workflow_runs_knowledge_asset_id" not in constraint_columns(connection)
        indexes = unique_indexes(connection)
        assert indexes.get("ix_alpha_workflow_runs_knowledge_asset_id") == (False, ("knowledge_asset_id",))
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM alpha_workflow_runs")
            assert cursor.fetchone()[0] == before_count
        shared = str(uuid.uuid4())
        first, second = run_values(uuid.uuid4().hex), run_values(uuid.uuid4().hex)
        first["knowledge_asset_id"] = shared
        second["knowledge_asset_id"] = shared
        assert insert_run(connection, scenario_id, str(uuid.uuid4()), first) == 1
        assert insert_run(connection, scenario_id, str(uuid.uuid4()), second) == 1


def test_0042_downgrade_has_no_knowledge_unique_or_name_collisions(
    postgres_database_factory, migration_fix_commit
):
    del migration_fix_commit
    database_url = postgres_database_factory("downgrade_0042")
    alembic(ROOT, database_url, "upgrade", "head")
    dsn = make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg2.connect(dsn) as connection:
        scenario_id = seed_scenario(connection)
        shared = str(uuid.uuid4())
        first, second = run_values(uuid.uuid4().hex), run_values(uuid.uuid4().hex)
        first["knowledge_asset_id"] = shared
        second["knowledge_asset_id"] = shared
        assert insert_run(connection, scenario_id, str(uuid.uuid4()), first) == 1
        assert insert_run(connection, scenario_id, str(uuid.uuid4()), second) == 1
        connection.commit()

    alembic(ROOT, database_url, "downgrade", "0041_v2_alpha_migration_history_repair")
    with psycopg2.connect(dsn) as connection:
        constraints = constraint_columns(connection)
        indexes = unique_indexes(connection)
        assert "uq_alpha_workflow_runs_knowledge_asset_id" not in constraints
        assert not indexes.get("uq_alpha_workflow_runs_knowledge_asset_id", (False, ()))[0]
        same_names = set(constraints) & set(indexes)
        assert same_names <= constraint_backing_indexes(connection), "downgrade后存在非约束支撑的同名索引冲突"
        for name, columns in EXPECTED_UNIQUES.items():
            assert constraints.get(name) == columns or indexes.get(name) == (True, columns)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM alpha_workflow_runs WHERE knowledge_asset_id = %s", (shared,))
            assert cursor.fetchone()[0] == 2
    alembic(ROOT, database_url, "upgrade", "head")
    with psycopg2.connect(dsn) as connection:
        assert_expected_constraints(connection)
        assert "uq_alpha_workflow_runs_knowledge_asset_id" not in constraint_columns(connection)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM alpha_workflow_runs WHERE knowledge_asset_id = %s", (shared,))
            assert cursor.fetchone()[0] == 2


def test_0005_revision_dag_is_guarded_historical_naming_debt():
    first = load_migration("0005_tiancang_knowledge_tables.py")
    successor = load_migration("0005_knowledge_center_tables.py")
    assert successor.down_revision == first.revision
    assert callable(first._has_table) and callable(successor._has_table)
    assert FINAL_REVISION == "0042_v2_alpha_workflow_unique_constraints"


def test_0005_complete_postgresql_chain_reaches_head(postgres_database_factory, migration_fix_commit):
    del migration_fix_commit
    database_url = postgres_database_factory("full_0005_chain")
    alembic(ROOT, database_url, "upgrade", "head")
    assert alembic(ROOT, database_url, "current").stdout.strip() == latest_alembic_head_line()


def make_agent_execution(db: Session):
    from backend.agent_runtime.models import AgentCapability, AgentExecution
    from backend.models import TaskCenterTask

    task = TaskCenterTask(
        title="Research persistence regression",
        description="验证正式持久化事务",
        status="running",
        priority="normal",
        source="orchestrator",
    )
    capability = AgentCapability(
        capability_id=f"research-{uuid.uuid4()}",
        capability_name="Research persistence regression",
        capability_type="research",
        executor_type="research",
        risk_level="low",
        enabled=True,
        readonly=True,
    )
    execution = AgentExecution(
        execution_id=str(uuid.uuid4()),
        task_id=None,
        capability_id=capability.capability_id,
        status="completed",
        risk_level="low",
        approval_status="not_required",
        executor_type="research",
        trace_id=f"research-trace-{uuid.uuid4()}",
    )
    db.add_all([task, capability])
    db.flush()
    execution.task_id = task.id
    db.add(execution)
    db.commit()
    return execution, task.id


def research_payload(execution_id: str):
    source_id = "恶意上游Source-" + ("S" * 160)
    evidence_id = "恶意上游Evidence-" + ("E" * 160)
    input_payload = {
        "topic": "Alpha Research持久化",
        "goal": "验证稳定ID与外键",
        "max_queries": 2,
        "max_sources": 2,
        "min_sources": 1,
        "language": "zh-CN",
        "allowed_domains": [],
        "blocked_domains": [],
        "cross_validate": True,
        "report_format": "中文研究报告",
    }
    output_payload = {
        "query_count": 1,
        "source_count": 1,
        "duplicate_count": 0,
        "core_conclusions": ["持久化ID必须稳定"],
        "conflicts": [],
        "uncertainties": [],
        "report_title": "Research持久化报告",
        "report_content": "正式报告内容",
        "report_hash": uuid.uuid4().hex,
        "sources": [{
            "source_id": source_id,
            "url": "https://docs.python.org/3/",
            "redacted_url": "https://docs.python.org/3/",
            "title": "Python Docs",
            "content_hash": uuid.uuid4().hex,
            "is_primary": True,
        }],
        "evidence": [{
            "evidence_id": evidence_id,
            "source_id": source_id,
            "raw_url": "https://docs.python.org/3/",
            "redacted_url": "https://docs.python.org/3/",
            "page_title": "Python Docs",
            "evidence_content_hash": uuid.uuid4().hex,
            "trace_id": f"research-trace-{execution_id}",
        }],
    }
    return input_payload, output_payload


def research_counts_and_ids(db: Session):
    from backend.research_runtime.models import ResearchClaim, ResearchEvidence, ResearchQuery, ResearchSource

    models = (ResearchQuery, ResearchSource, ResearchClaim, ResearchEvidence)
    counts = tuple(db.query(model).count() for model in models)
    ids = {
        "query": tuple(row.query_id for row in db.query(ResearchQuery).order_by(ResearchQuery.query_id)),
        "source": tuple(row.source_id for row in db.query(ResearchSource).order_by(ResearchSource.source_id)),
        "claim": tuple(row.claim_id for row in db.query(ResearchClaim).order_by(ResearchClaim.claim_id)),
        "evidence": tuple(row.evidence_id for row in db.query(ResearchEvidence).order_by(ResearchEvidence.evidence_id)),
    }
    return counts, ids


def test_research_persistence_uses_stable_uuid_ids_and_real_foreign_keys(
    postgres_database_factory, migration_fix_commit
):
    from backend.agent_runtime.models import AgentExecution
    from backend.models import TaskCenterTask
    from backend.research_runtime.models import ResearchClaim, ResearchEvidence, ResearchQuery, ResearchSource
    from backend.research_runtime.service import persist_research_result

    del migration_fix_commit
    database_url = postgres_database_factory("research_ids")
    alembic(ROOT, database_url, "upgrade", "head")
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as db:
        execution, task_id = make_agent_execution(db)
        execution_id = execution.execution_id
        input_payload, output_payload = research_payload(execution.execution_id)
        upstream_source_id = output_payload["sources"][0]["source_id"]
        upstream_evidence_id = output_payload["evidence"][0]["evidence_id"]
        persist_research_result(db, execution, input_payload, output_payload)
        db.commit()

    with SessionLocal() as db:
        before_counts, before_ids = research_counts_and_ids(db)
        assert all(before_counts)
        violations = []
        for values in before_ids.values():
            for value in values:
                assert len(value) <= 36
                assert str(uuid.UUID(value)) == value.lower(), f"ID必须是完整标准UUID，禁止字符串截断：{value}"
        assert upstream_source_id not in before_ids["source"]
        assert upstream_evidence_id not in before_ids["evidence"]
        for row in db.query(ResearchSource).filter(ResearchSource.execution_id == execution_id):
            query = db.get(ResearchQuery, row.query_id) if row.query_id else None
            if query is None or query.execution_id != execution_id:
                violations.append(f"Source未引用同Execution真实Query：{row.source_id}")
        for row in db.query(ResearchEvidence):
            source = db.get(ResearchSource, row.source_id)
            claim = db.get(ResearchClaim, row.claim_id) if row.claim_id else None
            if source is None or source.execution_id != execution_id:
                violations.append(f"Evidence未引用真实持久化Source：{row.evidence_id}")
            if row.claim_id is not None and (claim is None or claim.execution_id != execution_id):
                violations.append(f"Evidence未引用真实持久化Claim：{row.evidence_id}")
        first_summary = db.get(TaskCenterTask, task_id).summary

    with SessionLocal() as db:
        execution = db.get(AgentExecution, execution_id)
        persist_research_result(db, execution, input_payload, output_payload)
        db.commit()

    with SessionLocal() as db:
        after_counts, after_ids = research_counts_and_ids(db)
        if after_counts != before_counts or after_ids != before_ids:
            violations.append("重复persist改变正式记录数量或内部ID")
        task = db.get(TaskCenterTask, task_id)
        if task.summary != first_summary:
            violations.append("重复persist导致Task summary重复")
    engine.dispose()
    assert not violations, "；".join(violations)


def test_malicious_upstream_duplicate_source_id_is_mapped_to_internal_uuid(
    postgres_database_factory, migration_fix_commit
):
    from backend.research_runtime.models import ResearchSource
    from backend.research_runtime.service import persist_research_result

    del migration_fix_commit
    database_url = postgres_database_factory("research_duplicate_source")
    alembic(ROOT, database_url, "upgrade", "head")
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine)
    first_upstream_id = "恶意上游Source-A-" + ("A" * 160)
    second_upstream_id = "恶意上游Source-B-" + ("B" * 160)
    with SessionLocal() as db:
        execution, _task_id = make_agent_execution(db)
        input_payload, output_payload = research_payload(execution.execution_id)
        first = dict(output_payload["sources"][0])
        first.update({"source_id": first_upstream_id, "url": "https://example.com/source-a", "redacted_url": "https://example.com/source-a"})
        second = dict(first)
        second.update(
            {
                "source_id": second_upstream_id,
                "url": "https://example.com/source-b",
                "redacted_url": "https://example.com/source-b",
                "duplicate_of_source_id": first_upstream_id,
            }
        )
        output_payload["sources"] = [first, second]
        output_payload["evidence"] = []
        persist_research_result(db, execution, input_payload, output_payload)
        db.commit()

    with SessionLocal() as db:
        sources = db.query(ResearchSource).order_by(ResearchSource.source_url).all()
        assert len(sources) == 2
        first_row, second_row = sources
        for row in sources:
            assert len(row.source_id) == 36 and str(uuid.UUID(row.source_id)) == row.source_id
            assert row.source_id not in {first_upstream_id, second_upstream_id}
        assert second_row.duplicate_of_source_id == first_row.source_id
        assert len(second_row.duplicate_of_source_id) == 36
        assert str(uuid.UUID(second_row.duplicate_of_source_id)) == second_row.duplicate_of_source_id
    engine.dispose()


def test_research_upsert_never_rebinds_rows_across_executions(
    postgres_database_factory, migration_fix_commit, monkeypatch
):
    from backend.agent_runtime.models import AgentExecution
    from backend.models import TaskCenterTask
    from backend.research_runtime.models import ResearchQuery, ResearchSource
    from backend.research_runtime.exceptions import ResearchPersistenceError
    from backend.research_runtime import service as research_service
    from backend.research_runtime.service import persist_research_result

    del migration_fix_commit
    database_url = postgres_database_factory("research_execution_scope")
    alembic(ROOT, database_url, "upgrade", "head")
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as db:
        first_execution, first_task_id = make_agent_execution(db)
        first_execution_id = first_execution.execution_id
        input_payload, output_payload = research_payload(first_execution_id)
        output_payload["evidence"] = []
        persist_research_result(db, first_execution, input_payload, output_payload)
        db.commit()

    with SessionLocal() as db:
        first_execution = db.get(AgentExecution, first_execution_id)
        persist_research_result(db, first_execution, input_payload, output_payload)
        db.commit()
        second_execution, _second_task_id = make_agent_execution(db)
        second_execution_id = second_execution.execution_id
        persist_research_result(db, second_execution, input_payload, output_payload)
        db.commit()

    with SessionLocal() as db:
        forced_query_id = db.query(ResearchQuery.query_id).filter(ResearchQuery.execution_id == first_execution_id).order_by(ResearchQuery.query_id).first()[0]
        third_execution, _third_task_id = make_agent_execution(db)
        third_execution_id = third_execution.execution_id
        original_stable_id = research_service.stable_research_id

        def collide_with_first_execution(execution_id, resource_type, *components):
            if resource_type == "query":
                return forced_query_id
            return original_stable_id(execution_id, resource_type, *components)

        monkeypatch.setattr(research_service, "stable_research_id", collide_with_first_execution)
        with pytest.raises(ResearchPersistenceError, match="归属冲突"):
            persist_research_result(db, third_execution, input_payload, output_payload)
        db.rollback()

    violations = []
    with SessionLocal() as db:
        first_ids = {row.query_id for row in db.query(ResearchQuery).filter(ResearchQuery.execution_id == first_execution_id)}
        second_ids = {row.query_id for row in db.query(ResearchQuery).filter(ResearchQuery.execution_id == second_execution_id)}
        if not first_ids or not second_ids or first_ids & second_ids:
            violations.append("不同Execution的内部Query ID未保持隔离")
        if db.get(ResearchQuery, forced_query_id).execution_id != first_execution_id:
            violations.append("跨Execution冲突改绑了既有Query")
        if db.query(ResearchQuery).filter(ResearchQuery.execution_id == third_execution_id).count() != 0:
            violations.append("跨Execution Upsert拒绝后仍产生第三套Query")
        for source in db.query(ResearchSource):
            query = db.get(ResearchQuery, source.query_id) if source.query_id else None
            if query is None or query.execution_id != source.execution_id:
                violations.append(f"Source未引用同Execution真实Query：{source.source_id}")
        summary = db.get(TaskCenterTask, first_task_id).summary or ""
        if summary.count("[V2 Research]") != 1:
            violations.append(f"重复persist导致Task summary重复：{summary.count('[V2 Research]')}次")
    engine.dispose()
    assert not violations, "；".join(violations)


@pytest.mark.parametrize("failure_point", ["claim_failure", "evidence_fk", "flush_failure", "commit_failure"])
def test_research_persistence_failures_leave_one_recoverable_run_without_false_formal_data(
    postgres_alpha_runtime, failure_point
):
    from backend.agent_runtime.models import AgentExecution, AgentExecutionAudit
    from backend.alpha_workflow.models import AlphaWorkflowEvent, AlphaWorkflowRun
    from backend.knowledge_center.models import KnowledgeAsset, KnowledgeVersion
    from backend.models import TaskCenterAuditLog, TaskCenterResult, TaskCenterTask
    from backend.research_runtime.models import ResearchClaim, ResearchEvidence, ResearchExecution, ResearchQuery, ResearchSource
    from backend.skills_engine.models import SkillInvocation

    client, boss_headers, test_db = postgres_alpha_runtime
    fired = False
    evidence_flush_completed = False

    def inject_real_postgresql_failure(session, _flush_context, _instances):
        nonlocal fired
        if fired:
            return
        new_rows = list(session.new)
        queries = [row for row in new_rows if isinstance(row, ResearchQuery)]
        claims = [row for row in new_rows if isinstance(row, ResearchClaim)]
        evidence_rows = [row for row in new_rows if isinstance(row, ResearchEvidence)]
        if failure_point == "claim_failure" and claims:
            claims[0].claim_id = "超长Claim内部ID" + ("X" * 80)
            fired = True
        elif failure_point == "flush_failure" and len(queries) >= 2:
            duplicate_id = str(uuid.uuid4())
            queries[0].query_id = duplicate_id
            queries[1].query_id = duplicate_id
            fired = True
        elif failure_point in {"evidence_fk", "commit_failure"} and evidence_rows:
            evidence_rows[0].source_id = str(uuid.uuid4())
            fired = True

    def observe_evidence_flush(session, _flush_context):
        nonlocal evidence_flush_completed
        if failure_point == "commit_failure" and any(isinstance(row, ResearchEvidence) for row in session.identity_map.values()):
            evidence_flush_completed = True

    with test_db() as db:
        baseline_formal_counts, _ = research_counts_and_ids(db)
        baseline_report_count = db.query(ResearchExecution).count()
        baseline_run_count = db.query(AlphaWorkflowRun).count()
        baseline_event_count = db.query(AlphaWorkflowEvent).count()
        baseline_task_count = db.query(TaskCenterTask).count()
        baseline_agent_count = db.query(AgentExecution).count()
        baseline_knowledge_asset_count = db.query(KnowledgeAsset).count()
        baseline_knowledge_version_count = db.query(KnowledgeVersion).count()
        baseline_skill_invocation_count = db.query(SkillInvocation).count()
        baseline_task_result_count = db.query(TaskCenterResult).count()

    trace_id = f"research-failure-{failure_point}-{uuid.uuid4()}"
    captured_errors = []

    def capture_database_error(exception_context):
        captured_errors.append(exception_context.sqlalchemy_exception)

    engine = test_db.kw["bind"]
    if failure_point == "commit_failure":
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE research_evidence ALTER CONSTRAINT research_evidence_source_id_fkey DEFERRABLE INITIALLY DEFERRED"
            )
    event.listen(Session, "before_flush", inject_real_postgresql_failure)
    event.listen(Session, "after_flush", observe_evidence_flush)
    event.listen(engine, "handle_error", capture_database_error)
    api_exception = None
    first = None
    try:
        try:
            first = client.post(
                "/api/v2/alpha-workflows/demo",
                headers=boss_headers,
                json={"input_text": "Research持久化故障注入", "trace_id": trace_id},
            )
        except Exception as exc:
            api_exception = exc
    finally:
        event.remove(Session, "before_flush", inject_real_postgresql_failure)
        event.remove(Session, "after_flush", observe_evidence_flush)
        event.remove(engine, "handle_error", capture_database_error)
    assert fired, f"{failure_point}未由真实PostgreSQL flush路径触发"
    if failure_point == "commit_failure":
        assert evidence_flush_completed, "最终commit故障在Evidence flush完成前提前触发"
    expected_error = DataError if failure_point == "claim_failure" else IntegrityError
    assert any(isinstance(exc, expected_error) for exc in captured_errors), captured_errors
    expected_pgcode = {"evidence_fk": "23503", "flush_failure": "23505", "commit_failure": "23503"}.get(failure_point)
    if expected_pgcode:
        assert any(getattr(getattr(exc, "orig", None), "pgcode", None) == expected_pgcode for exc in captured_errors)
    violations = []
    if isinstance(api_exception, PendingRollbackError):
        violations.append("PendingRollbackError穿透API")
    elif api_exception is not None:
        violations.append(f"数据库故障异常穿透API：{type(api_exception).__name__}")
    if first is not None and first.status_code not in {200, 400}:
        violations.append(f"数据库故障返回异常HTTP状态：{first.status_code}")
    response_text = first.text if first is not None else str(api_exception or "")
    if re.search(r"DataError|IntegrityError|PendingRollback|sqlalchemy|psycopg|duplicate key|foreign key", response_text, re.I):
        violations.append(f"API泄漏英文数据库异常：{response_text}")

    with test_db() as db:
        runs = db.query(AlphaWorkflowRun).filter(AlphaWorkflowRun.trace_id == trace_id).all()
        if len(runs) != 1:
            violations.append("同一trace未严格保留一条Run")
            run_row = runs[0] if runs else None
        else:
            run_row = runs[0]
        if run_row is None:
            pytest.fail("真实数据库故障后未保留可恢复Run")
        run = {"run_id": run_row.run_id, "status": run_row.status, "recovery_status": run_row.recovery_status, "failure_reason": run_row.failure_reason}
        if run_row.status not in {"已失败", "失败"}:
            violations.append(f"Run留下非明确失败状态：{run_row.status}")
        if run_row.recovery_status != "待恢复":
            violations.append(f"Run未进入可恢复状态：{run_row.recovery_status}")
        formal_counts, _ = research_counts_and_ids(db)
        if formal_counts != baseline_formal_counts:
            violations.append(
                f"故障后正式Research数据数量变化：baseline={baseline_formal_counts}, actual={formal_counts}"
            )
        if db.query(ResearchExecution).count() != baseline_report_count:
            violations.append("故障后产生虚假Research报告记录")
        if db.query(KnowledgeAsset).count() != baseline_knowledge_asset_count:
            violations.append("故障后产生虚假Knowledge Asset")
        if db.query(KnowledgeVersion).count() != baseline_knowledge_version_count:
            violations.append("故障后产生虚假Knowledge Version")
        if db.query(SkillInvocation).count() != baseline_skill_invocation_count:
            violations.append("故障后产生虚假Skill Invocation")
        if db.query(TaskCenterResult).count() != baseline_task_result_count:
            violations.append("故障后产生虚假Task Result")
        task = db.get(TaskCenterTask, run_row.task_id) if run_row.task_id else None
        if task is None or task.status not in {"rejected", "failed"}:
            violations.append(f"Task未补偿为失败状态：{None if task is None else task.status}")
        agent = db.query(AgentExecution).filter(AgentExecution.trace_id == trace_id).one_or_none()
        if agent is None or agent.status not in {"failed", "已失败"}:
            violations.append(f"AgentExecution未补偿为失败状态：{None if agent is None else agent.status}")
        events = db.query(AlphaWorkflowEvent).filter(AlphaWorkflowEvent.trace_id == trace_id).all()
        success_events = [row for row in events if row.event_code in {"research_executed", "workflow_completed"}]
        failure_events = [row for row in events if row.event_code == "workflow_failed"]
        if len(failure_events) != 1:
            violations.append(f"workflow_failed Event数量错误：{len(failure_events)}")
        task_fail_audits = db.query(TaskCenterAuditLog).filter(
            TaskCenterAuditLog.task_id == run_row.task_id,
            TaskCenterAuditLog.action == "alpha_workflow_failed",
        ).count()
        if task_fail_audits != 1:
            violations.append(f"Task失败审计数量错误：{task_fail_audits}")
        agent_fail_audits = 0 if agent is None else db.query(AgentExecutionAudit).filter(
            AgentExecutionAudit.execution_id == agent.execution_id,
            AgentExecutionAudit.event_type == "execution_failed",
        ).count()
        if agent_fail_audits != 1:
            violations.append(f"AgentExecution失败审计数量错误：{agent_fail_audits}")
        if any(
            re.search(r"DataError|IntegrityError|PendingRollback|sqlalchemy|psycopg|duplicate key|foreign key", value or "", re.I)
            for value in [run_row.failure_reason, agent.error_message if agent else None, *(row.message for row in failure_events)]
        ):
            violations.append("Run/Agent/Event持久化字段泄漏英文数据库异常")
        success_events = db.query(AlphaWorkflowEvent).filter(
            AlphaWorkflowEvent.trace_id == trace_id,
            AlphaWorkflowEvent.event_code.in_(["research_executed", "workflow_completed"]),
        ).all()
        if success_events:
            violations.append(
                "故障后产生虚假成功Event：" + ",".join(row.event_code for row in success_events)
            )
        run_count = db.query(AlphaWorkflowRun).count()
        event_count = db.query(AlphaWorkflowEvent).count()

    replay = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "Research持久化故障注入", "trace_id": trace_id},
    )
    if replay.status_code != 200:
        violations.append(f"同trace重放未返回200：{replay.status_code}")
    elif replay.json()["run"]["run_id"] != run["run_id"]:
        violations.append("同trace重放创建了第二条Run")
    with test_db() as db:
        if db.query(AlphaWorkflowRun).count() != run_count:
            violations.append("同trace重放增加了Run数量")
        if db.query(AlphaWorkflowEvent).count() != event_count:
            violations.append("同trace重放增加了Event数量")
        replay_formal_counts, _ = research_counts_and_ids(db)
        if replay_formal_counts != baseline_formal_counts:
            violations.append(
                f"同trace重放改变正式Research数据数量：baseline={baseline_formal_counts}, actual={replay_formal_counts}"
            )
        if db.query(AlphaWorkflowRun).count() != baseline_run_count + 1:
            violations.append("故障与重放后Run总数不是基线加一")
        if db.query(TaskCenterTask).count() != baseline_task_count + 1:
            violations.append("故障与重放后Task总数不是基线加一")
        if db.query(AgentExecution).count() != baseline_agent_count + 1:
            violations.append("故障与重放后AgentExecution总数不是基线加一")
        if db.query(KnowledgeAsset).count() != baseline_knowledge_asset_count:
            violations.append("同trace重放增加了Knowledge Asset")
        if db.query(KnowledgeVersion).count() != baseline_knowledge_version_count:
            violations.append("同trace重放增加了Knowledge Version")
        if db.query(SkillInvocation).count() != baseline_skill_invocation_count:
            violations.append("同trace重放增加了Skill Invocation")
        if db.query(TaskCenterResult).count() != baseline_task_result_count:
            violations.append("同trace重放增加了Task Result")
        if db.query(AlphaWorkflowEvent).count() < baseline_event_count:
            violations.append("故障处理异常删除了既有Event")

    failure_reason = run.get("failure_reason") or ""
    if re.search(r"database|dataerror|integrityerror|pendingrollback|sqlalchemy|psycopg|sqlstate", failure_reason, re.I):
        violations.append(f"向用户暴露英文数据库异常：{failure_reason}")
    assert not violations, "；".join(violations)
