from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import os
from threading import Barrier, BrokenBarrierError
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import psycopg2
import pytest
from psycopg2 import sql
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Permission
from backend.seed import (
    PERMISSIONS,
    SEED_ADVISORY_LOCK_KEY,
    _acquire_seed_lock,
    seed_defaults,
)

POSTGRES_ADMIN_URL_ENV = "V2_ALPHA_POSTGRES_ADMIN_URL"
CONCURRENT_TEST_ROUNDS = 5
CONCURRENT_EXECUTOR_TIMEOUT_SECONDS = 45


def _session_factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _run_seed(monkeypatch, session):
    monkeypatch.setattr(
        "backend.seed.get_settings",
        lambda: SimpleNamespace(BOSS_INITIAL_PASSWORD="seed-test-password"),
    )
    monkeypatch.setattr("backend.seed.ensure_default_skills", lambda *args, **kwargs: None)
    monkeypatch.setattr("backend.seed.resolve_manager_user", lambda db: None)
    seed_defaults(session)


@pytest.fixture
def postgres_seed_database_factory():
    raw_admin_url = os.getenv(POSTGRES_ADMIN_URL_ENV)
    assert raw_admin_url, (
        f"真实PostgreSQL并发测试要求设置 {POSTGRES_ADMIN_URL_ENV}"
    )
    admin_url = make_url(raw_admin_url)
    assert admin_url.get_backend_name() == "postgresql", (
        "菜单种子并发测试禁止SQLite或Mock数据库"
    )
    admin_dsn = (
        admin_url.set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )
    created: list[str] = []

    def create_database(round_number: int) -> str:
        database_name = (
            f"s12_seed_concurrency_r{round_number}_{uuid.uuid4().hex[:12]}"
        )
        connection = psycopg2.connect(admin_dsn)
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(database_name)
                    )
                )
        finally:
            connection.close()
        created.append(database_name)
        return admin_url.set(database=database_name).render_as_string(
            hide_password=False
        )

    yield create_database

    connection = psycopg2.connect(admin_dsn)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            for database_name in created:
                cursor.execute(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = %s AND pid <> pg_backend_pid()
                    """,
                    (database_name,),
                )
                cursor.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(
                        sql.Identifier(database_name)
                    )
                )
    finally:
        connection.close()


def test_permission_seed_codes_are_unique():
    codes = [code for code, _ in PERMISSIONS]
    assert len(codes) == len(set(codes))


def test_seed_defaults_initializes_empty_permission_table(monkeypatch):
    Session = _session_factory()
    with Session() as db:
        _run_seed(monkeypatch, db)

        assert (
            db.query(Permission)
            .filter(Permission.code == "menu.computer_executor")
            .count()
            == 1
        )


def test_seed_defaults_is_idempotent_with_existing_permission(monkeypatch):
    Session = _session_factory()
    with Session() as db:
        db.add(Permission(code="menu.computer_executor", name="existing"))
        db.commit()

        _run_seed(monkeypatch, db)
        _run_seed(monkeypatch, db)

        assert (
            db.query(Permission)
            .filter(Permission.code == "menu.computer_executor")
            .count()
            == 1
        )


def test_postgresql_seed_uses_transaction_advisory_lock():
    db = Mock()
    db.get_bind.return_value.dialect.name = "postgresql"

    _acquire_seed_lock(db)

    statement, parameters = db.execute.call_args.args
    assert str(statement) == "SELECT pg_advisory_xact_lock(:lock_key)"
    assert parameters == {"lock_key": SEED_ADVISORY_LOCK_KEY}


def test_seed_defaults_serializes_two_real_postgresql_transactions(
    monkeypatch,
    postgres_seed_database_factory,
):
    monkeypatch.setattr(
        "backend.seed.get_settings",
        lambda: SimpleNamespace(BOSS_INITIAL_PASSWORD="seed-test-password"),
    )
    monkeypatch.setattr(
        "backend.seed.ensure_default_skills",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("backend.seed.resolve_manager_user", lambda db: None)

    deadlocks = []
    timeouts = []
    duplicate_key_errors = []
    unhandled_exceptions = []

    for round_number in range(1, CONCURRENT_TEST_ROUNDS + 1):
        database_url = postgres_seed_database_factory(round_number)
        setup_engine = create_engine(database_url, pool_pre_ping=True)
        Base.metadata.create_all(setup_engine)
        start_barrier = Barrier(2)

        def initialize_in_independent_transaction():
            worker_engine = create_engine(
                database_url,
                pool_pre_ping=True,
                connect_args={
                    "options": "-c lock_timeout=10000 -c statement_timeout=30000"
                },
            )
            WorkerSession = sessionmaker(
                bind=worker_engine,
                autoflush=False,
                autocommit=False,
            )
            try:
                with WorkerSession() as db:
                    db.begin()
                    start_barrier.wait(timeout=10)
                    seed_defaults(db)
            except Exception as error:  # returned to the coordinating test thread
                return error
            finally:
                worker_engine.dispose()
            return None

        executor = ThreadPoolExecutor(max_workers=2)
        futures = [
            executor.submit(initialize_in_independent_transaction)
            for _ in range(2)
        ]
        try:
            results = [
                future.result(timeout=CONCURRENT_EXECUTOR_TIMEOUT_SECONDS)
                for future in futures
            ]
        except FutureTimeoutError as error:
            timeouts.append(error)
            results = []
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

        for error in (item for item in results if item is not None):
            pgcode = (
                getattr(error.orig, "pgcode", None)
                if isinstance(error, DBAPIError)
                else None
            )
            if pgcode == "40P01":
                deadlocks.append(error)
            elif pgcode in {"55P03", "57014"} or isinstance(
                error, BrokenBarrierError
            ):
                timeouts.append(error)
            elif pgcode == "23505" or isinstance(error, IntegrityError):
                duplicate_key_errors.append(error)
            else:
                unhandled_exceptions.append(error)

        with setup_engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
            menu_count = connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM permissions
                    WHERE code = 'menu.computer_executor'
                    """
                )
            )
            role_menu_duplicate_count = connection.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM (
                        SELECT rp.role_id, rp.permission_id
                        FROM role_permissions AS rp
                        JOIN permissions AS p ON p.id = rp.permission_id
                        WHERE p.code = 'menu.computer_executor'
                        GROUP BY rp.role_id, rp.permission_id
                        HAVING count(*) > 1
                    ) AS duplicate_role_menu
                    """
                )
            )
        setup_engine.dispose()

        assert len(results) == 2
        assert menu_count == 1
        assert role_menu_duplicate_count == 0

    assert deadlocks == []
    assert timeouts == []
    assert duplicate_key_errors == []
    assert unhandled_exceptions == []
