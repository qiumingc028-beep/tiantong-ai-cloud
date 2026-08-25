from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Any


@dataclass
class AgentRuntimeOutcome:
    success: bool
    output: dict[str, Any]
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    metadata: dict[str, Any] | None = None

    @property
    def duration_ms(self) -> int | None:
        if not self.started_at or not self.finished_at:
            return None
        return max(0, int((self.finished_at - self.started_at).total_seconds() * 1000))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def invoke_agent_runtime(*, skill_code: str, employee_code: str, trace_id: str | None, handler: Callable[[], dict[str, Any]]) -> AgentRuntimeOutcome:
    started = utcnow()
    try:
        output = handler()
        finished = utcnow()
        return AgentRuntimeOutcome(
            success=True,
            output=output,
            started_at=started,
            finished_at=finished,
            metadata={"skill_code": skill_code, "employee_code": employee_code, "trace_id": trace_id, "bridge": "mock_agent_runtime"},
        )
    except Exception as exc:  # pragma: no cover - defensive bridge
        finished = utcnow()
        return AgentRuntimeOutcome(
            success=False,
            output={"error": "agent_runtime_failed"},
            error_code="AGENT_RUNTIME_FAILED",
            error_message=str(exc),
            started_at=started,
            finished_at=finished,
            metadata={"skill_code": skill_code, "employee_code": employee_code, "trace_id": trace_id, "bridge": "mock_agent_runtime"},
        )
