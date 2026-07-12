"""PostgreSQL-only historical migration and uniqueness regression tests.

These tests create disposable databases and execute Alembic.  They never use
SQLite and never permit a drift-skip environment variable.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
FIX_COMMIT_ENV = "MIGRATION_CODE_FIX_COMMIT"
ADMIN_URL_ENV = "V2_ALPHA_POSTGRES_ADMIN_URL"
DEVELOP_REF = "origin/develop-v2"
FINAL_REVISION = "0041_v2_alpha_migration_history_repair"
EXPECTED_UNIQUES = {
    "uq_alpha_workflow_runs_trace_id": ("trace_id",),
    "uq_alpha_workflow_runs_root_span_id": ("root_span_id",),
    "uq_alpha_workflow_runs_workflow_id": ("workflow_id",),
    "uq_alpha_workflow_runs_orchestrator_run_id": ("orchestrator_run_id",),
    "uq_alpha_workflow_runs_research_report_id": ("research_report_id",),
    "uq_alpha_workflow_runs_knowledge_asset_id": ("knowledge_asset_id",),
    "uq_alpha_workflow_runs_skill_invocation_id": ("skill_invocation_id",),
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True
    ).stdout.strip()


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
        with psycopg2.connect(admin_dsn) as connection:
            connection.autocommit = True
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        created.append(name)
        return admin_url.set(database=name).render_as_string(hide_password=False)

    yield create_database

    with psycopg2.connect(admin_dsn) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            for name in created:
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                    (name,),
                )
                cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))


@pytest.fixture(scope="module")
def migration_fix_commit():
    commit = os.getenv(FIX_COMMIT_ENV)
    assert commit, f"收到修复后必须设置 {FIX_COMMIT_ENV}"
    subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT, check=True)
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=ROOT
    ).returncode == 0, "MIGRATION_CODE_FIX_COMMIT尚未合并到测试分支"
    return commit


def extract_git_tree(commit: str, destination: Path) -> None:
    archive = subprocess.run(
        ["git", "archive", "--format=tar", commit], cwd=ROOT, check=True, capture_output=True
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        bundle.extractall(destination, filter="data")


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

    alembic(ROOT, database_url, "downgrade", "0039_v2_alpha_workflow_unified_contract")
    alembic(ROOT, database_url, "upgrade", "head")
    with psycopg2.connect(dsn) as connection:
        assert_expected_constraints(connection)
