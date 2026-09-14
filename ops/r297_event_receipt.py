#!/usr/bin/env python3
"""Persist receipt of one verified R297 event in the protected run transaction."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from ops.r297_acceptance_run import read_acceptance_event_receipt, record_acceptance_event_receipt
from ops.r297_evidence_events import signed_event_sha256, verify_signed_event


_ORDER = (
    ("web_page_close", "page_event_receiver"),
    ("authenticated_observer", "authenticated_observer"),
    ("electron_exit", "windows_runner"),
    ("authenticated_observer", "authenticated_observer"),
)
_SCOPE_FIELDS = (
    "namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha",
    "run_id", "run_attempt", "challenge",
)


def _read_bound_event(path: Path) -> dict:
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    sidecar = Path(f"{path}.sha256").read_text(encoding="ascii").strip().split()
    if sidecar != [digest, path.name]:
        raise RuntimeError("signed event sidecar mismatch")
    return json.loads(content)


def record_event(
    ledger: Path, event_path: Path, *, source_workflow_run_id: int,
    now: datetime | None = None,
) -> str:
    event = _read_bound_event(event_path)
    if os.getenv("APP_ENV", "").strip().lower() in {"acceptance", "production"}:
        from ops.r297_broker_client import broker_request
        return broker_request({"action": "receipt", "event": event, "source_workflow_run_id": source_workflow_run_id})["result"]
    return record_event_value(ledger, event, source_workflow_run_id=source_workflow_run_id, now=now)


def record_event_value(
    ledger: Path, event: dict, *, source_workflow_run_id: int,
    now: datetime | None = None, require_existing: bool = False,
) -> str:
    if type(source_workflow_run_id) is not int or source_workflow_run_id <= 0:
        raise ValueError("source workflow binding invalid")
    sequence = event.get("sequence")
    if type(sequence) is not int or sequence not in range(1, len(_ORDER) + 1):
        raise ValueError("evidence event sequence invalid")
    event_type, issuer = _ORDER[sequence - 1]
    received_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    scope = {field: event[field] for field in _SCOPE_FIELDS}
    digest = signed_event_sha256(event)
    original_received_at = read_acceptance_event_receipt(
        ledger, expected_scope=scope, source_workflow_run_id=source_workflow_run_id,
        sequence=sequence, event_sha256=digest, now=received_at,
    )
    if require_existing and original_received_at is None:
        raise ValueError("RECEIPT_NOT_VERIFIED")
    verify_signed_event(
        event, event_type=event_type, issuer=issuer,
        environment=os.getenv("APP_ENV", "").strip().lower(),
        now=original_received_at or received_at,
    )
    if original_received_at is not None:
        return "recovered"
    return record_acceptance_event_receipt(
        ledger,
        expected_scope=scope,
        source_workflow_run_id=source_workflow_run_id,
        event_type=event_type,
        sequence=sequence,
        event_sha256=digest,
        observed_at=datetime.fromisoformat(event["observed_at"].replace("Z", "+00:00")),
        received_at=received_at,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    parser.add_argument("event", type=Path)
    parser.add_argument("--source-workflow-run-id", type=int, required=True)
    args = parser.parse_args()
    result = record_event(
        args.ledger, args.event, source_workflow_run_id=args.source_workflow_run_id,
    )
    print(f"R297_EVENT_RECEIPT_RESULT={result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
