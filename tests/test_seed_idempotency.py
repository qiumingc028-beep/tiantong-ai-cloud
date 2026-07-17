from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Permission
from backend.seed import (
    PERMISSIONS,
    SEED_ADVISORY_LOCK_KEY,
    _acquire_seed_lock,
    seed_defaults,
)


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
