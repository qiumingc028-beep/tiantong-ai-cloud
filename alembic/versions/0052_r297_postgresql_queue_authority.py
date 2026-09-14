"""Make PostgreSQL authoritative for R297 queue identity and scope.

Revision ID: 0052_r297_postgresql_queue_authority
Revises: 0051_r297_queue_fencing_and_idempotency
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "0052_r297_postgresql_queue_authority"
down_revision = "0051_r297_queue_fencing_and_idempotency"
branch_labels = None
depends_on = None


def _reject_invalid_history():
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM jd_sync_logs
            WHERE store_id IS NOT NULL AND sync_window_started_at IS NOT NULL
              AND attempt = 0 AND source = 'cloud_scheduler'
            GROUP BY store_id, sync_window_started_at, task_type HAVING COUNT(*) > 1
          ) THEN
            RAISE EXCEPTION 'R297_DUPLICATE_STORE_WINDOW_TASK';
          END IF;
          IF EXISTS (
            SELECT 1 FROM jd_workbench_sync_policies p
            LEFT JOIN stores s ON (s.id, s.tenant_id, s.company_id) = (p.store_id, p.tenant_id, p.company_id)
            WHERE s.id IS NULL
          ) OR EXISTS (
            SELECT 1 FROM jd_workbench_sync_batches b
            LEFT JOIN stores s ON (s.id, s.tenant_id, s.company_id) = (b.store_id, b.tenant_id, b.company_id)
            WHERE s.id IS NULL
          ) OR EXISTS (
            SELECT 1 FROM jd_workbench_records r
            LEFT JOIN stores s ON (s.id, s.tenant_id, s.company_id) = (r.store_id, r.tenant_id, r.company_id)
            WHERE s.id IS NULL
          ) THEN
            RAISE EXCEPTION 'R297_TENANT_COMPANY_STORE_SCOPE_MISMATCH';
          END IF;
        END $$;
        """
    )


