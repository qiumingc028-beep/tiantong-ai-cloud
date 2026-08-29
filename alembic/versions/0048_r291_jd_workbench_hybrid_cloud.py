"""Add the R291 JD workbench pairing and normalized sync boundary.

Revision ID: 0048_r291_jd_workbench_hybrid_cloud
Revises: 0047_skill_invocation_audit_scope
Create Date: 2026-08-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0048_r291_jd_workbench_hybrid_cloud"
down_revision = "0047_skill_invocation_audit_scope"
branch_labels = None
depends_on = None


def upgrade():
    # R291 no longer accepts or retains JD login material or unfiltered source
    # payloads. This redaction is intentionally irreversible; the pre-deploy
    # encrypted database backup remains available only in the root-only backup
    # area for disaster recovery and must never enter an evidence bundle.
    op.execute("UPDATE store_account_notes SET encrypted_password = NULL, login_account = NULL")
    op.execute(
        "UPDATE jd_accounts SET access_token = NULL, refresh_token = NULL, "
        "login_username = NULL, remark = NULL"
    )
    op.execute("UPDATE jd_integrations SET app_key = NULL")
    op.execute("UPDATE jd_daily_metrics SET raw_payload = NULL")
    op.execute("UPDATE jd_ads SET raw_payload = NULL")
    op.execute(
        "UPDATE jd_orders SET buyer_pin = NULL, raw_payload = NULL, "
        "order_no = 'redacted-' || CAST(id AS VARCHAR)"
    )
    op.execute("UPDATE jd_products SET raw_payload = NULL")
    op.execute(
        "UPDATE jd_sync_logs SET message = 'REDACTED_R291' "
        "WHERE task_type IN ('sync_jd_smart', 'sync_jzt', 'sync_jd_orders', 'sync_jd_products')"
    )

    op.create_table(
        "jd_workbench_pairing_codes",
        sa.Column("pairing_id", sa.String(length=36), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("pairing_id"),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index("ix_jd_workbench_pairing_codes_code_hash", "jd_workbench_pairing_codes", ["code_hash"])
    op.create_index("ix_jd_workbench_pairing_codes_tenant_id", "jd_workbench_pairing_codes", ["tenant_id"])
    op.create_index("ix_jd_workbench_pairing_codes_company_id", "jd_workbench_pairing_codes", ["company_id"])
    op.create_index("ix_jd_workbench_pairing_codes_user_id", "jd_workbench_pairing_codes", ["user_id"])

    op.create_table(
        "jd_workbench_devices",
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("public_key_n", sa.String(length=512), nullable=False),
        sa.Column("public_key_e", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("device_name", sa.String(length=120), nullable=False),
        sa.Column("client_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("device_id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_jd_workbench_devices_token_hash", "jd_workbench_devices", ["token_hash"])
    op.create_index("ix_jd_workbench_devices_tenant_id", "jd_workbench_devices", ["tenant_id"])
    op.create_index("ix_jd_workbench_devices_company_id", "jd_workbench_devices", ["company_id"])
    op.create_index("ix_jd_workbench_devices_user_id", "jd_workbench_devices", ["user_id"])

    op.create_table(
        "jd_workbench_store_statuses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["jd_workbench_devices.device_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "store_id", name="uq_jd_workbench_store_status_device_store"),
    )
    op.create_index("ix_jd_workbench_store_statuses_device_id", "jd_workbench_store_statuses", ["device_id"])
    op.create_index("ix_jd_workbench_store_statuses_store_id", "jd_workbench_store_statuses", ["store_id"])

    op.create_table(
        "jd_workbench_sync_batches",
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("dataset_type", sa.String(length=32), nullable=False),
        sa.Column("source_period", sa.String(length=64), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("client_version", sa.String(length=64), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["device_id"], ["jd_workbench_devices.device_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("batch_id"),
        sa.UniqueConstraint(
            "tenant_id", "store_id", "dataset_type", "idempotency_key",
            name="uq_jd_workbench_sync_batch_idempotency",
        ),
    )
    op.create_index("ix_jd_workbench_sync_batches_device_id", "jd_workbench_sync_batches", ["device_id"])
    op.create_index("ix_jd_workbench_sync_batches_tenant_id", "jd_workbench_sync_batches", ["tenant_id"])
    op.create_index("ix_jd_workbench_sync_batches_company_id", "jd_workbench_sync_batches", ["company_id"])
    op.create_index("ix_jd_workbench_sync_batches_store_id", "jd_workbench_sync_batches", ["store_id"])
    op.create_index("ix_jd_workbench_sync_batches_subject_id", "jd_workbench_sync_batches", ["subject_id"])
    op.create_index("ix_jd_workbench_sync_batches_dataset_type", "jd_workbench_sync_batches", ["dataset_type"])

    op.create_table(
        "jd_workbench_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column("dataset_type", sa.String(length=32), nullable=False),
        sa.Column("source_period", sa.String(length=64), nullable=False),
        sa.Column("source_record_key", sa.String(length=160), nullable=False),
        sa.Column("values_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["jd_workbench_sync_batches.batch_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "store_id", "dataset_type", "source_period", "source_record_key",
            name="uq_jd_workbench_record_scope_source",
        ),
    )
    op.create_index("ix_jd_workbench_records_batch_id", "jd_workbench_records", ["batch_id"])
    op.create_index("ix_jd_workbench_records_tenant_id", "jd_workbench_records", ["tenant_id"])
    op.create_index("ix_jd_workbench_records_company_id", "jd_workbench_records", ["company_id"])
    op.create_index("ix_jd_workbench_records_store_id", "jd_workbench_records", ["store_id"])
    op.create_index("ix_jd_workbench_records_subject_id", "jd_workbench_records", ["subject_id"])
    op.create_index("ix_jd_workbench_records_dataset_type", "jd_workbench_records", ["dataset_type"])


def downgrade():
    op.drop_index("ix_jd_workbench_records_dataset_type", table_name="jd_workbench_records")
    op.drop_index("ix_jd_workbench_records_subject_id", table_name="jd_workbench_records")
    op.drop_index("ix_jd_workbench_records_store_id", table_name="jd_workbench_records")
    op.drop_index("ix_jd_workbench_records_company_id", table_name="jd_workbench_records")
    op.drop_index("ix_jd_workbench_records_tenant_id", table_name="jd_workbench_records")
    op.drop_index("ix_jd_workbench_records_batch_id", table_name="jd_workbench_records")
    op.drop_table("jd_workbench_records")
    op.drop_index("ix_jd_workbench_sync_batches_dataset_type", table_name="jd_workbench_sync_batches")
    op.drop_index("ix_jd_workbench_sync_batches_subject_id", table_name="jd_workbench_sync_batches")
    op.drop_index("ix_jd_workbench_sync_batches_store_id", table_name="jd_workbench_sync_batches")
    op.drop_index("ix_jd_workbench_sync_batches_company_id", table_name="jd_workbench_sync_batches")
    op.drop_index("ix_jd_workbench_sync_batches_tenant_id", table_name="jd_workbench_sync_batches")
    op.drop_index("ix_jd_workbench_sync_batches_device_id", table_name="jd_workbench_sync_batches")
    op.drop_table("jd_workbench_sync_batches")
    op.drop_index("ix_jd_workbench_store_statuses_store_id", table_name="jd_workbench_store_statuses")
    op.drop_index("ix_jd_workbench_store_statuses_device_id", table_name="jd_workbench_store_statuses")
    op.drop_table("jd_workbench_store_statuses")
    op.drop_index("ix_jd_workbench_devices_user_id", table_name="jd_workbench_devices")
    op.drop_index("ix_jd_workbench_devices_company_id", table_name="jd_workbench_devices")
    op.drop_index("ix_jd_workbench_devices_tenant_id", table_name="jd_workbench_devices")
    op.drop_index("ix_jd_workbench_devices_token_hash", table_name="jd_workbench_devices")
    op.drop_table("jd_workbench_devices")
    op.drop_index("ix_jd_workbench_pairing_codes_user_id", table_name="jd_workbench_pairing_codes")
    op.drop_index("ix_jd_workbench_pairing_codes_company_id", table_name="jd_workbench_pairing_codes")
    op.drop_index("ix_jd_workbench_pairing_codes_tenant_id", table_name="jd_workbench_pairing_codes")
    op.drop_index("ix_jd_workbench_pairing_codes_code_hash", table_name="jd_workbench_pairing_codes")
    op.drop_table("jd_workbench_pairing_codes")
