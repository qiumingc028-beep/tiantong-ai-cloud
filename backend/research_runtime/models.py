from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class ResearchExecution(Base):
    __tablename__ = "research_executions"
    __table_args__ = (UniqueConstraint("trace_id", name="uq_research_executions_trace_id"),)

    execution_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True, index=True)
    capability_id: Mapped[str] = mapped_column(ForeignKey("agent_capabilities.capability_id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="planned", index=True)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, default="low", index=True)
    approval_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_required", index=True)
    executor_type: Mapped[str] = mapped_column(String(40), nullable=False, default="research", index=True)
    research_topic: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    research_goal: Mapped[str] = mapped_column(Text, nullable=False)
    plan_json: Mapped[str | None] = mapped_column(Text)
    query_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conclusion_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflict_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uncertainty_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    report_title: Mapped[str | None] = mapped_column(String(200))
    report_content: Mapped[str | None] = mapped_column(Text)
    report_hash: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ResearchQuery(Base):
    __tablename__ = "research_queries"

    query_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("research_executions.execution_id", ondelete="CASCADE"), nullable=False, index=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(40), nullable=False, default="zh-CN")
    time_range: Mapped[str | None] = mapped_column(String(80))
    provider_name: Mapped[str] = mapped_column(String(80), nullable=False)
    allow_domains_json: Mapped[str | None] = mapped_column(Text)
    blocked_domains_json: Mapped[str | None] = mapped_column(Text)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="collected", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ResearchSource(Base):
    __tablename__ = "research_sources"

    source_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("research_executions.execution_id", ondelete="CASCADE"), nullable=False, index=True)
    query_id: Mapped[str | None] = mapped_column(ForeignKey("research_queries.query_id", ondelete="SET NULL"), nullable=True, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    redacted_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    confidence_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence_reason: Mapped[str | None] = mapped_column(Text)
    publication_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    content_excerpt: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    duplicate_of_source_id: Mapped[str | None] = mapped_column(String(36))
    provider_name: Mapped[str] = mapped_column(String(80), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False, default="已交叉验证", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ResearchClaim(Base):
    __tablename__ = "research_claims"

    claim_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("research_executions.execution_id", ondelete="CASCADE"), nullable=False, index=True)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_status: Mapped[str] = mapped_column(String(40), nullable=False, default="candidate")
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False, default="单一来源", index=True)
    confidence_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    support_source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflict_source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    support_source_ids_json: Mapped[str | None] = mapped_column(Text)
    conflict_source_ids_json: Mapped[str | None] = mapped_column(Text)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ResearchEvidence(Base):
    __tablename__ = "research_evidence"

    evidence_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("research_executions.execution_id", ondelete="CASCADE"), nullable=False, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("research_sources.source_id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id: Mapped[str | None] = mapped_column(ForeignKey("research_claims.claim_id", ondelete="SET NULL"), nullable=True, index=True)
    raw_url: Mapped[str] = mapped_column(Text, nullable=False)
    redacted_url: Mapped[str] = mapped_column(Text, nullable=False)
    page_title: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    confidence_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    citation_summary: Mapped[str | None] = mapped_column(Text)
    evidence_content_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    relation_type: Mapped[str] = mapped_column(String(30), nullable=False, default="support", index=True)
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False, default="已交叉验证", index=True)
    trace_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
