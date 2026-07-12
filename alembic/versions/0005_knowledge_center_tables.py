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
    _create_index_if_missing("ix_knowledge_files_category", "knowledge_files", ["category"])
    _create_index_if_missing("ix_knowledge_files_status", "knowledge_files", ["status"])
    _create_index_if_missing("ix_knowledge_articles_category", "knowledge_articles", ["category"])
    _create_index_if_missing("ix_knowledge_articles_status", "knowledge_articles", ["status"])
    _create_index_if_missing("ix_sop_library_category", "sop_library", ["category"])
    _create_index_if_missing("ix_sop_library_status", "sop_library", ["status"])
    _create_index_if_missing("ix_prompt_library_category", "prompt_library", ["category"])
    _create_index_if_missing("ix_prompt_library_status", "prompt_library", ["status"])
    _create_index_if_missing("ix_bug_cases_category", "bug_cases", ["category"])
    _create_index_if_missing("ix_bug_cases_status", "bug_cases", ["status"])
    _create_index_if_missing("ix_course_lessons_category", "course_lessons", ["category"])
    _create_index_if_missing("ix_course_lessons_status", "course_lessons", ["status"])


def downgrade():
    for name, table in [
        ("ix_course_lessons_status", "course_lessons"),
        ("ix_course_lessons_category", "course_lessons"),
        ("ix_bug_cases_status", "bug_cases"),
        ("ix_bug_cases_category", "bug_cases"),
        ("ix_prompt_library_status", "prompt_library"),
        ("ix_prompt_library_category", "prompt_library"),
        ("ix_sop_library_status", "sop_library"),
        ("ix_sop_library_category", "sop_library"),
        ("ix_knowledge_articles_status", "knowledge_articles"),
        ("ix_knowledge_articles_category", "knowledge_articles"),
        ("ix_knowledge_files_status", "knowledge_files"),
        ("ix_knowledge_files_category", "knowledge_files"),
    ]:
        if _has_table(table):
            op.drop_index(name, table_name=table)
