from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from .constants import DEFAULT_MAX_ACTIONS_PER_MINUTE, DEFAULT_MAX_DURATION_SECONDS, DEFAULT_MAX_RETRIES


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_budget(budget: dict | None) -> dict:
    budget = budget or {}
    return {
        "max_duration_seconds": int(budget.get("max_duration_seconds") or DEFAULT_MAX_DURATION_SECONDS),
        "max_actions_per_minute": int(budget.get("max_actions_per_minute") or DEFAULT_MAX_ACTIONS_PER_MINUTE),
        "max_retries": int(budget.get("max_retries") or DEFAULT_MAX_RETRIES),
    }


def ensure_budget_within_limits(workflow, *, executed_actions: int = 0) -> None:
    budget = workflow.execution_budget_json
    if not budget:
        return
    import json

    data = json.loads(budget)
    max_duration = int(data.get("max_duration_seconds") or DEFAULT_MAX_DURATION_SECONDS)
    max_actions_per_minute = int(data.get("max_actions_per_minute") or DEFAULT_MAX_ACTIONS_PER_MINUTE)
    if workflow.started_at and max_duration:
        elapsed = (utcnow() - workflow.started_at).total_seconds()
        if elapsed > max_duration:
            raise HTTPException(status_code=409, detail="工作流已超时")
    if executed_actions > max_actions_per_minute:
        raise HTTPException(status_code=409, detail="工作流动作预算已超限")
