from __future__ import annotations

import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


FINAL_REVISION = "0053_r297_jd_workbench_hash_uniqueness"


def _alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _seed_scope(connection) -> tuple[int, int, int]:
    tenant_id, company_id = connection.execute(text(
        "SELECT t.id, c.id FROM tenants t JOIN companies c ON c.tenant_id = t.id "
        "ORDER BY t.id LIMIT 1"
    )).one()
    user_id = connection.execute(text(
        "INSERT INTO users "
        "(username, password_hash, role, display_name, tenant_id, company_id, active) "
        "VALUES ('r297-hash-migration', 'not-a-secret', 'owner', 'R297', :tenant, :company, true) "
        "RETURNING id"
    ), {"tenant": tenant_id, "company": company_id}).scalar_one()
    return tenant_id, company_id, user_id


def test_hash_uniqueness_migration_roundtrip_and_postgresql_behavior(postgres_database_factory):
    database_url = postgres_database_factory("r297_hash_unique")
    assert _alembic(database_url, "upgrade", "head").returncode == 0
    checked = _alembic(database_url, "check")
    assert checked.returncode == 0, checked.stderr[-2000:]

    engine = create_engine(database_url)
    with engine.begin() as connection:
        inspector = inspect(connection)
        assert {item["name"] for item in inspector.get_unique_constraints("jd_workbench_devices")} >= {
            "uq_jd_workbench_devices_token_hash"
        }
        assert {item["name"] for item in inspector.get_unique_constraints("jd_workbench_pairing_codes")} >= {
            "uq_jd_workbench_pairing_codes_code_hash"
        }
        tenant_id, company_id, user_id = _seed_scope(connection)
        device_values = {
            "tenant": tenant_id, "company": company_id, "user": user_id,
            "expires": "2030-01-01T00:00:00+00:00",
        }
        connection.execute(text(
            "INSERT INTO jd_workbench_devices "
            "(device_id, token_hash, public_key_n, public_key_e, tenant_id, company_id, user_id, "
            "device_name, client_version, status, expires_at) VALUES "
            "('r297-device-1', :hash, 'n', 65537, :tenant, :company, :user, 'one', 'r297', 'PAIRED', :expires)"
        ), {**device_values, "hash": "a" * 64})
        connection.execute(text(
            "INSERT INTO jd_workbench_pairing_codes "
            "(pairing_id, code_hash, tenant_id, company_id, user_id, expires_at) VALUES "
            "('r297-pairing-1', :hash, :tenant, :company, :user, :expires)"
        ), {**device_values, "hash": "b" * 64})

    for statement, values in (
        (
            "INSERT INTO jd_workbench_devices "
            "(device_id, token_hash, public_key_n, public_key_e, tenant_id, company_id, user_id, "
            "device_name, client_version, status, expires_at) VALUES "
            "('r297-device-2', :hash, 'n', 65537, :tenant, :company, :user, 'two', 'r297', 'PAIRED', :expires)",
            {**device_values, "hash": "a" * 64},
        ),
        (
            "INSERT INTO jd_workbench_pairing_codes "
            "(pairing_id, code_hash, tenant_id, company_id, user_id, expires_at) VALUES "
            "('r297-pairing-2', :hash, :tenant, :company, :user, :expires)",
            {**device_values, "hash": "b" * 64},
        ),
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text(statement), values)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO jd_workbench_pairing_codes "
            "(pairing_id, code_hash, tenant_id, company_id, user_id, expires_at) VALUES "
            "('r297-pairing-null', NULL, :tenant, :company, :user, :expires)"
        ), device_values)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO jd_workbench_devices "
            "(device_id, token_hash, public_key_n, public_key_e, tenant_id, company_id, user_id, "
            "device_name, client_version, status, expires_at) VALUES "
            "('r297-device-null', NULL, 'n', 65537, :tenant, :company, :user, 'null', 'r297', "
            "'PAIRED', :expires)"
        ), device_values)

    assert _alembic(database_url, "downgrade", "0052_r297_postgresql_queue_authority").returncode == 0
    assert _alembic(database_url, "upgrade", "head").returncode == 0
    rechecked = _alembic(database_url, "check")
    assert rechecked.returncode == 0, rechecked.stderr[-2000:]
    current = _alembic(database_url, "current")
    assert current.returncode == 0 and FINAL_REVISION in current.stdout
    engine.dispose()


@pytest.mark.parametrize("target", ("pairing", "device"))
def test_hash_uniqueness_migration_rejects_historical_duplicates(postgres_database_factory, target):
    database_url = postgres_database_factory(f"r297_hash_duplicate_{target}")
    assert _alembic(database_url, "upgrade", "0052_r297_postgresql_queue_authority").returncode == 0
    engine = create_engine(database_url)
    with engine.begin() as connection:
        tenant_id, company_id, user_id = _seed_scope(connection)
        values = {"hash": "c" * 64, "tenant": tenant_id, "company": company_id, "user": user_id}
        if target == "pairing":
            connection.execute(text(
                "ALTER TABLE jd_workbench_pairing_codes "
                "DROP CONSTRAINT jd_workbench_pairing_codes_code_hash_key"
            ))
            connection.execute(text(
                "INSERT INTO jd_workbench_pairing_codes "
                "(pairing_id, code_hash, tenant_id, company_id, user_id, expires_at) VALUES "
                "('r297-duplicate-1', :hash, :tenant, :company, :user, now() + interval '1 hour'), "
                "('r297-duplicate-2', :hash, :tenant, :company, :user, now() + interval '1 hour')"
            ), values)
            expected_error = "R297_DUPLICATE_PAIRING_CODE_HASH"
        else:
            connection.execute(text(
                "ALTER TABLE jd_workbench_devices DROP CONSTRAINT jd_workbench_devices_token_hash_key"
            ))
            connection.execute(text(
                "INSERT INTO jd_workbench_devices "
                "(device_id, token_hash, public_key_n, public_key_e, tenant_id, company_id, user_id, "
                "device_name, client_version, status, expires_at) VALUES "
                "('r297-duplicate-1', :hash, 'n', 65537, :tenant, :company, :user, 'one', 'r297', "
                "'PAIRED', now() + interval '1 hour'), "
                "('r297-duplicate-2', :hash, 'n', 65537, :tenant, :company, :user, 'two', 'r297', "
                "'PAIRED', now() + interval '1 hour')"
            ), values)
            expected_error = "R297_DUPLICATE_DEVICE_TOKEN_HASH"
    upgraded = _alembic(database_url, "upgrade", "head")
    assert upgraded.returncode != 0
    assert expected_error in upgraded.stderr
    engine.dispose()
