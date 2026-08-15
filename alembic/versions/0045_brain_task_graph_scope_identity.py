"""Scope BrainTaskGraph identity to trusted workflow ownership.

Revision ID: 0045_brain_task_graph_scope_identity
Revises: 0044_tenant_company_store_authorization_scope
Create Date: 2026-08-14
"""

import hashlib
import json
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "0045_brain_task_graph_scope_identity"
down_revision = "0044_tenant_company_store_authorization_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("brain_task_graphs", sa.Column("ownership_scope_key", sa.String(length=64), nullable=True))
    op.add_column("brain_task_graphs", sa.Column("execution_scope_key", sa.String(length=255), nullable=True))
    op.add_column("brain_task_graphs", sa.Column("semantic_hash", sa.String(length=64), nullable=True))
    op.add_column("brain_task_graphs", sa.Column("semantic_payload_json", sa.Text(), nullable=True))
    op.add_column("brain_task_graphs", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.add_column("brain_task_graphs", sa.Column("company_id", sa.Integer(), nullable=True))
    op.add_column("brain_task_graphs", sa.Column("store_scope_key", sa.Text(), nullable=True))
    op.add_column("brain_task_graphs", sa.Column("requester_id", sa.Integer(), nullable=True))
    op.add_column("brain_task_graphs", sa.Column("canonical_run_id", sa.String(length=36), nullable=True))

    connection = op.get_bind()
    rows = list(connection.execute(
        sa.text(
            "SELECT id, graph_id, user_request, goal, task_type, risk_level, "
            "approval_required, estimated_cost_level, status, dry_run, created_by "
            "FROM brain_task_graphs ORDER BY id"
        )
    ).mappings())
    for row in rows:
        payload_json = json.dumps(
            {
                "legacy_graph_id": row["graph_id"],
                "user_request": row["user_request"],
                "goal": row["goal"],
                "task_type": row["task_type"],
                "risk_level": row["risk_level"],
                "approval_required": row["approval_required"],
                "estimated_cost_level": row["estimated_cost_level"],
                "status": row["status"],
                "dry_run": row["dry_run"],
                "created_by": row["created_by"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        legacy_key = f"legacy:{row['id']}:{uuid4().hex}"
        connection.execute(
            sa.text(
                "UPDATE brain_task_graphs SET ownership_scope_key=:scope, "
                "execution_scope_key=:execution, semantic_hash=:semantic_hash, "
                "semantic_payload_json=:payload, store_scope_key=:store_scope "
                "WHERE id=:id"
            ),
            {
                "id": row["id"],
                "scope": legacy_key,
                "execution": f"legacy:{row['id']}",
                "semantic_hash": hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
                "payload": payload_json,
                "store_scope": f"legacy:{row['id']}",
            },
        )

    for column_name in (
        "ownership_scope_key",
        "execution_scope_key",
        "semantic_hash",
        "semantic_payload_json",
        "store_scope_key",
    ):
        op.alter_column("brain_task_graphs", column_name, nullable=False)

    op.create_foreign_key(
        "fk_brain_task_graphs_tenant",
        "brain_task_graphs",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_brain_task_graphs_tenant_company",
        "brain_task_graphs",
        "companies",
        ["tenant_id", "company_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_brain_task_graphs_requester",
        "brain_task_graphs",
        "users",
        ["requester_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_brain_task_graphs_canonical_run",
        "brain_task_graphs",
        "alpha_workflow_runs",
        ["canonical_run_id"],
        ["run_id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_brain_task_graph_scope_execution_semantic",
        "brain_task_graphs",
        ["ownership_scope_key", "execution_scope_key", "semantic_hash"],
    )
    for column_name in (
        "ownership_scope_key",
        "execution_scope_key",
        "semantic_hash",
        "tenant_id",
        "company_id",
        "requester_id",
        "canonical_run_id",
    ):
        op.create_index(f"ix_brain_task_graphs_{column_name}", "brain_task_graphs", [column_name])


def downgrade():
    op.execute(
        """
        DO $migration$
        BEGIN
            IF EXISTS (SELECT 1 FROM brain_task_graphs) THEN
                RAISE EXCEPTION 'cannot downgrade: BrainTaskGraph ownership identity data would be lost';
            END IF;
        END
        $migration$
        """
    )
    for column_name in reversed(
        (
            "ownership_scope_key",
            "execution_scope_key",
            "semantic_hash",
            "tenant_id",
            "company_id",
            "store_scope_key",
            "requester_id",
            "canonical_run_id",
        )
    ):
        op.drop_index(f"ix_brain_task_graphs_{column_name}", table_name="brain_task_graphs")
    op.drop_constraint("uq_brain_task_graph_scope_execution_semantic", "brain_task_graphs", type_="unique")
    op.drop_constraint("fk_brain_task_graphs_canonical_run", "brain_task_graphs", type_="foreignkey")
    op.drop_constraint("fk_brain_task_graphs_requester", "brain_task_graphs", type_="foreignkey")
    op.drop_constraint("fk_brain_task_graphs_tenant_company", "brain_task_graphs", type_="foreignkey")
    op.drop_constraint("fk_brain_task_graphs_tenant", "brain_task_graphs", type_="foreignkey")
    for column_name in (
        "canonical_run_id",
        "requester_id",
        "store_scope_key",
        "company_id",
        "tenant_id",
        "semantic_payload_json",
        "semantic_hash",
        "execution_scope_key",
        "ownership_scope_key",
    ):
        op.drop_column("brain_task_graphs", column_name)
