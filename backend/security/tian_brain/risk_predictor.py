from __future__ import annotations

import json
import re
from typing import Any

from backend.security.tian_shen.audit import read_audit_records


def predict_risk(
    event: dict[str, Any],
    route: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    audit_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    route_payload = route if isinstance(route, dict) else {}
    policy_data = policy if isinstance(policy, dict) else {}
    text = event_text(event, route_payload)
    records = audit_records if audit_records is not None else read_audit_records(limit=200)

    red_keywords = [str(keyword).lower() for keyword in (policy_data.get("red") or {}).get("keywords", [])]
    yellow_keywords = [str(keyword).lower() for keyword in (policy_data.get("yellow") or {}).get("keywords", [])]
    yellow_sources = [str(source).lower() for source in (policy_data.get("yellow") or {}).get("sources", [])]
    matched_red = sorted(keyword for keyword in red_keywords if matches_policy_keyword(keyword, text))
    matched_yellow = sorted(keyword for keyword in yellow_keywords if matches_policy_keyword(keyword, text))
    matched_sources = sorted(source for source in yellow_sources if matches_policy_keyword(source, text))
    historical_blocks = count_historical_blocks(event, records)

    score = 0
    signals = []
    if matched_red:
        score += 90
        signals.append("matched_red_keywords")
    if matched_yellow or matched_sources:
        score += 45
        signals.append("matched_yellow_rules")
    if historical_blocks:
        score += min(30, historical_blocks * 10)
        signals.append("historical_blocks")

    if score >= 80:
        predicted_level = "RED"
    elif score >= 30:
        predicted_level = "YELLOW"
    else:
        predicted_level = "GREEN"

    return {
        "center": "TianBrain",
        "predicted_level": predicted_level,
        "risk_score": min(score, 100),
        "signals": signals or ["low_risk_pattern"],
        "matched_red_keywords": matched_red,
        "matched_yellow_keywords": matched_yellow,
        "matched_sources": matched_sources,
        "historical_blocks": historical_blocks,
    }


def count_historical_blocks(event: dict[str, Any], records: list[dict[str, Any]]) -> int:
    payload = event.get("payload")
    command = event.get("command")
    if not command and isinstance(payload, dict):
        command = payload.get("command")
    if not command:
        command = event.get("action") or ""
    source = str(event.get("source") or "unknown")
    return sum(1 for row in records if row.get("source") == source and row.get("command") == command and not row.get("allowed"))


def event_text(event: dict[str, Any], route: dict[str, Any]) -> str:
    payload = {
        "source": event.get("source"),
        "target": event.get("target"),
        "action": event.get("action"),
        "tool": event.get("tool"),
        "command": event.get("command"),
        "route": route,
        "payload": event.get("payload"),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).lower()


def matches_policy_keyword(keyword: str, text: str) -> bool:
    if not keyword:
        return False
    if keyword.isalnum() and len(keyword) <= 3:
        return keyword in set(re.findall(r"[a-z0-9]+", text))
    return keyword in text
