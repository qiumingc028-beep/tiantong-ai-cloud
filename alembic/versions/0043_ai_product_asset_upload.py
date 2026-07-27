"""AI product draft and asset upload metadata

Revision ID: 0043_ai_product_asset_upload
Revises: 0042_v2_alpha_workflow_unique_constraints
Create Date: 2026-07-27
"""

from alembic import op
import sqlalchemy as sa


revision = "0043_ai_product_asset_upload"
down_revision = "0042_v2_alpha_workflow_unique_constraints"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_product_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("shop_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for column in ("tenant_id", "shop_id", "created_by"):
        op.create_index(f"ix_ai_product_drafts_{column}", "ai_product_drafts", [column])

    op.create_table(
        "ai_product_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("draft_id", sa.Integer(), sa.ForeignKey("ai_product_drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("shop_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ready"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for column in ("draft_id", "tenant_id", "shop_id", "created_by"):
        op.create_index(f"ix_ai_product_assets_{column}", "ai_product_assets", [column])


def downgrade():
    op.drop_table("ai_product_assets")
    op.drop_table("ai_product_drafts")
