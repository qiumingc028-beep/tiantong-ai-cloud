from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IncidentAcknowledgeRequest(BaseModel):
    comment: str | None = Field(default=None, max_length=500)


class IncidentResolveRequest(BaseModel):
    resolution_summary: str | None = Field(default=None, max_length=1000)


class AlertRuleCreateRequest(BaseModel):
    中文名称: str = Field(min_length=1, max_length=120)
    rule_code: str = Field(min_length=1, max_length=80)
    metric_name: str = Field(min_length=1, max_length=120)
    condition: str = Field(min_length=1, max_length=40)
    threshold: str = Field(min_length=1, max_length=120)
    duration_seconds: int = Field(ge=0, le=86400)
    severity: str = Field(min_length=1, max_length=20)
    action: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    environment: str = Field(default="test", max_length=40)


class AlertRuleUpdateRequest(BaseModel):
    中文名称: str | None = Field(default=None, max_length=120)
    metric_name: str | None = Field(default=None, max_length=120)
    condition: str | None = Field(default=None, max_length=40)
    threshold: str | None = Field(default=None, max_length=120)
    duration_seconds: int | None = Field(default=None, ge=0, le=86400)
    severity: str | None = Field(default=None, max_length=20)
    action: str | None = Field(default=None, max_length=80)
    enabled: bool | None = None
    environment: str | None = Field(default=None, max_length=40)


class ObservabilityScoreView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    score_id: str
    scope_type: str
    scope_id: str
    score: int
    grade: str
    dimension_scores: dict[str, Any] = Field(default_factory=dict)
    deduction_reasons: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    explanation: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

