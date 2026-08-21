"""Scope Task Center data to trusted server ownership.

Revision ID: 0046_task_center_ownership_scope
Revises: 0045_brain_task_graph_scope_identity
Create Date: 2026-08-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0046_task_center_ownership_scope"
down_revision = "0045_brain_task_graph_scope_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("task_center_tasks", sa.Column("tenant_id", sa.Integer(), nullable=True))
    op.add_column("task_center_tasks", sa.Column("company_id", sa.Integer(), nullable=True))
    op.add_column("task_center_tasks", sa.Column("requester_id", sa.Integer(), nullable=True))
    op.add_column("task_center_tasks", sa.Column("store_scope_key", sa.Text(), nullable=True))
    op.add_column("task_center_tasks", sa.Column("ownership_scope_key", sa.String(length=64), nullable=True))
    op.add_column("task_center_tasks", sa.Column("canonical_run_id", sa.String(length=36), nullable=True))
    op.create_foreign_key("fk_task_center_tasks_tenant", "task_center_tasks", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key(
        "fk_task_center_tasks_tenant_company",
        "task_center_tasks",
        "companies",
        ["tenant_id", "company_id"],
        ["tenant_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key("fk_task_center_tasks_requester", "task_center_tasks", "users", ["requester_id"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key(
        "fk_task_center_tasks_canonical_run",
        "task_center_tasks",
        "alpha_workflow_runs",
        ["canonical_run_id"],
        ["run_id"],
        ondelete="SET NULL",
    )
    for column_name in ("tenant_id", "company_id", "requester_id", "ownership_scope_key", "canonical_run_id"):
        op.create_index(f"ix_task_center_tasks_{column_name}", "task_center_tasks", [column_name])


def downgrade():
    for column_name in reversed(("tenant_id", "company_id", "requester_id", "ownership_scope_key", "canonical_run_id")):
        op.drop_index(f"ix_task_center_tasks_{column_name}", table_name="task_center_tasks")
    op.drop_constraint("fk_task_center_tasks_canonical_run", "task_center_tasks", type_="foreignkey")
    op.drop_constraint("fk_task_center_tasks_requester", "task_center_tasks", type_="foreignkey")
    op.drop_constraint("fk_task_center_tasks_tenant_company", "task_center_tasks", type_="foreignkey")
    op.drop_constraint("fk_task_center_tasks_tenant", "task_center_tasks", type_="foreignkey")
    for column_name in ("canonical_run_id", "ownership_scope_key", "store_scope_key", "requester_id", "company_id", "tenant_id"):
        op.drop_column("task_center_tasks", column_name)
