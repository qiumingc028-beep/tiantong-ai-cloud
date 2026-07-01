"""initial production schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
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
    _create_table_if_missing("roles", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(50), nullable=False, unique=True), sa.Column("name", sa.String(100), nullable=False), sa.Column("description", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    _create_table_if_missing("permissions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(100), nullable=False, unique=True), sa.Column("name", sa.String(100), nullable=False), sa.Column("description", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    _create_table_if_missing("role_permissions", sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True), sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True))
    _create_table_if_missing("users", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("username", sa.String(50), nullable=False, unique=True), sa.Column("password_hash", sa.Text(), nullable=False), sa.Column("role", sa.String(50), nullable=False), sa.Column("display_name", sa.String(100), nullable=False), sa.Column("active", sa.Boolean(), default=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    _create_index_if_missing("ix_users_username", "users", ["username"])
    _create_table_if_missing("employee_logs", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("action", sa.String(100), nullable=False), sa.Column("detail", sa.Text()), sa.Column("ip_address", sa.String(100)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    _create_table_if_missing("stores", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("platform", sa.String(50), nullable=False), sa.Column("store_code", sa.String(100), nullable=False, unique=True), sa.Column("store_name", sa.String(200), nullable=False), sa.Column("manager_user_id", sa.Integer(), sa.ForeignKey("users.id")), sa.Column("active", sa.Boolean(), default=True), sa.Column("notes", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    _create_index_if_missing("ix_stores_store_code", "stores", ["store_code"])
    _create_table_if_missing("metrics_daily", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False), sa.Column("metric_date", sa.Date(), nullable=False), sa.Column("sales_amount", sa.Numeric(14, 2), default=0), sa.Column("profit_amount", sa.Numeric(14, 2), default=0), sa.Column("ad_spend", sa.Numeric(14, 2), default=0), sa.Column("roi", sa.Numeric(10, 2), default=0), sa.Column("orders_count", sa.Integer(), default=0), sa.Column("visitors_count", sa.Integer(), default=0), sa.Column("refunds_count", sa.Integer(), default=0), sa.Column("after_sales_count", sa.Integer(), default=0), sa.Column("source", sa.String(50), default="manual"), sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.UniqueConstraint("store_id", "metric_date", name="uq_metrics_daily_store_date"))
    _create_table_if_missing("jd_integrations", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False), sa.Column("source_type", sa.String(50), nullable=False), sa.Column("connection_mode", sa.String(50), nullable=False), sa.Column("merchant_id", sa.String(100)), sa.Column("app_key", sa.String(200)), sa.Column("status", sa.String(50), default="pending"), sa.Column("notes", sa.Text()), sa.Column("active", sa.Boolean(), default=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    _create_table_if_missing("ai_tasks", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("ai_employee_code", sa.String(50), nullable=False, unique=True), sa.Column("ai_employee_name", sa.String(100), nullable=False), sa.Column("status", sa.String(50), default="idle"), sa.Column("today_task", sa.Text()), sa.Column("execution_log", sa.Text()), sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("last_run_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))


def downgrade():
    op.drop_table("ai_tasks")
    op.drop_table("jd_integrations")
    op.drop_table("metrics_daily")
    op.drop_table("stores")
    op.drop_table("employee_logs")
    op.drop_table("users")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
