"""knowledge center tables

Revision ID: 0005_knowledge_center_tables
Revises: 0005_tiancang_knowledge_tables
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "0005_knowledge_center_tables"
down_revision = "0005_tiancang_knowledge_tables"
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
    if not _has_table("knowledge_files"):
        op.create_table(
            "knowledge_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("original_name", sa.String(255)),
            sa.Column("file_path", sa.Text()),
            sa.Column("file_type", sa.String(100)),
            sa.Column("content_type", sa.String(100)),
            sa.Column("file_size", sa.Integer(), default=0),
            sa.Column("content_text", sa.Text()),
            sa.Column("summary", sa.Text()),
            sa.Column("ai_tags", sa.Text()),
            sa.Column("category", sa.String(100)),
            sa.Column("status", sa.String(50), server_default="draft"),
            sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_knowledge_files_category", "knowledge_files", ["category"])
    _create_index_if_missing("ix_knowledge_files_status", "knowledge_files", ["status"])

    if not _has_table("knowledge_articles"):
        op.create_table(
            "knowledge_articles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("file_id", sa.Integer(), sa.ForeignKey("knowledge_files.id", ondelete="SET NULL")),
            sa.Column("source_file_id", sa.Integer(), sa.ForeignKey("knowledge_files.id", ondelete="SET NULL")),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("summary", sa.Text()),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("category", sa.String(100)),
            sa.Column("tags", sa.Text()),
            sa.Column("status", sa.String(50), server_default="draft"),
            sa.Column("published_at", sa.DateTime(timezone=True)),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_knowledge_articles_category", "knowledge_articles", ["category"])
    _create_index_if_missing("ix_knowledge_articles_status", "knowledge_articles", ["status"])

    if not _has_table("sop_library"):
        op.create_table(
            "sop_library",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("article_id", sa.Integer(), sa.ForeignKey("knowledge_articles.id", ondelete="SET NULL")),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("department", sa.String(100)),
            sa.Column("content", sa.Text()),
            sa.Column("category", sa.String(100)),
            sa.Column("steps", sa.Text()),
            sa.Column("status", sa.String(50), server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_sop_library_category", "sop_library", ["category"])
    _create_index_if_missing("ix_sop_library_status", "sop_library", ["status"])

    if not _has_table("prompt_library"):
        op.create_table(
            "prompt_library",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("article_id", sa.Integer(), sa.ForeignKey("knowledge_articles.id", ondelete="SET NULL")),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("prompt_type", sa.String(100)),
            sa.Column("category", sa.String(100)),
            sa.Column("content", sa.Text()),
            sa.Column("model", sa.String(100)),
            sa.Column("version", sa.String(50)),
            sa.Column("prompt_text", sa.Text()),
            sa.Column("usage_notes", sa.Text()),
            sa.Column("status", sa.String(50), server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_prompt_library_category", "prompt_library", ["category"])
    _create_index_if_missing("ix_prompt_library_status", "prompt_library", ["status"])

    if not _has_table("bug_cases"):
        op.create_table(
            "bug_cases",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("article_id", sa.Integer(), sa.ForeignKey("knowledge_articles.id", ondelete="SET NULL")),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("reason", sa.Text()),
            sa.Column("impact_scope", sa.String(255)),
            sa.Column("category", sa.String(100)),
            sa.Column("symptom", sa.Text()),
            sa.Column("root_cause", sa.Text()),
            sa.Column("solution", sa.Text()),
            sa.Column("status", sa.String(50), server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_bug_cases_category", "bug_cases", ["category"])
    _create_index_if_missing("ix_bug_cases_status", "bug_cases", ["status"])

    if not _has_table("course_lessons"):
        op.create_table(
            "course_lessons",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("article_id", sa.Integer(), sa.ForeignKey("knowledge_articles.id", ondelete="SET NULL")),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("course_name", sa.String(255)),
            sa.Column("category", sa.String(100)),
            sa.Column("outline", sa.Text()),
            sa.Column("content", sa.Text()),
            sa.Column("lesson_order", sa.Integer(), default=0),
            sa.Column("target_audience", sa.String(255)),
            sa.Column("status", sa.String(50), server_default="draft"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_course_lessons_category", "course_lessons", ["category"])
    _create_index_if_missing("ix_course_lessons_status", "course_lessons", ["status"])


def downgrade():
    op.drop_index("ix_course_lessons_status", table_name="course_lessons")
    op.drop_index("ix_course_lessons_category", table_name="course_lessons")
    op.drop_table("course_lessons")
    op.drop_index("ix_bug_cases_status", table_name="bug_cases")
    op.drop_index("ix_bug_cases_category", table_name="bug_cases")
    op.drop_table("bug_cases")
    op.drop_index("ix_prompt_library_status", table_name="prompt_library")
    op.drop_index("ix_prompt_library_category", table_name="prompt_library")
    op.drop_table("prompt_library")
    op.drop_index("ix_sop_library_status", table_name="sop_library")
    op.drop_index("ix_sop_library_category", table_name="sop_library")
    op.drop_table("sop_library")
    op.drop_index("ix_knowledge_articles_status", table_name="knowledge_articles")
    op.drop_index("ix_knowledge_articles_category", table_name="knowledge_articles")
    op.drop_table("knowledge_articles")
    op.drop_index("ix_knowledge_files_status", table_name="knowledge_files")
    op.drop_index("ix_knowledge_files_category", table_name="knowledge_files")
    op.drop_table("knowledge_files")
