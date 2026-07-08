from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class SprintRecord(BaseModel):
    id: str
    sprint_name: str
    sprint_version: str
    owner: list[str] = Field(default_factory=list)
    commit_id: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    test_result: str | None = None
    deployment_status: str | None = None
    risk_notes: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SprintSummaryPayload(BaseModel):
    sprint_name: str
    sprint_version: str
    owner: list[str] = Field(default_factory=list)
    commit_id: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    test_result: str | None = None
    deployment_status: str | None = None
    risk_notes: list[str] = Field(default_factory=list)
    codex_output: str | None = None


class DraftResponse(BaseModel):
    sprint_record: SprintRecord
    drafts: dict[str, str]
    saved: bool = False
    requires_boss_confirmation: bool = True
    safety: dict[str, bool | list[str]]
