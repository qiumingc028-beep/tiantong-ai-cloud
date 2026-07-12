from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResearchTaskInput(BaseModel):
    topic: str = Field(min_length=1, max_length=300)
    goal: str = Field(min_length=1, max_length=500)
    max_queries: int | None = Field(default=None, ge=1)
    max_sources: int | None = Field(default=None, ge=1)
    time_range: str | None = None
    language: str = "zh-CN"
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    cross_validate: bool = True
    min_sources: int | None = Field(default=None, ge=1)
    report_format: str = "中文研究报告"
    task_title: str | None = None


class ResearchPlanStep(BaseModel):
    question: str
    query: str
    fields: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)


class ResearchPlan(BaseModel):
    topic: str
    goal: str
    max_queries: int
    max_sources: int
    min_sources: int
    language: str
    time_range: str | None = None
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    cross_validate: bool = True
    report_format: str = "中文研究报告"
    questions: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    steps: list[ResearchPlanStep] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    data_fields: list[str] = Field(default_factory=list)
    recommended_source_types: list[str] = Field(default_factory=list)
    maximum_duration_seconds: int = 300


class SearchResult(BaseModel):
    title: str
    url: str
    summary: str
    source_domain: str
    published_at: str | None = None
    search_rank: int
    provider: str
    query: str
    fetched_at: str


class SearchQueryRequest(BaseModel):
    query: str
    language: str = "zh-CN"
    time_range: str | None = None
    source_count: int = 5
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    safe_search: bool = True
    trace_id: str | None = None


class SearchQueryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[SearchResult] = Field(default_factory=list)


class ResearchSourceRecord(BaseModel):
    source_id: str
    title: str
    url: str
    redacted_url: str
    source_domain: str
    source_type: str
    confidence_level: str
    confidence_score: int
    confidence_reason: str
    content_hash: str
    is_primary: bool = False
    duplicate_of_source_id: str | None = None


class ResearchClaimRecord(BaseModel):
    claim_id: str
    claim_text: str
    validation_status: str
    confidence_level: str
    confidence_score: int
    support_source_ids: list[str] = Field(default_factory=list)
    conflict_source_ids: list[str] = Field(default_factory=list)
    evidence_count: int = 0


class ResearchEvidenceRecord(BaseModel):
    evidence_id: str
    source_id: str
    claim_id: str | None = None
    raw_url: str
    redacted_url: str
    page_title: str
    source_type: str
    confidence_level: str
    evidence_summary: str
    evidence_content_hash: str
    collected_at: datetime
    published_at: datetime | None = None
    relation_type: str = "support"
    validation_status: str = "已交叉验证"
    trace_id: str


class ResearchExecutionOutput(BaseModel):
    research_summary: str
    core_conclusions: list[str]
    structured_data: dict[str, Any] = Field(default_factory=dict)
    sources: list[ResearchSourceRecord] = Field(default_factory=list)
    evidence: list[ResearchEvidenceRecord] = Field(default_factory=list)
    source_reliability: dict[str, Any] = Field(default_factory=dict)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    security_events: list[str] = Field(default_factory=list)
    external_content_instruction_detected: bool = False
    collected_at: str
    trace_id: str
    report_hash: str
    report_content: str
    report_title: str = "公开信息研究报告"
    query_plan: dict[str, Any] = Field(default_factory=dict)
