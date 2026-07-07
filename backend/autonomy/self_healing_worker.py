from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def detect_worker_error(item: dict[str, Any], exc: Exception) -> dict[str, Any]:
    message = str(exc)
    plan = build_healing_plan(message)
    return {
        "detected": True,
        "error_type": type(exc).__name__,
        "message": message,
        "plan": plan,
        "retry_recommended": plan["retry_recommended"],
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }


def build_healing_plan(message: str) -> dict[str, Any]:
    lower = message.lower()
    if "timeout" in lower or "redis" in lower:
        return {
            "category": "transient_queue_error",
            "action": "retry_with_backoff",
            "retry_recommended": True,
            "repair_steps": ["record warning", "keep worker alive", "requeue task"],
        }
    if "not found" in lower:
        return {
            "category": "missing_dependency_or_record",
            "action": "stop_after_audit",
            "retry_recommended": False,
            "repair_steps": ["record failure", "require upstream data repair"],
        }
    return {
        "category": "generic_worker_error",
        "action": "retry_once_then_escalate",
        "retry_recommended": True,
        "repair_steps": ["capture error", "requeue task", "escalate if repeated"],
    }
