from __future__ import annotations

import json
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_AUDIT_LOG_PATH = "/tmp/tiantong_tian_shen_audit.log"
HISTORY_WINDOW = 200


def audit_scope(event: dict[str, Any]) -> dict[str, Any] | None:
    """Only complete server-provided ownership may select risk history."""
    scope = event.get("audit_scope")
    if not isinstance(scope, dict):
        return None
    integer_fields = ("tenant_id", "company_id", "requester_id")
    string_fields = ("store_scope_key", "ownership_scope_key")
    if any(type(scope.get(key)) is not int or scope[key] <= 0 for key in integer_fields):
        return None
    if any(type(scope.get(key)) is not str or not scope[key] for key in string_fields):
        return None
    return {key: scope[key] for key in (*integer_fields, *string_fields)}


def matches_audit_event(record: dict[str, Any], event: dict[str, Any]) -> bool:
    scope = audit_scope(event)
    return (
        scope is not None
        and audit_scope(record) == scope
        and record.get("source") == str(event.get("source") or "unknown")
        and record.get("command") == str(extract_command(event) or "dispatch")
    )


def audit_log_path() -> Path:
    return Path(os.getenv("TIAN_SHEN_AUDIT_LOG", DEFAULT_AUDIT_LOG_PATH))


def record_audit(event: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    command = extract_command(event)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": str(event.get("source") or "unknown"),
        "target": str(event.get("target") or "unknown"),
        "action": str(event.get("action") or "dispatch"),
        "command": str(command or event.get("action") or "dispatch"),
        "level": decision.get("decision"),
        "decision": decision.get("decision"),
        "allowed": bool(decision.get("allowed")),
        "requires_confirmation": bool(decision.get("requires_confirmation")),
        "reasons": decision.get("reasons") or [],
        "safe_alternative": decision.get("safe_alternative") or "",
        "tian_brain": decision.get("tian_brain") or {},
        "audit_scope": audit_scope(event),
    }
    path = audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def extract_command(event: dict[str, Any]) -> Any:
    payload = event.get("payload")
    if event.get("command"):
        return event.get("command")
    if isinstance(payload, dict) and payload.get("command"):
        return payload.get("command")
    return event.get("action")


def read_audit_records(
    limit: int | None = None, *, event: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return the last limit matching records, not matches in a global window.

    Unscoped/legacy events remain in the audit log but cannot supply scoped risk
    history. The window includes both allowed and blocked matching decisions.
    """
    path = audit_log_path()
    if not path.exists():
        return []
    rows: deque[dict[str, Any]] = deque(maxlen=limit)
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if event is None or matches_audit_event(record, event):
                rows.append(record)
    return list(rows)
