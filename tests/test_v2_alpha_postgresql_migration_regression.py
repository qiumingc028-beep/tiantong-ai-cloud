"""PostgreSQL-only historical migration and uniqueness regression tests.

These tests create disposable databases and execute Alembic.  They never use
SQLite and never permit a drift-skip environment variable.
"""

from __future__ import annotations

import io
import importlib.util
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


ROOT = Path(__file__).resolve().parents[1]
FIX_COMMIT_ENV = "MIGRATION_CODE_FIX_COMMIT"
ADMIN_URL_ENV = "V2_ALPHA_POSTGRES_ADMIN_URL"
DEVELOP_REF = "origin/develop-v2"
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
    merge_base = git("merge-base", migration_fix_commit, DEVELOP_REF)
    historical_tree = tmp_path / "merge-base"
    historical_tree.mkdir()
    extract_git_tree(merge_base, historical_tree)

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
    assert FINAL_REVISION in current


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


def test_same_idempotency_key_returns_existing_run_without_new_rows(
    postgres_alpha_runtime,
):
    from backend.alpha_workflow.models import AlphaWorkflowEvent, AlphaWorkflowRun

    client, boss_headers, test_db = postgres_alpha_runtime
    payload = {"input_text": "验证409幂等语义", "trace_id": f"pg-contract-{uuid.uuid4()}"}
    first = client.post("/api/v2/alpha-workflows/demo", headers=boss_headers, json=payload)
    with test_db() as db:
        run_count = db.query(AlphaWorkflowRun).count()
        event_count = db.query(AlphaWorkflowEvent).count()
    second = client.post("/api/v2/alpha-workflows/demo", headers=boss_headers, json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["run"]["run_id"] == first.json()["run"]["run_id"]
    with test_db() as db:
        assert db.query(AlphaWorkflowRun).count() == run_count
        assert db.query(AlphaWorkflowEvent).count() == event_count


def test_concurrent_same_trace_replay_returns_one_run_without_duplicate_side_effects(
    postgres_alpha_runtime,
):
    from backend.agent_runtime.models import AgentExecution
    from backend.alpha_workflow.models import AlphaWorkflowEvent, AlphaWorkflowRun
    from backend.models import TaskCenterTask

    client, boss_headers, test_db = postgres_alpha_runtime
    payload = {"input_text": "验证并发幂等语义", "trace_id": f"pg-concurrent-{uuid.uuid4()}"}
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
        assert db.query(TaskCenterTask).filter(TaskCenterTask.id == run.task_id).count() == 1
        assert db.query(AgentExecution).filter(AgentExecution.trace_id == payload["trace_id"]).count() == 1
        event_ids = [row.event_id for row in db.query(AlphaWorkflowEvent).filter(AlphaWorkflowEvent.run_id == run.run_id)]
        assert len(event_ids) == len(set(event_ids))


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
    assert FINAL_REVISION in alembic(ROOT, database_url, "current").stdout


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


def test_research_upsert_never_rebinds_rows_across_executions(
    postgres_database_factory, migration_fix_commit
):
    from backend.agent_runtime.models import AgentExecution
    from backend.models import TaskCenterTask
    from backend.research_runtime.models import ResearchQuery, ResearchSource
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

    violations = []
    with SessionLocal() as db:
        first_ids = {row.query_id for row in db.query(ResearchQuery).filter(ResearchQuery.execution_id == first_execution_id)}
        second_ids = {row.query_id for row in db.query(ResearchQuery).filter(ResearchQuery.execution_id == second_execution_id)}
        if not first_ids or not second_ids or first_ids & second_ids:
            violations.append("不同Execution的内部Query ID未保持隔离")
        for source in db.query(ResearchSource):
            query = db.get(ResearchQuery, source.query_id) if source.query_id else None
            if query is None or query.execution_id != source.execution_id:
                violations.append(f"Source未引用同Execution真实Query：{source.source_id}")
        summary = db.get(TaskCenterTask, first_task_id).summary or ""
        if summary.count("[V2 Research]") != 1:
            violations.append(f"重复persist导致Task summary重复：{summary.count('[V2 Research]')}次")
    engine.dispose()
    assert not violations, "；".join(violations)


@pytest.mark.parametrize("failure_point", ["data_error", "foreign_key", "integrity_error"])
def test_research_persistence_failures_leave_one_recoverable_run_without_false_formal_data(
    postgres_alpha_runtime, failure_point
):
    from backend.agent_runtime.models import AgentExecution, AgentExecutionAudit
    from backend.alpha_workflow.models import AlphaWorkflowEvent, AlphaWorkflowRun
    from backend.models import TaskCenterAuditLog, TaskCenterTask
    from backend.research_runtime.models import ResearchClaim, ResearchEvidence, ResearchExecution, ResearchQuery, ResearchSource

    client, boss_headers, test_db = postgres_alpha_runtime
    fired = False

    def inject_real_postgresql_failure(session, _flush_context, _instances):
        nonlocal fired
        if fired:
            return
        new_rows = list(session.new)
        queries = [row for row in new_rows if isinstance(row, ResearchQuery)]
        evidence_rows = [row for row in new_rows if isinstance(row, ResearchEvidence)]
        if failure_point == "data_error" and queries:
            queries[0].query_id = "超长内部ID" + ("X" * 80)
            fired = True
        elif failure_point == "integrity_error" and len(queries) >= 2:
            duplicate_id = str(uuid.uuid4())
            queries[0].query_id = duplicate_id
            queries[1].query_id = duplicate_id
            fired = True
        elif failure_point == "foreign_key" and evidence_rows:
            evidence_rows[0].source_id = str(uuid.uuid4())
            fired = True

    with test_db() as db:
        baseline_formal_counts, _ = research_counts_and_ids(db)
        baseline_report_count = db.query(ResearchExecution).count()
        baseline_run_count = db.query(AlphaWorkflowRun).count()
        baseline_event_count = db.query(AlphaWorkflowEvent).count()
        baseline_task_count = db.query(TaskCenterTask).count()
        baseline_agent_count = db.query(AgentExecution).count()

    trace_id = f"research-failure-{failure_point}-{uuid.uuid4()}"
    captured_errors = []

    def capture_database_error(exception_context):
        captured_errors.append(exception_context.sqlalchemy_exception)

    engine = test_db.kw["bind"]
    event.listen(Session, "before_flush", inject_real_postgresql_failure)
    event.listen(engine, "handle_error", capture_database_error)
    try:
        first = client.post(
            "/api/v2/alpha-workflows/demo",
            headers=boss_headers,
            json={"input_text": "Research持久化故障注入", "trace_id": trace_id},
        )
    finally:
        event.remove(Session, "before_flush", inject_real_postgresql_failure)
        event.remove(engine, "handle_error", capture_database_error)
    assert fired, f"{failure_point}未由真实PostgreSQL flush路径触发"
    expected_error = DataError if failure_point == "data_error" else IntegrityError
    assert any(isinstance(exc, expected_error) for exc in captured_errors), captured_errors
    expected_pgcode = {"foreign_key": "23503", "integrity_error": "23505"}.get(failure_point)
    if expected_pgcode:
        assert any(getattr(getattr(exc, "orig", None), "pgcode", None) == expected_pgcode for exc in captured_errors)
    assert not any(isinstance(exc, PendingRollbackError) for exc in captured_errors)
    assert first.status_code in {200, 400}
    violations = []
    response_text = first.text
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
        if db.query(AlphaWorkflowEvent).count() < baseline_event_count:
            violations.append("故障处理异常删除了既有Event")

    failure_reason = run.get("failure_reason") or ""
    if re.search(r"database|dataerror|integrityerror|pendingrollback|sqlalchemy|psycopg|sqlstate", failure_reason, re.I):
        violations.append(f"向用户暴露英文数据库异常：{failure_reason}")
    assert not violations, "；".join(violations)
