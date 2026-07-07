from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_AUDIT_LOG_PATH = "/tmp/tiantong_tian_shen_audit.log"


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


def read_audit_records(limit: int | None = None) -> list[dict[str, Any]]:
    path = audit_log_path()
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    if limit is not None:
        return rows[-limit:]
    return rows
