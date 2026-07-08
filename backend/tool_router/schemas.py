from __future__ import annotations

from pydantic import BaseModel


class ToolRouterCheckPayload(BaseModel):
    employee_code: str
    tool_name: str
    boss_confirmed: bool = False
    security_audited: bool = False


class ToolRoutePayload(BaseModel):
    employee_code: str
    task: str
    requirement: str | None = None
    boss_confirmed: bool = False
    security_audited: bool = False