def upgrade():
    op.add_column("jd_sync_logs", sa.Column("tenant_id", sa.Integer()))
    op.add_column("jd_sync_logs", sa.Column("company_id", sa.Integer()))
    op.add_column("jd_sync_logs", sa.Column("claim_generation", sa.Integer()))
    op.add_column("jd_sync_logs", sa.Column("source", sa.String(length=32)))
    op.add_column("jd_sync_logs", sa.Column("redis_notification_pending", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("jd_sync_logs", sa.Column("redis_notification_payload", sa.Text()))
    op.add_column("jd_sync_logs", sa.Column("sync_window_started_at", sa.DateTime(timezone=True)))
    op.create_unique_constraint("uq_stores_tenant_company_id", "stores", ["tenant_id", "company_id", "id"])
    if inspect(op.get_bind()).has_table("r297_0052_jd_sync_log_backup"):
        backup_columns = {
            column["name"]
            for column in inspect(op.get_bind()).get_columns("r297_0052_jd_sync_log_backup")
        }
        pending_value = (
            "(b.redis_notification_pending AND b.redis_notification_payload IS NOT NULL)"
            if {"redis_notification_pending", "redis_notification_payload"}.issubset(backup_columns)
            else "false"
        )
        payload_value = "b.redis_notification_payload" if "redis_notification_payload" in backup_columns else "NULL"
        op.execute(
            f"""
            UPDATE jd_sync_logs AS l
            SET tenant_id = b.tenant_id, company_id = b.company_id,
                claim_generation = b.claim_generation, source = b.source,
                redis_notification_pending = {pending_value},
                redis_notification_payload = {payload_value},
                sync_window_started_at = b.sync_window_started_at
            FROM r297_0052_jd_sync_log_backup AS b WHERE l.id = b.id
            """
        )
        op.drop_table("r297_0052_jd_sync_log_backup")
    op.execute("UPDATE jd_sync_logs SET source = 'legacy' WHERE source IS NULL")
    op.execute(
        """
        UPDATE jd_sync_logs AS l
        SET tenant_id = COALESCE(l.tenant_id, s.tenant_id),
            company_id = COALESCE(l.company_id, s.company_id),
            sync_window_started_at = COALESCE(
              l.sync_window_started_at,
              to_timestamp(
                floor(extract(epoch FROM l.created_at) / COALESCE(p.interval_seconds, 300))
                * COALESCE(p.interval_seconds, 300)
              )
            )
        FROM stores AS s
        LEFT JOIN jd_workbench_sync_policies AS p
          ON (p.store_id, p.tenant_id, p.company_id) = (s.id, s.tenant_id, s.company_id)
        WHERE l.store_id = s.id
          AND (l.tenant_id IS NULL OR l.company_id IS NULL OR l.sync_window_started_at IS NULL)
        """
    )
    _reject_invalid_history()
    op.create_foreign_key(
        "fk_jd_sync_logs_tenant_company_store", "jd_sync_logs", "stores",
        ["tenant_id", "company_id", "store_id"], ["tenant_id", "company_id", "id"], ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_jd_sync_logs_store_scope_complete", "jd_sync_logs",
        "store_id IS NULL OR (tenant_id IS NOT NULL AND company_id IS NOT NULL AND sync_window_started_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_jd_sync_logs_notification_payload", "jd_sync_logs",
        "NOT redis_notification_pending OR redis_notification_payload IS NOT NULL",
    )
    op.create_index(
        "uq_jd_sync_logs_store_window_task_type", "jd_sync_logs",
        ["store_id", "sync_window_started_at", "task_type"], unique=True,
        postgresql_where=sa.text("attempt = 0 AND source = 'cloud_scheduler'"),
    )
    for table in ("jd_workbench_sync_policies", "jd_workbench_sync_batches", "jd_workbench_records"):
        op.create_foreign_key(
            f"fk_{table}_tenant_company_store", table, "stores",
            ["tenant_id", "company_id", "store_id"], ["tenant_id", "company_id", "id"],
            ondelete="CASCADE" if table == "jd_workbench_sync_policies" else "RESTRICT",
        )


def downgrade():
    op.create_table(
        "r297_0052_jd_sync_log_backup",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer()),
        sa.Column("company_id", sa.Integer()),
        sa.Column("claim_generation", sa.Integer()),
        sa.Column("source", sa.String(length=32)),
        sa.Column("redis_notification_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("redis_notification_payload", sa.Text()),
        sa.Column("sync_window_started_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        """
        INSERT INTO r297_0052_jd_sync_log_backup
          (id, tenant_id, company_id, claim_generation, source, redis_notification_pending, redis_notification_payload, sync_window_started_at)
        SELECT id, tenant_id, company_id, claim_generation, source, redis_notification_pending, redis_notification_payload, sync_window_started_at
        FROM jd_sync_logs
        """
    )
    for table in ("jd_workbench_records", "jd_workbench_sync_batches", "jd_workbench_sync_policies"):
        op.drop_constraint(f"fk_{table}_tenant_company_store", table, type_="foreignkey")
    op.drop_index("uq_jd_sync_logs_store_window_task_type", table_name="jd_sync_logs")
    op.drop_constraint("ck_jd_sync_logs_notification_payload", "jd_sync_logs", type_="check")
    op.drop_constraint("ck_jd_sync_logs_store_scope_complete", "jd_sync_logs", type_="check")
    op.drop_constraint("fk_jd_sync_logs_tenant_company_store", "jd_sync_logs", type_="foreignkey")
    op.drop_constraint("uq_stores_tenant_company_id", "stores", type_="unique")
    op.drop_column("jd_sync_logs", "sync_window_started_at")
    op.drop_column("jd_sync_logs", "redis_notification_payload")
    op.drop_column("jd_sync_logs", "redis_notification_pending")
    op.drop_column("jd_sync_logs", "source")
    op.drop_column("jd_sync_logs", "claim_generation")
    op.drop_column("jd_sync_logs", "company_id")
    op.drop_column("jd_sync_logs", "tenant_id")
