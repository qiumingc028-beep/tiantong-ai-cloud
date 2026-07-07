from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


DECISION_MEMORY: list[dict[str, Any]] = []
MAX_DECISION_MEMORY = 100


def record_decision(decision: dict[str, Any]) -> dict[str, Any]:
    row = {
        **decision,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "memory_scope": "in_process_readonly_decision_memory",
    }
    DECISION_MEMORY.insert(0, row)
    del DECISION_MEMORY[MAX_DECISION_MEMORY:]
    return row


def list_decisions(limit: int = 20) -> list[dict[str, Any]]:
    safe_limit = min(max(int(limit or 20), 1), MAX_DECISION_MEMORY)
    return DECISION_MEMORY[:safe_limit]


def clear_decisions() -> None:
    DECISION_MEMORY.clear()
