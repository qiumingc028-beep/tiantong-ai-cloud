from __future__ import annotations

from typing import Any

from .business_detector import detect_business_signals
from .opportunity_engine import build_opportunities


def monitor_business_state(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    signals = detect_business_signals(snapshot)
    opportunities = build_opportunities(signals)
    return {
        "mode": "autonomous_business_monitor",
        "signals": signals,
        "opportunities": opportunities,
        "task_lifecycle": ["discovered", "analysis", "decision", "approval", "execution", "review", "learning"],
        "requires_command_center": True,
        "requires_orchestrator": True,
        "requires_tian_shen": True,
        "requires_tian_brain": True,
    }
