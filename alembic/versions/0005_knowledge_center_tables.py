"""knowledge center tables

Revision ID: 0005_knowledge_center_tables
Revises: 0004_jd_sync_runtime
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "0005_knowledge_center_tables"
down_revision = "0004_jd_sync_runtime"
branch_labels = None
depends_on = None


def upgrade():
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
    op.create_index("ix_knowledge_files_category", "knowledge_files", ["category"])
    op.create_index("ix_knowledge_files_status", "knowledge_files", ["status"])

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
    op.create_index("ix_knowledge_articles_category", "knowledge_articles", ["category"])
    op.create_index("ix_knowledge_articles_status", "knowledge_articles", ["status"])

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
    op.create_index("ix_sop_library_category", "sop_library", ["category"])
    op.create_index("ix_sop_library_status", "sop_library", ["status"])

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
    op.create_index("ix_prompt_library_category", "prompt_library", ["category"])
    op.create_index("ix_prompt_library_status", "prompt_library", ["status"])

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
    op.create_index("ix_bug_cases_category", "bug_cases", ["category"])
    op.create_index("ix_bug_cases_status", "bug_cases", ["status"])

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
    op.create_index("ix_course_lessons_category", "course_lessons", ["category"])
    op.create_index("ix_course_lessons_status", "course_lessons", ["status"])


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
