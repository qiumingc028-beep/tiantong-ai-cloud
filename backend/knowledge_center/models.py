from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class KnowledgeAsset(Base):
    __tablename__ = "knowledge_assets"
    __table_args__ = (
        UniqueConstraint("knowledge_code", name="uq_knowledge_assets_code"),
    )

    knowledge_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    knowledge_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    knowledge_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="草稿", index=True)
    visibility: Mapped[str] = mapped_column(String(40), nullable=False, default="部门可见", index=True)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, default="低风险", index=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), index=True)
    owner_employee_id: Mapped[str | None] = mapped_column(String(64), index=True)
    owner_department: Mapped[str | None] = mapped_column(String(120), index=True)
    created_by: Mapped[str | None] = mapped_column(String(64), index=True)
    approved_by: Mapped[str | None] = mapped_column(String(64), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    source_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    primary_source_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cross_validated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    conflict_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unverified_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evidence_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    source_report_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source_execution_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False, index=True)

    versions: Mapped[list["KnowledgeVersion"]] = relationship(back_populates="knowledge", cascade="all, delete-orphan")


class KnowledgeVersion(Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (
        UniqueConstraint("knowledge_id", "version_number", name="uq_knowledge_versions_number"),
    )

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge_assets.knowledge_id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_format: Mapped[str] = mapped_column(String(40), nullable=False, default="markdown")
    change_summary: Mapped[str | None] = mapped_column(Text)
    change_reason: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str | None] = mapped_column(String(80), index=True)
    source_execution_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source_report_id: Mapped[str | None] = mapped_column(String(64), index=True)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_by: Mapped[str | None] = mapped_column(String(64), index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), index=True)
    approved_by: Mapped[str | None] = mapped_column(String(64), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False, index=True)

    knowledge: Mapped[KnowledgeAsset] = relationship(back_populates="versions")
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(back_populates="version", cascade="all, delete-orphan")


class KnowledgeSourceLink(Base):
    __tablename__ = "knowledge_source_links"

    link_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge_assets.knowledge_id", ondelete="CASCADE"), nullable=False, index=True)
    version_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_versions.version_id", ondelete="SET NULL"), index=True)
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    source_ref_id: Mapped[str | None] = mapped_column(String(64), index=True)
    source_title: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(Text)
    source_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    source_confidence_level: Mapped[str | None] = mapped_column(String(40), index=True)
    source_confidence_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_checked: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    evidence_id: Mapped[str | None] = mapped_column(String(64), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class KnowledgeReview(Base):
    __tablename__ = "knowledge_reviews"

    review_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge_assets.knowledge_id", ondelete="CASCADE"), nullable=False, index=True)
    version_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_versions.version_id", ondelete="SET NULL"), index=True)
    review_stage: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    review_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reviewer_employee_code: Mapped[str | None] = mapped_column(String(64), index=True)
    reviewer_name: Mapped[str | None] = mapped_column(String(120))
    review_comment: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str | None] = mapped_column(String(40), index=True)
    source_check_result: Mapped[str | None] = mapped_column(Text)
    sensitive_check_result: Mapped[str | None] = mapped_column(Text)
    prompt_injection_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    boss_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class KnowledgeTag(Base):
    __tablename__ = "knowledge_tags"
    __table_args__ = (
        UniqueConstraint("tag_code", name="uq_knowledge_tags_code"),
        UniqueConstraint("tag_name", name="uq_knowledge_tags_name"),
    )

    tag_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tag_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    tag_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tag_group: Mapped[str | None] = mapped_column(String(80), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False, index=True)


class KnowledgeTagRelation(Base):
    __tablename__ = "knowledge_tag_relations"
    __table_args__ = (
        UniqueConstraint("knowledge_id", "tag_id", name="uq_knowledge_tag_relations_knowledge_tag"),
    )

    relation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge_assets.knowledge_id", ondelete="CASCADE"), nullable=False, index=True)
    version_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_versions.version_id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[str] = mapped_column(ForeignKey("knowledge_tags.tag_id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    tag: Mapped[KnowledgeTag] = relationship()


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("knowledge_id", "version_id", "chunk_index", name="uq_knowledge_chunks_version_index"),
    )

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge_assets.knowledge_id", ondelete="CASCADE"), nullable=False, index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("knowledge_versions.version_id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    heading: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    version: Mapped[KnowledgeVersion] = relationship(back_populates="chunks")


class KnowledgeCitation(Base):
    __tablename__ = "knowledge_citations"

    citation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge_assets.knowledge_id", ondelete="CASCADE"), nullable=False, index=True)
    version_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_versions.version_id", ondelete="SET NULL"), index=True)
    chunk_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_chunks.chunk_id", ondelete="SET NULL"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), index=True)
    execution_id: Mapped[str | None] = mapped_column(String(64), index=True)
    employee_id: Mapped[str | None] = mapped_column(String(64), index=True)
    usage_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    query_text_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    citation_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
