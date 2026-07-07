"""sprint20.5 release center

Revision ID: 0017_sprint20_5_release_center
Revises: 0016_sprint20_employee_evolution
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0017_sprint20_5_release_center"
down_revision = "0016_sprint20_employee_evolution"
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


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade():
    if not _has_table("release_versions"):
        op.create_table(
            "release_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("version", sa.String(100), nullable=False),
            sa.Column("sprint_name", sa.String(200), nullable=False),
            sa.Column("commit_id", sa.String(100), nullable=False),
            sa.Column("branch", sa.String(100), nullable=False),
            sa.Column("author", sa.String(100)),
            sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("approved_by", sa.String(100)),
            sa.Column("deploy_status", sa.String(50), nullable=False, server_default="waiting"),
            sa.UniqueConstraint("version", name="uq_release_versions_version"),
        )
    _create_index_if_missing("ix_release_versions_version", "release_versions", ["version"])
    _create_index_if_missing("ix_release_versions_sprint_name", "release_versions", ["sprint_name"])
    _create_index_if_missing("ix_release_versions_commit_id", "release_versions", ["commit_id"])
    _create_index_if_missing("ix_release_versions_branch", "release_versions", ["branch"])
    _create_index_if_missing("ix_release_versions_status", "release_versions", ["status"])
    _create_index_if_missing("ix_release_versions_created_at", "release_versions", ["created_at"])
    _create_index_if_missing("ix_release_versions_deploy_status", "release_versions", ["deploy_status"])


def downgrade():
    if _has_table("release_versions"):
        op.drop_table("release_versions")
