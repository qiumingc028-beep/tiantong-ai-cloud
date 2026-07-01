"""jd collection tables

Revision ID: 0002_jd_collection_tables
Revises: 0001_initial_schema
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_jd_collection_tables"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("jd_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_type", sa.String(50), nullable=False),
        sa.Column("account_name", sa.String(100), nullable=False),
        sa.Column("login_username", sa.String(200)),
        sa.Column("auth_status", sa.String(50), default="pending"),
        sa.Column("access_token", sa.Text()),
        sa.Column("refresh_token", sa.Text()),
        sa.Column("token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table("jd_daily_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("gmv", sa.Numeric(14, 2), default=0),
        sa.Column("profit_amount", sa.Numeric(14, 2), default=0),
        sa.Column("visitors_count", sa.Integer(), default=0),
        sa.Column("paid_orders_count", sa.Integer(), default=0),
        sa.Column("ad_spend", sa.Numeric(14, 2), default=0),
        sa.Column("roi", sa.Numeric(10, 2), default=0),
        sa.Column("refunds_count", sa.Integer(), default=0),
        sa.Column("after_sales_count", sa.Integer(), default=0),
        sa.Column("favorites_count", sa.Integer(), default=0),
        sa.Column("cart_add_count", sa.Integer(), default=0),
        sa.Column("conversion_rate", sa.Numeric(10, 4), default=0),
        sa.Column("source", sa.String(50), default="jd"),
        sa.Column("raw_payload", sa.Text()),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("store_id", "metric_date", name="uq_jd_daily_metrics_store_date"),
    )
    op.create_table("jd_ads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("jd_accounts.id", ondelete="SET NULL")),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("campaign_id", sa.String(100)),
        sa.Column("campaign_name", sa.String(200)),
        sa.Column("ad_spend", sa.Numeric(14, 2), default=0),
        sa.Column("clicks", sa.Integer(), default=0),
        sa.Column("impressions", sa.Integer(), default=0),
        sa.Column("roi", sa.Numeric(10, 2), default=0),
        sa.Column("cpa", sa.Numeric(14, 2), default=0),
        sa.Column("deal_amount", sa.Numeric(14, 2), default=0),
        sa.Column("raw_payload", sa.Text()),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table("jd_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_no", sa.String(100), nullable=False, unique=True),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("paid_amount", sa.Numeric(14, 2), default=0),
        sa.Column("profit_amount", sa.Numeric(14, 2), default=0),
        sa.Column("order_status", sa.String(50)),
        sa.Column("buyer_pin", sa.String(100)),
        sa.Column("raw_payload", sa.Text()),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table("jd_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sku_id", sa.String(100), nullable=False),
        sa.Column("product_name", sa.String(300), nullable=False),
        sa.Column("category_name", sa.String(200)),
        sa.Column("stock_quantity", sa.Integer(), default=0),
        sa.Column("sales_amount", sa.Numeric(14, 2), default=0),
        sa.Column("sales_quantity", sa.Integer(), default=0),
        sa.Column("visitors_count", sa.Integer(), default=0),
        sa.Column("conversion_rate", sa.Numeric(10, 4), default=0),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("raw_payload", sa.Text()),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("jd_products")
    op.drop_table("jd_orders")
    op.drop_table("jd_ads")
    op.drop_table("jd_daily_metrics")
    op.drop_table("jd_accounts")
