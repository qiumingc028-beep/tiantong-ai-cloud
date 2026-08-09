from datetime import date
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

from backend.models import (
    Company,
    JdDailyMetric,
    MetricDaily,
    Store,
    Tenant,
    User,
    UserStoreMembership,
)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from backend.auth import hash_password


ROOT = Path(__file__).resolve().parents[1]


def test_0044_extends_existing_0043_head():
    migration = (
        ROOT / "alembic/versions/0044_tenant_company_store_authorization_scope.py"
    ).read_text()

    assert 'revision = "0044_tenant_company_store_authorization_scope"' in migration
    assert 'down_revision = "0043_ai_product_asset_upload"' in migration


def test_0044_postgresql_upgrade_backfill_and_safe_downgrade():
    database_url = os.getenv("STORE_AUTHZ_POSTGRES_URL")
    if not database_url:
        pytest.skip("requires an isolated local PostgreSQL database")

    admin_url = make_url(database_url)
    database_name = f"tiantong_authz_{uuid.uuid4().hex}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f"CREATE DATABASE {database_name}"))
    isolated_url = admin_url.set(database=database_name).render_as_string(hide_password=False)

    def alembic(*args, check=True):
        env = os.environ.copy()
        env["DATABASE_URL"] = isolated_url
        return subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=check,
        )

    engine = create_engine(isolated_url)
    try:
        alembic("upgrade", "0043_ai_product_asset_upload")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (username, password_hash, role, display_name, active) "
                    "VALUES ('legacy-owner', 'unused', 'owner', 'Legacy Owner', TRUE), "
                    "('legacy-manager', 'unused', 'operator', 'Legacy Manager', TRUE)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO stores (platform, store_code, store_name, manager_user_id, active) "
                    "SELECT 'jd', 'LEGACY', 'Legacy Store', id, TRUE FROM users "
                    "WHERE username = 'legacy-manager'"
                )
            )

        alembic("upgrade", "head")
        with engine.begin() as connection:
            scope = connection.execute(
                text(
                    "SELECT users.tenant_id, users.company_id, stores.tenant_id, stores.company_id "
                    "FROM users CROSS JOIN stores WHERE users.username = 'legacy-owner' "
                    "AND stores.store_code = 'LEGACY'"
                )
            ).one()
            assert all(scope)
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM user_store_memberships memberships "
                    "JOIN users ON users.id = memberships.user_id "
                    "JOIN stores ON stores.id = memberships.store_id "
                    "WHERE users.username IN ('legacy-owner', 'legacy-manager') "
                    "AND stores.store_code = 'LEGACY' "
                    "AND memberships.can_read AND memberships.can_write AND memberships.active"
                )
            ).scalar_one() == 2
            connection.execute(text("INSERT INTO tenants (tenant_code, tenant_name, active) VALUES ('second', 'Second', TRUE)"))
            connection.execute(text("INSERT INTO companies (tenant_id, company_code, company_name, active) SELECT id, 'second', 'Second', TRUE FROM tenants WHERE tenant_code = 'second'"))
            connection.execute(text("INSERT INTO stores (tenant_id, company_id, platform, store_code, store_name, active) SELECT tenants.id, companies.id, 'jd', 'LEGACY', 'Second Legacy', TRUE FROM tenants JOIN companies ON companies.tenant_id = tenants.id WHERE tenants.tenant_code = 'second'"))

        blocked = alembic("downgrade", "0043_ai_product_asset_upload", check=False)
        assert blocked.returncode != 0
        assert "duplicate store_code values exist across tenants" in f"{blocked.stdout}\n{blocked.stderr}"

        with engine.begin() as connection:
            connection.execute(text("UPDATE stores SET store_code = 'SECOND' WHERE store_name = 'Second Legacy'"))
        blocked = alembic("downgrade", "0043_ai_product_asset_upload", check=False)
        assert blocked.returncode != 0
        assert "scoped authorization data would be lost" in f"{blocked.stdout}\n{blocked.stderr}"

        with engine.begin() as connection:
            connection.execute(text("DELETE FROM stores WHERE store_name = 'Second Legacy'"))
            connection.execute(text("DELETE FROM companies WHERE company_code = 'second'"))
            connection.execute(text("DELETE FROM tenants WHERE tenant_code = 'second'"))
            connection.execute(text("UPDATE user_store_memberships SET can_write = FALSE WHERE assignment_managed = FALSE"))
        blocked = alembic("downgrade", "0043_ai_product_asset_upload", check=False)
        assert blocked.returncode != 0
        assert "store membership changes would be lost" in f"{blocked.stdout}\n{blocked.stderr}"
        with engine.begin() as connection:
            connection.execute(text("UPDATE user_store_memberships SET can_write = TRUE WHERE assignment_managed = FALSE"))
        alembic("downgrade", "0043_ai_product_asset_upload")
        alembic("upgrade", "head")
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {database_name}"))
        admin_engine.dispose()


