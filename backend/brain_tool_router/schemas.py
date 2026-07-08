from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyzePayload(BaseModel):
    request_text: str = Field(min_length=1, max_length=2000)


class TaskIntent(BaseModel):
    task_id: str
    goal: str
    employee_code: str
    employee_role: str
    required_tools: list[str]
    risk_level: str
    approval_required: bool
    execution_plan: list[str]


class PlanPayload(BaseModel):
    request_text: str = Field(min_length=1, max_length=2000)
    task_id: str | None = None
    employee_code: str | None = None
    boss_confirmed: bool = False
    security_audited: bool = False


class ApprovalCheckPayload(BaseModel):
    risk_level: str
    boss_confirmed: bool = False
    security_audited: bool = False
    task_id: str | None = None
    employee_code: str | None = None

