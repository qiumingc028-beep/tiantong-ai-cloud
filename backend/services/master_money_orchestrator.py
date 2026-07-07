from __future__ import annotations

from datetime import datetime, timezone

from .auto_profit_loop import run_profit_cycle
from .revenue_feedback_loop import optimize_strategy


STATE = {
    "running": False,
    "last_started_at": None,
    "last_stopped_at": None,
    "cycle_count": 0,
    "last_result": None,
    "strategy": {},
}


def start_loop(seed: dict, cycles: int = 1) -> dict:
    safe_cycles = max(1, min(int(cycles or 1), 10))
    STATE["running"] = True
    STATE["last_started_at"] = datetime.now(timezone.utc).isoformat()
    results = []
    strategy = STATE.get("strategy") or {}
    for _ in range(safe_cycles):
        cycle_index = int(STATE.get("cycle_count") or 0) + 1
        result = run_profit_cycle(seed, cycle_index, strategy)
        results.append(result)
        strategy = result["next_strategy"]
        STATE["cycle_count"] = cycle_index
        STATE["last_result"] = result
        STATE["strategy"] = strategy
    return status(extra={"results": results})


def stop_loop() -> dict:
    STATE["running"] = False
    STATE["last_stopped_at"] = datetime.now(timezone.utc).isoformat()
    return status()


def status(extra: dict | None = None) -> dict:
    payload = {
        "running": bool(STATE.get("running")),
        "cycle_count": int(STATE.get("cycle_count") or 0),
        "last_started_at": STATE.get("last_started_at"),
        "last_stopped_at": STATE.get("last_stopped_at"),
        "last_result": STATE.get("last_result"),
        "strategy": STATE.get("strategy") or {},
        "external_execution": False,
        "mode": "bounded_internal_auto_loop",
    }
    if extra:
        payload.update(extra)
    return payload


def optimize(payload: dict) -> dict:
    feedback = payload.get("feedback") if isinstance(payload.get("feedback"), dict) else payload
    strategy = optimize_strategy(feedback)
    STATE["strategy"] = strategy
    return {"strategy": strategy, "status": status(), "external_execution": False}
