"""account center tables

Revision ID: 0003_account_center_tables
Revises: 0002_jd_collection_tables
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_account_center_tables"
down_revision = "0002_jd_collection_tables"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(index["name"] == index_name for index in _inspector().get_indexes(table_name))


def _create_table_if_missing(table_name: str, *columns, **kwargs) -> None:
    if not _has_table(table_name):
        op.create_table(table_name, *columns, **kwargs)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str], **kwargs) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns, **kwargs)


def upgrade():
    _create_table_if_missing(
        "account_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("fields_json", sa.Text()),
        sa.Column("active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    _create_table_if_missing(
        "brands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("brand_code", sa.String(100), unique=True),
        sa.Column("brand_name", sa.String(200), nullable=False, unique=True),
        sa.Column("owner_name", sa.String(100)),
        sa.Column("notes", sa.Text()),
        sa.Column("active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    _create_table_if_missing(
        "store_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_code", sa.String(100), unique=True),
        sa.Column("group_name", sa.String(200), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    _create_table_if_missing(
        "store_account_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id", ondelete="SET NULL")),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("store_groups.id", ondelete="SET NULL")),
        sa.Column("login_account", sa.String(200)),
        sa.Column("encrypted_password", sa.Text()),
        sa.Column("cookie_status", sa.String(50), default="待登录"),
        sa.Column("login_status", sa.String(50), default="待登录"),
        sa.Column("account_status", sa.String(50), default="待登录"),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("tags", sa.Text()),
        sa.Column("active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("store_id", name="uq_store_account_notes_store"),
    )
    _create_table_if_missing(
        "employee_store_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_name", sa.String(100), nullable=False),
        sa.Column("phone", sa.String(50)),
        sa.Column("role_name", sa.String(50), default="负责人"),
        sa.Column("active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("store_id", name="uq_employee_store_assignments_store"),
    )


def downgrade():
    op.drop_table("employee_store_assignments")
    op.drop_table("store_account_notes")
    op.drop_table("store_groups")
    op.drop_table("brands")
    op.drop_table("account_templates")
