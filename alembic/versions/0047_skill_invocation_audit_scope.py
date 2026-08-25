"""Scope skill invocation audit logs to an exact invocation.

Revision ID: 0047_skill_invocation_audit_scope
Revises: 0046_task_center_ownership_scope
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0047_skill_invocation_audit_scope"
down_revision = "0046_task_center_ownership_scope"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("employee_logs", sa.Column("skill_invocation_id", sa.Integer(), nullable=True))
    op.create_index(
        "ix_employee_logs_skill_invocation_id",
        "employee_logs",
        ["skill_invocation_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_employee_logs_skill_invocation",
        "employee_logs",
        "skill_invocations",
        ["skill_invocation_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        "fk_employee_logs_skill_invocation",
        "employee_logs",
        type_="foreignkey",
    )
    op.drop_index("ix_employee_logs_skill_invocation_id", table_name="employee_logs")
    op.drop_column("employee_logs", "skill_invocation_id")
