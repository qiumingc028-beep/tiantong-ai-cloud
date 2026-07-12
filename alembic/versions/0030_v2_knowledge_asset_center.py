"""v2 knowledge asset center foundation

Revision ID: 0030_v2_knowledge_asset_center
Revises: 0029_v2_public_research_workflow
Create Date: 2026-07-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0030_v2_knowledge_asset_center"
down_revision = "0029_v2_public_research_workflow"
branch_labels = None
depends_on = None


def _create_single_column_indexes(table_name: str, columns: list[str]) -> None:
    for column in columns:
        op.create_index(f"ix_{table_name}_{column}", table_name, [column])


def upgrade():
    op.create_table(
        "knowledge_assets",
        sa.Column("knowledge_id", sa.String(length=36), primary_key=True),
        sa.Column("knowledge_code", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("knowledge_type", sa.String(length=60), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="草稿"),
        sa.Column("visibility", sa.String(length=40), nullable=False, server_default="部门可见"),
        sa.Column("risk_level", sa.String(length=40), nullable=False, server_default="低风险"),
        sa.Column("current_version_id", sa.String(length=36), nullable=True),
        sa.Column("owner_employee_id", sa.String(length=64), nullable=True),
        sa.Column("owner_department", sa.String(length=120), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("approved_by", sa.String(length=64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("primary_source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cross_validated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unverified_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_hash", sa.String(length=128), nullable=True),
        sa.Column("source_report_id", sa.String(length=64), nullable=True),
        sa.Column("source_execution_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("knowledge_code", name="uq_knowledge_assets_code"),
    )
    _create_single_column_indexes(
        "knowledge_assets",
        [
            "knowledge_code",
            "title",
            "knowledge_type",
            "category",
            "status",
            "visibility",
            "risk_level",
            "current_version_id",
            "owner_employee_id",
            "owner_department",
            "created_by",
            "approved_by",
            "published_at",
            "archived_at",
            "evidence_hash",
            "source_report_id",
            "source_execution_id",
            "created_at",
            "updated_at",
        ],
    )

    op.create_table(
        "knowledge_versions",
        sa.Column("version_id", sa.String(length=36), primary_key=True),
        sa.Column("knowledge_id", sa.String(length=36), sa.ForeignKey("knowledge_assets.knowledge_id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_format", sa.String(length=40), nullable=False, server_default="markdown"),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=80), nullable=True),
        sa.Column("source_execution_id", sa.String(length=64), nullable=True),
        sa.Column("source_report_id", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("reviewed_by", sa.String(length=64), nullable=True),
        sa.Column("approved_by", sa.String(length=64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("knowledge_id", "version_number", name="uq_knowledge_versions_number"),
    )
    _create_single_column_indexes(
        "knowledge_versions",
        [
            "knowledge_id",
            "version_number",
            "source_type",
            "source_execution_id",
            "source_report_id",
            "content_hash",
            "created_by",
            "reviewed_by",
            "approved_by",
            "created_at",
            "updated_at",
        ],
    )

    op.create_table(
        "knowledge_source_links",
        sa.Column("link_id", sa.String(length=36), primary_key=True),
        sa.Column("knowledge_id", sa.String(length=36), sa.ForeignKey("knowledge_assets.knowledge_id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.String(length=36), sa.ForeignKey("knowledge_versions.version_id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_kind", sa.String(length=80), nullable=False),
        sa.Column("source_ref_id", sa.String(length=64), nullable=True),
        sa.Column("source_title", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_hash", sa.String(length=128), nullable=True),
        sa.Column("source_confidence_level", sa.String(length=40), nullable=True),
        sa.Column("source_confidence_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source_checked", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("evidence_id", sa.String(length=64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    _create_single_column_indexes(
        "knowledge_source_links",
        [
            "knowledge_id",
            "version_id",
            "source_kind",
            "source_ref_id",
            "source_hash",
            "source_confidence_level",
            "evidence_id",
            "created_at",
        ],
    )

    op.create_table(
        "knowledge_reviews",
        sa.Column("review_id", sa.String(length=36), primary_key=True),
        sa.Column("knowledge_id", sa.String(length=36), sa.ForeignKey("knowledge_assets.knowledge_id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.String(length=36), sa.ForeignKey("knowledge_versions.version_id", ondelete="SET NULL"), nullable=True),
        sa.Column("review_stage", sa.String(length=40), nullable=False),
        sa.Column("review_status", sa.String(length=40), nullable=False),
        sa.Column("reviewer_employee_code", sa.String(length=64), nullable=True),
        sa.Column("reviewer_name", sa.String(length=120), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=40), nullable=True),
        sa.Column("source_check_result", sa.Text(), nullable=True),
        sa.Column("sensitive_check_result", sa.Text(), nullable=True),
        sa.Column("prompt_injection_detected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("boss_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    _create_single_column_indexes(
        "knowledge_reviews",
        [
            "knowledge_id",
            "version_id",
            "review_stage",
            "review_status",
            "reviewer_employee_code",
            "risk_level",
            "created_at",
        ],
    )

    op.create_table(
        "knowledge_tags",
        sa.Column("tag_id", sa.String(length=36), primary_key=True),
        sa.Column("tag_code", sa.String(length=80), nullable=False),
        sa.Column("tag_name", sa.String(length=100), nullable=False),
        sa.Column("tag_group", sa.String(length=80), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tag_code", name="uq_knowledge_tags_code"),
        sa.UniqueConstraint("tag_name", name="uq_knowledge_tags_name"),
    )
    _create_single_column_indexes("knowledge_tags", ["tag_code", "tag_name", "tag_group", "enabled", "created_at", "updated_at"])

    op.create_table(
        "knowledge_tag_relations",
        sa.Column("relation_id", sa.String(length=36), primary_key=True),
        sa.Column("knowledge_id", sa.String(length=36), sa.ForeignKey("knowledge_assets.knowledge_id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.String(length=36), sa.ForeignKey("knowledge_versions.version_id", ondelete="CASCADE"), nullable=True),
        sa.Column("tag_id", sa.String(length=36), sa.ForeignKey("knowledge_tags.tag_id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("knowledge_id", "tag_id", name="uq_knowledge_tag_relations_knowledge_tag"),
    )
    _create_single_column_indexes("knowledge_tag_relations", ["knowledge_id", "version_id", "tag_id", "created_at"])

    op.create_table(
        "knowledge_chunks",
        sa.Column("chunk_id", sa.String(length=64), primary_key=True),
        sa.Column("knowledge_id", sa.String(length=36), sa.ForeignKey("knowledge_assets.knowledge_id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.String(length=36), sa.ForeignKey("knowledge_versions.version_id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("knowledge_id", "version_id", "chunk_index", name="uq_knowledge_chunks_version_index"),
    )
    _create_single_column_indexes("knowledge_chunks", ["knowledge_id", "version_id", "chunk_index", "content_hash", "created_at"])

    op.create_table(
        "knowledge_citations",
        sa.Column("citation_id", sa.String(length=36), primary_key=True),
        sa.Column("knowledge_id", sa.String(length=36), sa.ForeignKey("knowledge_assets.knowledge_id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.String(length=36), sa.ForeignKey("knowledge_versions.version_id", ondelete="SET NULL"), nullable=True),
        sa.Column("chunk_id", sa.String(length=64), sa.ForeignKey("knowledge_chunks.chunk_id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("execution_id", sa.String(length=64), nullable=True),
        sa.Column("employee_id", sa.String(length=64), nullable=True),
        sa.Column("usage_type", sa.String(length=80), nullable=False),
        sa.Column("query_text_hash", sa.String(length=128), nullable=False),
        sa.Column("citation_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    _create_single_column_indexes(
        "knowledge_citations",
        ["knowledge_id", "version_id", "chunk_id", "task_id", "execution_id", "employee_id", "usage_type", "query_text_hash", "created_at"],
    )


def downgrade():
    op.drop_index("ix_knowledge_citations_created_at", table_name="knowledge_citations")
    op.drop_index("ix_knowledge_citations_query_text_hash", table_name="knowledge_citations")
    op.drop_index("ix_knowledge_citations_usage_type", table_name="knowledge_citations")
    op.drop_index("ix_knowledge_citations_employee_id", table_name="knowledge_citations")
    op.drop_index("ix_knowledge_citations_execution_id", table_name="knowledge_citations")
    op.drop_index("ix_knowledge_citations_task_id", table_name="knowledge_citations")
    op.drop_index("ix_knowledge_citations_chunk_id", table_name="knowledge_citations")
    op.drop_index("ix_knowledge_citations_version_id", table_name="knowledge_citations")
    op.drop_index("ix_knowledge_citations_knowledge_id", table_name="knowledge_citations")
    op.drop_table("knowledge_citations")

    op.drop_index("ix_knowledge_chunks_created_at", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_content_hash", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_chunk_index", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_version_id", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_knowledge_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")

    op.drop_index("ix_knowledge_tag_relations_created_at", table_name="knowledge_tag_relations")
    op.drop_index("ix_knowledge_tag_relations_tag_id", table_name="knowledge_tag_relations")
    op.drop_index("ix_knowledge_tag_relations_version_id", table_name="knowledge_tag_relations")
    op.drop_index("ix_knowledge_tag_relations_knowledge_id", table_name="knowledge_tag_relations")
    op.drop_table("knowledge_tag_relations")

    op.drop_index("ix_knowledge_tags_updated_at", table_name="knowledge_tags")
    op.drop_index("ix_knowledge_tags_created_at", table_name="knowledge_tags")
    op.drop_index("ix_knowledge_tags_enabled", table_name="knowledge_tags")
    op.drop_index("ix_knowledge_tags_tag_group", table_name="knowledge_tags")
    op.drop_index("ix_knowledge_tags_tag_name", table_name="knowledge_tags")
    op.drop_index("ix_knowledge_tags_tag_code", table_name="knowledge_tags")
    op.drop_table("knowledge_tags")

    op.drop_index("ix_knowledge_reviews_created_at", table_name="knowledge_reviews")
    op.drop_index("ix_knowledge_reviews_risk_level", table_name="knowledge_reviews")
    op.drop_index("ix_knowledge_reviews_reviewer_employee_code", table_name="knowledge_reviews")
    op.drop_index("ix_knowledge_reviews_review_status", table_name="knowledge_reviews")
    op.drop_index("ix_knowledge_reviews_review_stage", table_name="knowledge_reviews")
    op.drop_index("ix_knowledge_reviews_version_id", table_name="knowledge_reviews")
    op.drop_index("ix_knowledge_reviews_knowledge_id", table_name="knowledge_reviews")
    op.drop_table("knowledge_reviews")

    op.drop_index("ix_knowledge_source_links_created_at", table_name="knowledge_source_links")
    op.drop_index("ix_knowledge_source_links_evidence_id", table_name="knowledge_source_links")
    op.drop_index("ix_knowledge_source_links_source_confidence_level", table_name="knowledge_source_links")
    op.drop_index("ix_knowledge_source_links_source_hash", table_name="knowledge_source_links")
    op.drop_index("ix_knowledge_source_links_source_kind", table_name="knowledge_source_links")
    op.drop_index("ix_knowledge_source_links_source_ref_id", table_name="knowledge_source_links")
    op.drop_index("ix_knowledge_source_links_version_id", table_name="knowledge_source_links")
    op.drop_index("ix_knowledge_source_links_knowledge_id", table_name="knowledge_source_links")
    op.drop_table("knowledge_source_links")

    op.drop_index("ix_knowledge_versions_updated_at", table_name="knowledge_versions")
    op.drop_index("ix_knowledge_versions_created_at", table_name="knowledge_versions")
    op.drop_index("ix_knowledge_versions_approved_by", table_name="knowledge_versions")
    op.drop_index("ix_knowledge_versions_reviewed_by", table_name="knowledge_versions")
    op.drop_index("ix_knowledge_versions_created_by", table_name="knowledge_versions")
    op.drop_index("ix_knowledge_versions_content_hash", table_name="knowledge_versions")
    op.drop_index("ix_knowledge_versions_source_report_id", table_name="knowledge_versions")
    op.drop_index("ix_knowledge_versions_source_execution_id", table_name="knowledge_versions")
    op.drop_index("ix_knowledge_versions_source_type", table_name="knowledge_versions")
    op.drop_index("ix_knowledge_versions_version_number", table_name="knowledge_versions")
    op.drop_index("ix_knowledge_versions_knowledge_id", table_name="knowledge_versions")
    op.drop_table("knowledge_versions")

    op.drop_index("ix_knowledge_assets_updated_at", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_created_at", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_source_execution_id", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_source_report_id", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_evidence_hash", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_archived_at", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_published_at", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_approved_by", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_created_by", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_owner_department", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_owner_employee_id", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_current_version_id", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_risk_level", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_visibility", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_status", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_category", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_knowledge_type", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_title", table_name="knowledge_assets")
    op.drop_index("ix_knowledge_assets_knowledge_code", table_name="knowledge_assets")
    op.drop_table("knowledge_assets")
