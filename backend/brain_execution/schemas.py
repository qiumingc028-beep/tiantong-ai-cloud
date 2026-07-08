from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyzePayload(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)


class PlanPayload(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    boss_confirm: bool = False
    security_audited: bool = False


class ApprovePayload(BaseModel):
    execution_id: int
    decision: str = "approved"
    reason: str | None = None
    boss_confirm: bool = False
    security_audited: bool = False


class StartPayload(BaseModel):
    execution_id: int

