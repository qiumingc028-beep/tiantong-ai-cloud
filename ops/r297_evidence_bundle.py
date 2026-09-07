#!/usr/bin/env python3
"""Assemble the four real R297 producer events without signing any of them."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from ops.r297_evidence_events import verify_acceptance_event_bundle, write_sha256_bound_file


_SCOPE_FIELDS = (
    "namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha",
    "run_id", "run_attempt", "challenge",
)
_SIGNER_VARIABLES = (
    "R297_PAGE_EVENT_RECEIVER_PRIVATE_KEY_PATH",
    "R297_OBSERVER_PRIVATE_KEY_PATH",
    "R297_WINDOWS_RUNNER_PRIVATE_KEY_PATH",
)


def build_bundle(events: list[dict], *, expected_scope: dict, now: datetime) -> dict:
    """Verify a complete chain using a disposable ledger; formal verification consumes the durable ledger."""
    if any(os.getenv(name) for name in _SIGNER_VARIABLES):
        raise RuntimeError("verifier must not receive signer private keys")
    bundle = {"events": events}
    with tempfile.TemporaryDirectory(prefix="r297-bundle-check-") as root:
        directory = Path(root)
        directory.chmod(0o700)
        ledger = directory / "nonces.json"
        lock = directory / "nonces.json.lock"
        ledger.write_text("[]\n", encoding="utf-8")
        lock.touch()
        ledger.chmod(0o600)
        lock.chmod(0o600)
        verify_acceptance_event_bundle(
            bundle,
            expected_scope=expected_scope,
            now=now,
            nonce_ledger=ledger,
        )
    return bundle


def _read_bound_event(path: Path) -> dict:
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    sidecar = Path(f"{path}.sha256").read_text(encoding="ascii").strip().split()
    if sidecar != [digest, path.name]:
        raise RuntimeError("signed event sidecar mismatch")
    return json.loads(content)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("events", nargs=4, type=Path)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--store-id", type=int, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--challenge", required=True)
    args = parser.parse_args()
    scope = {field: getattr(args, field) for field in _SCOPE_FIELDS}
    events = [_read_bound_event(path) for path in args.events]
    bundle = build_bundle(events, expected_scope=scope, now=datetime.now(timezone.utc))
    content = (json.dumps(bundle, sort_keys=True) + "\n").encode()
    write_sha256_bound_file(args.output, content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
