"""V2 skills engine foundation

Revision ID: 0032_v2_skills_engine_foundation
Revises: 0031_v2_research_topic_index
Create Date: 2026-07-12 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0032_v2_skills_engine_foundation"
down_revision = "0031_v2_research_topic_index"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("skill_code", sa.String(length=120), nullable=False),
        sa.Column("chinese_name", sa.String(length=200), nullable=False),
        sa.Column("chinese_description", sa.Text(), nullable=True),
        sa.Column("skill_type", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'草稿'")),
        sa.Column("risk_level", sa.String(length=50), nullable=False, server_default=sa.text("'低风险'")),
        sa.Column("current_version_id", sa.Integer(), nullable=True),
        sa.Column("publisher_type", sa.String(length=50), nullable=True),
        sa.Column("publisher_name", sa.String(length=100), nullable=True),
        sa.Column("source_type", sa.String(length=80), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("license", sa.String(length=200), nullable=True),
        sa.Column("checksum", sa.String(length=255), nullable=True),
        sa.Column("signature_status", sa.String(length=50), nullable=False, server_default=sa.text("'未验证'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("deprecated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_skills_skill_code", "skills", ["skill_code"])
    op.create_index("ix_skills_skill_type", "skills", ["skill_type"])
    op.create_index("ix_skills_category", "skills", ["category"])
    op.create_index("ix_skills_status", "skills", ["status"])
    op.create_index("ix_skills_risk_level", "skills", ["risk_level"])
    op.create_index("ix_skills_current_version_id", "skills", ["current_version_id"])
    op.create_index("ix_skills_enabled", "skills", ["enabled"])
    op.create_index("ix_skills_deprecated", "skills", ["deprecated"])
    op.create_index("ix_skills_created_at", "skills", ["created_at"])
    op.create_unique_constraint("uq_skills_skill_code", "skills", ["skill_code"])

    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("manifest", sa.Text(), nullable=True),
        sa.Column("input_schema", sa.Text(), nullable=True),
        sa.Column("output_schema", sa.Text(), nullable=True),
        sa.Column("required_capabilities", sa.Text(), nullable=True),
        sa.Column("required_permissions", sa.Text(), nullable=True),
        sa.Column("required_feature_flags", sa.Text(), nullable=True),
        sa.Column("min_runtime_version", sa.String(length=50), nullable=True),
        sa.Column("max_runtime_version", sa.String(length=50), nullable=True),
        sa.Column("checksum", sa.String(length=255), nullable=True),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("release_notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),
    )
    op.create_index("ix_skill_versions_skill_id", "skill_versions", ["skill_id"])
    op.create_index("ix_skill_versions_version", "skill_versions", ["version"])
    op.create_index("ix_skill_versions_created_at", "skill_versions", ["created_at"])

    op.create_table(
        "skill_installations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_version_id", sa.Integer(), sa.ForeignKey("skill_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("department_id", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'待校验'")),
        sa.Column("installed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("configuration", sa.Text(), nullable=True),
        sa.Column("permission_snapshot", sa.Text(), nullable=True),
        sa.Column("checksum_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signature_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, cols in [
        ("ix_skill_installations_skill_id", ["skill_id"]),
        ("ix_skill_installations_skill_version_id", ["skill_version_id"]),
        ("ix_skill_installations_employee_id", ["employee_id"]),
        ("ix_skill_installations_department_id", ["department_id"]),
        ("ix_skill_installations_status", ["status"]),
        ("ix_skill_installations_created_at", ["created_at"]),
    ]:
        op.create_index(name, "skill_installations", cols)

    op.create_table(
        "skill_employee_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_version_id", sa.Integer(), sa.ForeignKey("skill_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("department_id", sa.String(length=100), nullable=True),
        sa.Column("permission_scope", sa.String(length=50), nullable=False),
        sa.Column("allow", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("risk_limit", sa.String(length=50), nullable=True),
        sa.Column("environment_limit", sa.String(length=50), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("skill_id", "employee_id", "permission_scope", name="uq_skill_employee_permissions"),
    )
    for name, cols in [
        ("ix_skill_employee_permissions_skill_id", ["skill_id"]),
        ("ix_skill_employee_permissions_skill_version_id", ["skill_version_id"]),
        ("ix_skill_employee_permissions_employee_id", ["employee_id"]),
        ("ix_skill_employee_permissions_department_id", ["department_id"]),
        ("ix_skill_employee_permissions_permission_scope", ["permission_scope"]),
        ("ix_skill_employee_permissions_allow", ["allow"]),
        ("ix_skill_employee_permissions_risk_limit", ["risk_limit"]),
        ("ix_skill_employee_permissions_environment_limit", ["environment_limit"]),
        ("ix_skill_employee_permissions_created_at", ["created_at"]),
    ]:
        op.create_index(name, "skill_employee_permissions", cols)

    op.create_table(
        "skill_invocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_version_id", sa.Integer(), sa.ForeignKey("skill_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("installation_id", sa.Integer(), sa.ForeignKey("skill_installations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("execution_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'待校验'")),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, cols in [
        ("ix_skill_invocations_skill_id", ["skill_id"]),
        ("ix_skill_invocations_skill_version_id", ["skill_version_id"]),
        ("ix_skill_invocations_installation_id", ["installation_id"]),
        ("ix_skill_invocations_employee_id", ["employee_id"]),
        ("ix_skill_invocations_task_id", ["task_id"]),
        ("ix_skill_invocations_execution_id", ["execution_id"]),
        ("ix_skill_invocations_status", ["status"]),
        ("ix_skill_invocations_error_code", ["error_code"]),
        ("ix_skill_invocations_trace_id", ["trace_id"]),
        ("ix_skill_invocations_created_at", ["created_at"]),
    ]:
        op.create_index(name, "skill_invocations", cols)

    op.create_table(
        "skill_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_version_id", sa.Integer(), sa.ForeignKey("skill_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision", sa.String(length=50), nullable=False),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=50), nullable=True),
        sa.Column("source_check_result", sa.Text(), nullable=True),
        sa.Column("sensitivity_check_result", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, cols in [
        ("ix_skill_reviews_skill_id", ["skill_id"]),
        ("ix_skill_reviews_skill_version_id", ["skill_version_id"]),
        ("ix_skill_reviews_reviewer_id", ["reviewer_id"]),
        ("ix_skill_reviews_decision", ["decision"]),
        ("ix_skill_reviews_risk_level", ["risk_level"]),
        ("ix_skill_reviews_reviewed_at", ["reviewed_at"]),
        ("ix_skill_reviews_created_at", ["created_at"]),
    ]:
        op.create_index(name, "skill_reviews", cols)

    op.create_table(
        "skill_capability_relations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_version_id", sa.Integer(), sa.ForeignKey("skill_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("capability_code", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("skill_id", "skill_version_id", "capability_code", name="uq_skill_capability_relations"),
    )
    for name, cols in [
        ("ix_skill_capability_relations_skill_id", ["skill_id"]),
        ("ix_skill_capability_relations_skill_version_id", ["skill_version_id"]),
        ("ix_skill_capability_relations_capability_code", ["capability_code"]),
        ("ix_skill_capability_relations_created_at", ["created_at"]),
    ]:
        op.create_index(name, "skill_capability_relations", cols)


def downgrade():
    for table in [
        "skill_capability_relations",
        "skill_reviews",
        "skill_invocations",
        "skill_employee_permissions",
        "skill_installations",
        "skill_versions",
        "skills",
    ]:
        op.drop_table(table)
