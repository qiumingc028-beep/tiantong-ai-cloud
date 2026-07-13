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
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine


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


def test_final_head_unique_constraints_reject_duplicates_and_keep_idempotency_after_reupgrade(
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

    alembic(ROOT, database_url, "downgrade", "0039_v2_alpha_workflow_unified_contract")
    alembic(ROOT, database_url, "upgrade", "head")
    with psycopg2.connect(dsn) as connection:
        assert_expected_constraints(connection)
        assert "uq_alpha_workflow_runs_knowledge_asset_id" not in constraint_columns(connection), "knowledge_asset_id必须允许跨Run复用"
        shared_knowledge = str(uuid.uuid4())
        first = run_values(uuid.uuid4().hex)
        second = run_values(uuid.uuid4().hex)
        first["knowledge_asset_id"] = shared_knowledge
        second["knowledge_asset_id"] = shared_knowledge
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
    client, boss_headers, alpha_enabled, test_db
):
    from backend.alpha_workflow.models import AlphaWorkflowEvent, AlphaWorkflowRun

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


@pytest.mark.parametrize("constraint_name", sorted(EXPECTED_UNIQUES))
def test_other_run_unique_conflicts_map_to_chinese_409(
    client, boss_headers, alpha_enabled, monkeypatch, constraint_name
):
    from backend.routers import alpha_workflow as router

    occupied = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "先创建占用身份的Run", "trace_id": f"occupied-{uuid.uuid4()}"},
    )
    assert occupied.status_code == 200

    def conflict(*_args, **_kwargs):
        raise IntegrityError(
            "INSERT alpha_workflow_runs",
            {},
            Exception(f'duplicate key violates unique constraint "{constraint_name}"'),
        )

    monkeypatch.setattr(router, "start_alpha_workflow", conflict)
    response = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "唯一字段已被另一Run占用", "trace_id": f"conflict-{uuid.uuid4()}"},
    )
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
        assert not (set(constraints) & set(indexes)), "downgrade后存在同名索引/约束冲突"
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
        capability_id=capability.capability_id,
        status="completed",
        risk_level="low",
        approval_status="not_required",
        executor_type="research",
        trace_id=f"research-trace-{uuid.uuid4()}",
    )
    db.add_all([capability, execution])
    db.commit()
    return execution


def research_payload(execution_id: str):
    source_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{execution_id}:source:1"))
    evidence_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{execution_id}:evidence:1"))
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
    from backend.research_runtime.models import ResearchClaim, ResearchEvidence, ResearchSource
    from backend.research_runtime.service import persist_research_result

    del migration_fix_commit
    database_url = postgres_database_factory("research_ids")
    alembic(ROOT, database_url, "upgrade", "head")
    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as db:
        execution = make_agent_execution(db)
        input_payload, output_payload = research_payload(execution.execution_id)
        persist_research_result(db, execution, input_payload, output_payload)
        before_counts, before_ids = research_counts_and_ids(db)
        assert all(before_counts)
        for values in before_ids.values():
            for value in values:
                assert len(value) <= 36
                assert str(uuid.UUID(value)) == value.lower(), f"ID必须是完整标准UUID，禁止字符串截断：{value}"
        for row in db.query(ResearchEvidence):
            assert db.get(ResearchSource, row.source_id) is not None
            assert row.claim_id is None or db.get(ResearchClaim, row.claim_id) is not None

        persist_research_result(db, execution, input_payload, output_payload)
        after_counts, after_ids = research_counts_and_ids(db)
        assert after_counts == before_counts
        assert after_ids == before_ids
    engine.dispose()


@pytest.mark.parametrize("failure_point", ["claim_insert", "evidence_insert", "research_commit"])
def test_research_persistence_failures_leave_one_recoverable_run_without_false_formal_data(
    client, boss_headers, alpha_enabled, test_db, monkeypatch, failure_point
):
    from backend.alpha_workflow.models import AlphaWorkflowEvent, AlphaWorkflowRun
    from backend.research_runtime.models import ResearchClaim, ResearchEvidence, ResearchExecution, ResearchQuery, ResearchSource

    original_add = Session.add
    original_commit = Session.commit
    fired = False

    def guarded_add(session, instance, *args, **kwargs):
        nonlocal fired
        if not fired and ((failure_point == "claim_insert" and isinstance(instance, ResearchClaim)) or (failure_point == "evidence_insert" and isinstance(instance, ResearchEvidence))):
            fired = True
            raise RuntimeError("database persistence failure")
        return original_add(session, instance, *args, **kwargs)

    def guarded_commit(session, *args, **kwargs):
        nonlocal fired
        has_research = any(isinstance(row, ResearchExecution) for row in list(session.new) + list(session.identity_map.values()))
        if not fired and failure_point == "research_commit" and has_research:
            fired = True
            raise RuntimeError("database research commit failure")
        return original_commit(session, *args, **kwargs)

    monkeypatch.setattr(Session, "add", guarded_add)
    monkeypatch.setattr(Session, "commit", guarded_commit)
    with test_db() as db:
        baseline_formal_counts, _ = research_counts_and_ids(db)
        baseline_run_count = db.query(AlphaWorkflowRun).count()
        baseline_event_count = db.query(AlphaWorkflowEvent).count()

    trace_id = f"research-failure-{failure_point}-{uuid.uuid4()}"
    first = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "Research持久化故障注入", "trace_id": trace_id},
    )
    assert first.status_code == 200
    run = first.json()["run"]
    violations = []
    if run["status"] not in {"已失败", "失败"}:
        violations.append(f"Run留下非明确失败状态：{run['status']}")
    if run["recovery_status"] != "待恢复":
        violations.append(f"Run未进入可恢复状态：{run['recovery_status']}")

    with test_db() as db:
        if db.query(AlphaWorkflowRun).filter(AlphaWorkflowRun.trace_id == trace_id).count() != 1:
            violations.append("同一trace未严格保留一条Run")
        formal_counts, _ = research_counts_and_ids(db)
        if formal_counts != baseline_formal_counts:
            violations.append(
                f"故障后正式Research数据数量变化：baseline={baseline_formal_counts}, actual={formal_counts}"
            )
        if db.query(ResearchExecution).count() != 0:
            violations.append("故障后产生虚假Research报告记录")
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
        if db.query(AlphaWorkflowEvent).count() < baseline_event_count:
            violations.append("故障处理异常删除了既有Event")

    failure_reason = run.get("failure_reason") or ""
    if re.search(r"database|integrityerror|sqlalchemy|psycopg|sqlstate", failure_reason, re.I):
        violations.append(f"向用户暴露英文数据库异常：{failure_reason}")
    assert not violations, "；".join(violations)
