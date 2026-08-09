"""Tenant, company, and explicit store authorization scope.

Revision ID: 0044_tenant_company_store_authorization_scope
Revises: 0043_ai_product_asset_upload
Create Date: 2026-08-10
"""

from alembic import op
import sqlalchemy as sa


revision = "0044_tenant_company_store_authorization_scope"
down_revision = "0043_ai_product_asset_upload"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_code", sa.String(length=64), nullable=False),
        sa.Column("tenant_name", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("tenant_code", name="uq_tenants_tenant_code"),
    )
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("company_code", sa.String(length=64), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_companies_tenant", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "company_code", name="uq_companies_tenant_company_code"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_companies_tenant_id_id"),
    )
    op.create_index("ix_companies_tenant_id", "companies", ["tenant_id"])

    op.execute(
        "INSERT INTO tenants (tenant_code, tenant_name, active) "
        "VALUES ('default', 'Default Tenant', TRUE)"
    )
    op.execute(
        "INSERT INTO companies (tenant_id, company_code, company_name, active) "
        "SELECT id, 'default', 'Default Company', TRUE FROM tenants WHERE tenant_code = 'default'"
    )

    op.add_column("users", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("company_id", sa.Integer(), nullable=True))
    op.add_column("stores", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.add_column("stores", sa.Column("company_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE users SET tenant_id = (SELECT id FROM tenants WHERE tenant_code = 'default'), "
        "company_id = (SELECT id FROM companies WHERE company_code = 'default')"
    )
    op.execute(
        "UPDATE stores SET tenant_id = (SELECT id FROM tenants WHERE tenant_code = 'default'), "
        "company_id = (SELECT id FROM companies WHERE company_code = 'default')"
    )
    op.alter_column("users", "tenant_id", nullable=False)
    op.alter_column("users", "company_id", nullable=False)
    op.alter_column("stores", "tenant_id", nullable=False)
    op.alter_column("stores", "company_id", nullable=False)
    op.create_foreign_key("fk_users_tenant", "users", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key(
        "fk_users_tenant_company",
        "users",
        "companies",
        ["tenant_id", "company_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key("fk_stores_tenant", "stores", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key(
        "fk_stores_tenant_company",
        "stores",
        "companies",
        ["tenant_id", "company_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_company_id", "users", ["company_id"])
    op.create_index("ix_stores_tenant_id", "stores", ["tenant_id"])
    op.create_index("ix_stores_company_id", "stores", ["company_id"])

    op.drop_index("ix_stores_store_code", table_name="stores")
    op.create_index("ix_stores_store_code", "stores", ["store_code"], unique=False)
    op.create_unique_constraint("uq_stores_tenant_store_code", "stores", ["tenant_id", "store_code"])

    op.create_table(
        "user_store_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("can_read", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_write", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("assignment_managed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("assignment_previous_active", sa.Boolean(), nullable=True),
        sa.Column("assignment_previous_can_read", sa.Boolean(), nullable=True),
        sa.Column("assignment_previous_can_write", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_store_memberships_user", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], name="fk_user_store_memberships_store", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "store_id", name="uq_user_store_memberships_user_store"),
    )
    op.create_index("ix_user_store_memberships_user_id", "user_store_memberships", ["user_id"])
    op.create_index("ix_user_store_memberships_store_id", "user_store_memberships", ["store_id"])
    op.add_column("employee_logs", sa.Column("store_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_employee_logs_store",
        "employee_logs",
        "stores",
        ["store_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_employee_logs_store_id", "employee_logs", ["store_id"])
    op.execute(
        "INSERT INTO user_store_memberships (user_id, store_id, can_read, can_write, active, assignment_managed) "
        "SELECT users.id, stores.id, TRUE, TRUE, TRUE, FALSE FROM users CROSS JOIN stores "
        "WHERE users.role IN ('owner', 'boss', 'admin') "
        "ON CONFLICT (user_id, store_id) DO NOTHING"
    )
    op.execute(
        "INSERT INTO user_store_memberships ("
        "user_id, store_id, can_read, can_write, active, assignment_managed, "
        "assignment_previous_active, assignment_previous_can_read, assignment_previous_can_write"
        ") SELECT users.id, stores.id, TRUE, TRUE, TRUE, TRUE, FALSE, FALSE, FALSE "
        "FROM users JOIN stores ON stores.manager_user_id = users.id "
        "ON CONFLICT (user_id, store_id) DO NOTHING"
    )


def downgrade():
    op.execute(
        """
        DO $migration$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM stores GROUP BY store_code HAVING COUNT(*) > 1
            ) THEN
                RAISE EXCEPTION 'cannot downgrade: duplicate store_code values exist across tenants';
            END IF;
            IF EXISTS (SELECT 1 FROM tenants WHERE tenant_code <> 'default')
                OR EXISTS (SELECT 1 FROM companies WHERE company_code <> 'default')
                OR EXISTS (
                    SELECT 1 FROM users
                    WHERE tenant_id <> (SELECT id FROM tenants WHERE tenant_code = 'default')
                       OR company_id <> (SELECT id FROM companies WHERE company_code = 'default')
                )
                OR EXISTS (
                    SELECT 1 FROM stores
                    WHERE tenant_id <> (SELECT id FROM tenants WHERE tenant_code = 'default')
                       OR company_id <> (SELECT id FROM companies WHERE company_code = 'default')
                )
                OR EXISTS (SELECT 1 FROM employee_logs WHERE store_id IS NOT NULL)
            THEN
                RAISE EXCEPTION 'cannot downgrade: scoped authorization data would be lost';
            END IF;
            IF EXISTS (
                SELECT 1 FROM user_store_memberships memberships
                JOIN users ON users.id = memberships.user_id
                JOIN stores ON stores.id = memberships.store_id
                WHERE NOT memberships.active
                   OR NOT memberships.can_read
                   OR NOT memberships.can_write
                   OR NOT (users.role IN ('owner', 'boss', 'admin') OR stores.manager_user_id = users.id)
                   OR memberships.assignment_managed <> (
                       stores.manager_user_id = users.id AND users.role NOT IN ('owner', 'boss', 'admin')
                   )
                   OR (
                       memberships.assignment_managed AND (
                           memberships.assignment_previous_active IS DISTINCT FROM FALSE
                           OR memberships.assignment_previous_can_read IS DISTINCT FROM FALSE
                           OR memberships.assignment_previous_can_write IS DISTINCT FROM FALSE
                       )
                   )
                   OR (
                       NOT memberships.assignment_managed AND (
                           memberships.assignment_previous_active IS NOT NULL
                           OR memberships.assignment_previous_can_read IS NOT NULL
                           OR memberships.assignment_previous_can_write IS NOT NULL
                       )
                   )
            ) OR EXISTS (
                SELECT 1 FROM users CROSS JOIN stores
                WHERE (users.role IN ('owner', 'boss', 'admin') OR stores.manager_user_id = users.id)
                  AND NOT EXISTS (
                      SELECT 1 FROM user_store_memberships memberships
                      WHERE memberships.user_id = users.id AND memberships.store_id = stores.id
                  )
            ) THEN
                RAISE EXCEPTION 'cannot downgrade: store membership changes would be lost';
            END IF;
        END
        $migration$
        """
    )
    op.drop_index("ix_employee_logs_store_id", table_name="employee_logs")
    op.drop_constraint("fk_employee_logs_store", "employee_logs", type_="foreignkey")
    op.drop_column("employee_logs", "store_id")
    op.drop_index("ix_user_store_memberships_store_id", table_name="user_store_memberships")
    op.drop_index("ix_user_store_memberships_user_id", table_name="user_store_memberships")
    op.drop_table("user_store_memberships")

    op.drop_constraint("uq_stores_tenant_store_code", "stores", type_="unique")
    op.drop_index("ix_stores_store_code", table_name="stores")
    op.create_index("ix_stores_store_code", "stores", ["store_code"], unique=True)

    op.drop_index("ix_stores_company_id", table_name="stores")
    op.drop_index("ix_stores_tenant_id", table_name="stores")
    op.drop_index("ix_users_company_id", table_name="users")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_constraint("fk_stores_tenant_company", "stores", type_="foreignkey")
    op.drop_constraint("fk_stores_tenant", "stores", type_="foreignkey")
    op.drop_constraint("fk_users_tenant_company", "users", type_="foreignkey")
    op.drop_constraint("fk_users_tenant", "users", type_="foreignkey")
    op.drop_column("stores", "company_id")
    op.drop_column("stores", "tenant_id")
    op.drop_column("users", "company_id")
    op.drop_column("users", "tenant_id")
    op.drop_index("ix_companies_tenant_id", table_name="companies")
    op.drop_table("companies")
    op.drop_table("tenants")