@pytest.fixture()
def authorization_scope(test_db):
    with test_db() as db:
        owner = db.query(User).filter(User.username == "owner").one()
        own_store = db.query(Store).filter(Store.store_code == "JD01").one()
        other_company = Company(
            tenant_id=owner.tenant_id,
            company_code="other-company",
            company_name="Other Company",
            active=True,
        )
        other_tenant = Tenant(tenant_code="other-tenant", tenant_name="Other Tenant", active=True)
        db.add_all([other_company, other_tenant])
        db.flush()
        other_tenant_company = Company(
            tenant_id=other_tenant.id,
            company_code="internal-test",
            company_name="Other Tenant Company",
            active=True,
        )
        db.add(other_tenant_company)
        db.flush()
        same_company_unauthorized = Store(
            platform="jd",
            store_code="NO-MEMBERSHIP",
            store_name="No Membership",
            tenant_id=owner.tenant_id,
            company_id=owner.company_id,
            active=True,
        )
        cross_company = Store(
            platform="jd",
            store_code="CROSS-COMPANY",
            store_name="Cross Company",
            tenant_id=owner.tenant_id,
            company_id=other_company.id,
            active=True,
        )
        cross_tenant_same_code = Store(
            platform="jd",
            store_code=own_store.store_code,
            store_name="Cross Tenant Same Code",
            tenant_id=other_tenant.id,
            company_id=other_tenant_company.id,
            active=True,
        )
        db.add_all([same_company_unauthorized, cross_company, cross_tenant_same_code])
        db.flush()
        db.add_all(
            [
                UserStoreMembership(
                    user_id=owner.id,
                    store_id=store.id,
                    can_read=True,
                    can_write=True,
                    active=True,
                )
                for store in (cross_company, cross_tenant_same_code)
            ]
        )
        for store, amount in (
            (own_store, 100),
            (same_company_unauthorized, 200),
            (cross_company, 300),
            (cross_tenant_same_code, 400),
        ):
            db.add(
                JdDailyMetric(
                    store_id=store.id,
                    metric_date=date(2026, 8, 10),
                    gmv=amount,
                    paid_orders_count=1,
                    ad_spend=10,
                    source="test",
                )
            )
        db.commit()
        return {
            "own": own_store.id,
            "same_company_unauthorized": same_company_unauthorized.id,
            "cross_company": cross_company.id,
            "cross_tenant_same_code": cross_tenant_same_code.id,
            "cross_tenant_id": other_tenant.id,
            "cross_company_id": other_company.id,
        }


def test_unscoped_store_reads_only_return_authorized_scope(client, owner_headers, authorization_scope):
    stores = client.get("/api/stores", headers=owner_headers)
    assert stores.status_code == 200
    assert [store["id"] for store in stores.json()] == [authorization_scope["own"]]

    today = client.get("/api/metrics/today", headers=owner_headers)
    assert today.status_code == 200
    assert [store["store_id"] for store in today.json()] == [authorization_scope["own"]]

    business = client.get(
        "/api/business-center/metrics?date_from=2026-08-10&date_to=2026-08-10",
        headers=owner_headers,
    )
    assert business.status_code == 200
    assert business.json()["summary"]["sales_amount"] == 100

    dashboard = client.get(
        "/api/owner/dashboard?date_from=2026-08-10&date_to=2026-08-10",
        headers=owner_headers,
    )
    assert dashboard.status_code == 200
    assert dashboard.json()["today_sales"] == 100


def test_inactive_authorized_store_remains_manageable(client, owner_headers, authorization_scope):
    store_id = authorization_scope["own"]
    disabled = client.post(f"/api/stores/{store_id}/toggle", headers=owner_headers)
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["active"] is False
    assert store_id in [row["id"] for row in client.get("/api/stores", headers=owner_headers).json()]
    assert client.post(f"/api/stores/{store_id}/toggle", headers=owner_headers).json()["active"] is True


def test_admin_user_management_is_tenant_and_company_scoped(client, admin_headers, test_db):
    with test_db() as db:
        tenant = Tenant(tenant_code="isolated-users", tenant_name="Isolated Users", active=True)
        db.add(tenant)
        db.flush()
        company = Company(tenant_id=tenant.id, company_code="isolated", company_name="Isolated", active=True)
        db.add(company)
        db.flush()
        foreign_user = User(
            username="foreign-user",
            password_hash=hash_password("password"),
            role="operator",
            display_name="Foreign User",
            tenant_id=tenant.id,
            company_id=company.id,
            active=True,
        )
        db.add(foreign_user)
        db.commit()
        foreign_user_id = foreign_user.id
        original_hash = foreign_user.password_hash

    listed = client.get("/api/users", headers=admin_headers)
    assert listed.status_code == 200
    assert "foreign-user" not in {row["username"] for row in listed.json()}
    assert client.post(f"/api/users/{foreign_user_id}/reset-password", headers=admin_headers).status_code == 404
    assert client.post(f"/api/users/{foreign_user_id}/toggle", headers=admin_headers).status_code == 404

    with test_db() as db:
        foreign_user = db.get(User, foreign_user_id)
        assert foreign_user.active is True
        assert foreign_user.password_hash == original_hash


