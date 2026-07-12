from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KnowledgeSubmissionRequest(BaseModel):
    submitter_employee_code: str = "tiancai_data"
    owner_employee_id: str | None = None
    owner_department: str | None = None
    title: str | None = None
    summary: str | None = None
    knowledge_type: str = "研究报告"
    category: str | None = None
    visibility: str = "部门可见"
    risk_level: str = "低风险"
    tags: list[str] = Field(default_factory=list)
    boss_confirmed: bool = False
    source_execution_id: str | None = None
    source_report_id: str | None = None


class KnowledgeDraftCreateRequest(BaseModel):
    title: str
    summary: str | None = None
    knowledge_type: str = "研究报告"
    category: str | None = None
    visibility: str = "部门可见"
    risk_level: str = "低风险"
    owner_employee_id: str | None = None
    owner_department: str | None = None
    content: str = ""
    tags: list[str] = Field(default_factory=list)


class KnowledgeDraftUpdateRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    knowledge_type: str | None = None
    category: str | None = None
    visibility: str | None = None
    risk_level: str | None = None
    owner_employee_id: str | None = None
    owner_department: str | None = None
    content: str | None = None
    tags: list[str] | None = None


class KnowledgeReviewRequest(BaseModel):
    reviewer_employee_code: str = "tiancang"
    review_comment: str | None = None
    boss_confirmed: bool = False
    sensitive_check_passed: bool = True


class KnowledgeCitationCreateRequest(BaseModel):
    task_id: int | None = None
    execution_id: str | None = None
    employee_id: str | None = None
    usage_type: str = "回答问题"
    query_text: str | None = None
    citation_summary: str | None = None
    chunk_id: str | None = None


class KnowledgeSearchQuery(BaseModel):
    q: str | None = None
    category: str | None = None
    tag: str | None = None
    knowledge_type: str | None = None
    status: str | None = None
    owner_department: str | None = None
    risk_level: str | None = None
    min_confidence: int | None = None
    limit: int = 20


class KnowledgeVersionView(BaseModel):
    version_id: str
    knowledge_id: str
    version_number: str
    title: str
    summary: str | None = None
    content: str
    content_format: str
    change_summary: str | None = None
    change_reason: str | None = None
    source_type: str | None = None
    source_execution_id: str | None = None
    source_report_id: str | None = None
    content_hash: str
    created_by: str | None = None
    reviewed_by: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime
    chunks: list[dict[str, Any]] = Field(default_factory=list)

