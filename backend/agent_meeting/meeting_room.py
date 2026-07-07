from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.agent_meeting.collaboration_engine import run_ai_meeting


MEETING_MEMORY: list[dict[str, Any]] = []
MAX_MEETINGS = 100


def create_meeting(goal: str, context: dict[str, Any] | None = None, invitees: list[str] | None = None) -> dict[str, Any]:
    meeting = run_ai_meeting(goal, context, invitees)
    record = {
        **meeting,
        "meeting_id": f"meeting-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "discussion_completed",
    }
    MEETING_MEMORY.insert(0, record)
    del MEETING_MEMORY[MAX_MEETINGS:]
    return record


def list_meetings(limit: int = 20) -> list[dict[str, Any]]:
    safe_limit = min(max(int(limit or 20), 1), MAX_MEETINGS)
    return MEETING_MEMORY[:safe_limit]


def clear_meetings() -> None:
    MEETING_MEMORY.clear()