@pytest.mark.parametrize("endpoint", ["/api/business-center/metrics", "/api/owner/dashboard"])
@pytest.mark.parametrize(
    "target",
    ["same_company_unauthorized", "cross_company", "cross_tenant_same_code"],
)
def test_scoped_reads_deny_unauthorized_store(client, owner_headers, authorization_scope, endpoint, target):
    response = client.get(
        f"{endpoint}?store_id={authorization_scope[target]}&date_from=2026-08-10&date_to=2026-08-10",
        headers=owner_headers,
    )

    assert response.status_code == 403
    assert "store_name" not in response.text


@pytest.mark.parametrize(
    "target",
    ["same_company_unauthorized", "cross_company", "cross_tenant_same_code"],
)
def test_manual_write_denies_unauthorized_store_without_changes(
    client, owner_headers, test_db, authorization_scope, target
):
    store_id = authorization_scope[target]
    response = client.post(
        "/api/metrics/manual",
        headers=owner_headers,
        json={"store_id": store_id, "metric_date": "2026-08-11", "sales_amount": 999},
    )

    assert response.status_code == 403
    with test_db() as db:
        assert db.query(MetricDaily).filter(MetricDaily.store_id == store_id).count() == 0
        assert db.query(JdDailyMetric).filter(
            JdDailyMetric.store_id == store_id,
            JdDailyMetric.metric_date == "2026-08-11",
        ).count() == 0


@pytest.mark.parametrize(
    "target",
    ["same_company_unauthorized", "cross_company", "cross_tenant_same_code"],
)
def test_file_import_denies_unauthorized_store_without_changes(
    client, owner_headers, test_db, authorization_scope, target
):
    store_id = authorization_scope[target]
    content = b"metric_date,sales_amount,ad_spend,orders_count\n2026-08-11,999,10,1\n"
    response = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        data={
            "store_id": str(store_id),
            "tenant_id": str(authorization_scope["cross_tenant_id"]),
            "company_id": str(authorization_scope["cross_company_id"]),
        },
        files={"file": ("metrics.csv", content, "text/csv")},
    )

    assert response.status_code == 403
    with test_db() as db:
        assert db.query(MetricDaily).filter(MetricDaily.store_id == store_id).count() == 0
        assert db.query(JdDailyMetric).filter(
            JdDailyMetric.store_id == store_id,
            JdDailyMetric.metric_date == "2026-08-11",
        ).count() == 0


def test_same_store_code_in_other_tenant_never_receives_import(
    client, owner_headers, test_db, authorization_scope
):
    content = (
        b"store_code,metric_date,sales_amount,ad_spend,orders_count\n"
        b"JD01,2026-08-11,123,10,1\n"
    )
    response = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        files={"file": ("metrics.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    with test_db() as db:
        assert db.query(MetricDaily).filter(
            MetricDaily.store_id == authorization_scope["own"],
            MetricDaily.metric_date == "2026-08-11",
        ).count() == 1
        assert db.query(MetricDaily).filter(
            MetricDaily.store_id == authorization_scope["cross_tenant_same_code"],
            MetricDaily.metric_date == "2026-08-11",
        ).count() == 0


def test_import_without_store_scope_is_denied(client, owner_headers):
    content = b"metric_date,sales_amount,ad_spend,orders_count\n2026-08-11,123,10,1\n"
    response = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        files={"file": ("metrics.csv", content, "text/csv")},
    )

    assert response.status_code == 403


def test_import_records_hide_data_after_store_access_is_revoked(
    client, owner_headers, test_db, authorization_scope
):
    content = b"metric_date,sales_amount,ad_spend,orders_count\n2026-08-13,123,10,1\n"
    imported = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        data={"store_id": str(authorization_scope["own"])},
        files={"file": ("metrics.csv", content, "text/csv")},
    )
    assert imported.status_code == 200
    assert len(client.get("/api/metrics/import-records", headers=owner_headers).json()["records"]) == 1

    with test_db() as db:
        owner = db.query(User).filter(User.username == "owner").one()
        membership = db.query(UserStoreMembership).filter(
            UserStoreMembership.user_id == owner.id,
            UserStoreMembership.store_id == authorization_scope["own"],
        ).one()
        membership.active = False
        db.commit()

    records = client.get("/api/metrics/import-records", headers=owner_headers)
    assert records.status_code == 200
    assert records.json() == {"records": []}
