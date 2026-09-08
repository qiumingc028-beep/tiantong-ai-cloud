#!/usr/bin/env python3
"""Issue and consume one-use R297 acceptance challenges on a protected host."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from collections.abc import Callable


_SCOPE_FIELDS = {"namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha"}


_RUN_LIFETIME = timedelta(minutes=5)
_OBSERVATION_LIFETIME = timedelta(hours=12)
_EVENT_ORDER = ("web_page_close", "authenticated_observer", "electron_exit", "authenticated_observer")
_MAX_STAGED_OUTPUT_BYTES = 2 * 1024 * 1024
_MAX_LEDGER_BYTES = 8 * 1024 * 1024


def _validate_parent(path: Path) -> None:
    parent = path.parent.lstat()
    if (
        path.parent.is_symlink() or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise RuntimeError("acceptance run ledger directory permissions invalid")


def _open_protected(path: Path) -> int:
    descriptor = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_nlink != 1
    ):
        os.close(descriptor)
        raise RuntimeError("acceptance run ledger permissions invalid")
    return descriptor


def _update(path: Path, mutate, *, now: datetime | None = None):
    _validate_parent(path)
    lock_descriptor = _open_protected(Path(f"{path}.lock"))
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        descriptor = _open_protected(path)
        try:
            with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as handle:
                ledger = json.load(handle)
        finally:
            os.close(descriptor)
        if not isinstance(ledger, dict) or set(ledger) != {"schema_version", "runs"} or ledger["schema_version"] != 1 or not isinstance(ledger["runs"], list):
            raise ValueError("acceptance run ledger invalid")
        compact_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        for record in ledger["runs"]:
            if not isinstance(record, dict) or "pending_output_base64" not in record:
                continue
            try:
                issued_at = datetime.fromisoformat(record["issued_at"])
                if issued_at.tzinfo is None:
                    raise ValueError
                expired = compact_at - issued_at.astimezone(timezone.utc) > _OBSERVATION_LIFETIME
            except (KeyError, TypeError, ValueError):
                expired = True
            if expired:
                record.pop("pending_output_base64", None)
        result = mutate(ledger["runs"])
        content = (json.dumps(ledger, sort_keys=True) + "\n").encode()
        if len(content) > _MAX_LEDGER_BYTES:
            raise ValueError("acceptance run ledger size limit exceeded")
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}")
        temporary_descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            remaining = memoryview(content)
            while remaining:
                written = os.write(temporary_descriptor, remaining)
                if written <= 0:
                    raise OSError("acceptance run ledger short write")
                remaining = remaining[written:]
            os.fsync(temporary_descriptor)
            os.close(temporary_descriptor)
            temporary_descriptor = -1
            os.replace(temporary, path)
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if temporary_descriptor >= 0:
                os.close(temporary_descriptor)
            temporary.unlink(missing_ok=True)
        return result
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)


def _require_live(record: dict, now: datetime) -> None:
    try:
        issued_at = datetime.fromisoformat(record["issued_at"])
        if issued_at.tzinfo is None:
            raise ValueError
        issued_at = issued_at.astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError):
        raise ValueError("acceptance run issue time invalid") from None
    if issued_at > now + timedelta(seconds=30) or now - issued_at > _RUN_LIFETIME:
        raise ValueError("acceptance run expired")


def _require_observation_live(record: dict, now: datetime) -> None:
    try:
        issued_at = datetime.fromisoformat(record["issued_at"])
        if issued_at.tzinfo is None:
            raise ValueError
        issued_at = issued_at.astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError):
        raise ValueError("acceptance run issue time invalid") from None
    if issued_at > now + timedelta(seconds=30) or now - issued_at > _OBSERVATION_LIFETIME:
        raise ValueError("acceptance observation expired")


def issue_acceptance_run(
    ledger: Path, *, scope: dict, source_workflow_run_id: int,
    run_attempt: int, now: datetime | None = None,
) -> dict:
    if (
        set(scope) != _SCOPE_FIELDS or not re.fullmatch(r"[0-9a-f]{40}", str(scope.get("release_sha", "")))
        or type(source_workflow_run_id) is not int or source_workflow_run_id <= 0
        or type(run_attempt) is not int or run_attempt <= 0
    ):
        raise ValueError("acceptance run binding invalid")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    challenge = secrets.token_urlsafe(32)
    run_id = f"r297-{run_attempt}-{hashlib.sha256(challenge.encode()).hexdigest()[:24]}"
    record = {
        **scope, "source_workflow_run_id": source_workflow_run_id,
        "run_id": run_id, "run_attempt": run_attempt, "challenge": challenge,
        "issued_at": now.isoformat(), "consumed_at": None, "state": "issued",
        "event_receipts": [],
    }

    def mutate(runs):
        matches = [
            item for item in runs
            if isinstance(item, dict) and item.get("source_workflow_run_id") == source_workflow_run_id
        ]
        if matches:
            existing = matches[0]
            same_binding = (
                len(matches) == 1 and existing.get("state") == "issued"
                and existing.get("run_attempt") == run_attempt
                and all(existing.get(field) == scope[field] for field in _SCOPE_FIELDS)
            )
            if not same_binding:
                raise ValueError("source workflow run already consumed")
            _require_live(existing, now)
            return existing
        runs.append(record)
        return record

    return _update(ledger, mutate, now=now)


def consume_acceptance_run(
    ledger: Path, *, expected_scope: dict, source_workflow_run_id: int,
    now: datetime | None = None,
    transaction_sha256: str | None = None,
    commit_nonces: Callable[[], None] | None = None,
) -> None:
    required = _SCOPE_FIELDS | {"run_id", "run_attempt", "challenge"}
    if set(expected_scope) != required:
        raise ValueError("acceptance run binding invalid")
    if (transaction_sha256 is None) != (commit_nonces is None):
        raise ValueError("acceptance transaction binding invalid")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    def mutate(runs):
        matches = [item for item in runs if isinstance(item, dict) and item.get("run_id") == expected_scope["run_id"]]
        expected_state = "reserved" if transaction_sha256 is not None else "issued"
        if len(matches) != 1 or matches[0].get("state") != expected_state:
            raise ValueError("acceptance run missing or consumed")
        record = matches[0]
        if transaction_sha256 is None:
            _require_live(record, now)
        else:
            _require_observation_live(record, now)
        if record.get("source_workflow_run_id") != source_workflow_run_id:
            raise ValueError("acceptance source workflow mismatch")
        for field in required:
            if type(record.get(field)) is not type(expected_scope[field]) or record.get(field) != expected_scope[field]:
                raise ValueError("acceptance run scope mismatch")
        if transaction_sha256 is not None:
            if record.get("transaction_sha256") != transaction_sha256:
                raise ValueError("acceptance run reserved by different transaction")
            commit_nonces()
        record["state"] = "consumed"
        record["consumed_at"] = now.isoformat()

    _update(ledger, mutate, now=now)


def reserve_acceptance_run(
    ledger: Path, *, expected_scope: dict, source_workflow_run_id: int,
    transaction_sha256: str, now: datetime | None = None,
    event_sha256s: list[str] | None = None,
    require_event_receipts: bool = False,
    verified_bundle: dict | None = None,
) -> str:
    """Fence one exact bundle before nonce/output publication; exact retries resume."""
    required = _SCOPE_FIELDS | {"run_id", "run_attempt", "challenge"}
    if set(expected_scope) != required or not re.fullmatch(r"[0-9a-f]{64}", transaction_sha256):
        raise ValueError("acceptance transaction binding invalid")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    def mutate(runs):
        matches = [item for item in runs if isinstance(item, dict) and item.get("run_id") == expected_scope["run_id"]]
        if len(matches) != 1:
            raise ValueError("acceptance run missing or consumed")
        record = matches[0]
        if record.get("state") == "consumed":
            raise ValueError("acceptance run missing or consumed")
        if require_event_receipts and record.get("state") not in {"observing", "reserved"}:
            raise ValueError("acceptance event receipt chain missing")
        if record.get("state") == "issued":
            _require_live(record, now)
        else:
            _require_observation_live(record, now)
        if record.get("source_workflow_run_id") != source_workflow_run_id:
            raise ValueError("acceptance source workflow mismatch")
        for field in required:
            if type(record.get(field)) is not type(expected_scope[field]) or record.get(field) != expected_scope[field]:
                raise ValueError("acceptance run scope mismatch")
        if record.get("state") in {"issued", "observing"}:
            if record.get("state") == "observing":
                receipts = record.get("event_receipts")
                if (
                    not isinstance(event_sha256s, list)
                    or not isinstance(receipts, list)
                    or [item.get("event_sha256") for item in receipts] != event_sha256s
                    or len(receipts) != len(_EVENT_ORDER)
                ):
                    raise ValueError("acceptance event receipt chain mismatch")
            record.update({
                "state": "reserved", "transaction_sha256": transaction_sha256,
                "reserved_at": now.isoformat(), "published_sha256": None,
                "event_sha256s": event_sha256s,
            })
            if verified_bundle is not None:
                record["verified_bundle"] = verified_bundle
            return "reserved"
        if record.get("state") == "reserved" and record.get("transaction_sha256") == transaction_sha256:
            if record.get("event_sha256s") != event_sha256s:
                raise ValueError("acceptance event receipt binding mismatch")
            if verified_bundle is not None:
                previous = record.get("verified_bundle")
                if previous is not None and previous != verified_bundle:
                    raise ValueError("acceptance verification receipt binding mismatch")
                record["verified_bundle"] = verified_bundle
            return "recovering"
        raise ValueError("acceptance run reserved by different transaction")

    return _update(ledger, mutate, now=now)


def read_acceptance_verification(
    ledger: Path, *, expected_scope: dict, source_workflow_run_id: int,
    transaction_sha256: str, event_sha256s: list[str], now: datetime,
) -> dict:
    """Read trusted verification from the existing transaction, never producer claims."""
    def read(runs):
        matches = [item for item in runs if isinstance(item, dict) and item.get("run_id") == expected_scope["run_id"]]
        if len(matches) != 1:
            raise ValueError("acceptance run missing or consumed")
        record = matches[0]
        _require_observation_live(record, now)
        if record.get("source_workflow_run_id") != source_workflow_run_id or any(
            type(record.get(field)) is not type(value) or record.get(field) != value
            for field, value in expected_scope.items()
        ):
            raise ValueError("acceptance run scope mismatch")
        if record.get("transaction_sha256") not in {None, transaction_sha256}:
            raise ValueError("acceptance run reserved by different transaction: receipt binding mismatch")
        receipts = record.get("event_receipts", [])
        if receipts and [item.get("event_sha256") for item in receipts] != event_sha256s:
            raise ValueError("acceptance event receipt binding mismatch")
        if record.get("verified_bundle") is not None and record.get("event_sha256s") != event_sha256s:
            raise ValueError("acceptance verification receipt binding mismatch")
        return {"verified_bundle": record.get("verified_bundle"), "event_receipts": receipts}

    return _update(ledger, read, now=now)


def read_acceptance_event_receipt(
    ledger: Path, *, expected_scope: dict, source_workflow_run_id: int,
    sequence: int, event_sha256: str, now: datetime,
) -> datetime | None:
    """Recover only the original trusted arrival, including after a lost response."""
    def read(runs):
        matches = [item for item in runs if isinstance(item, dict) and item.get("run_id") == expected_scope["run_id"]]
        if len(matches) != 1:
            raise ValueError("acceptance run missing or consumed")
        record = matches[0]
        _require_observation_live(record, now)
        if record.get("source_workflow_run_id") != source_workflow_run_id or any(
            type(record.get(field)) is not type(value) or record.get(field) != value
            for field, value in expected_scope.items()
        ):
            raise ValueError("acceptance run scope mismatch")
        receipts = record.get("event_receipts", [])
        if len(receipts) < sequence:
            return None
        receipt = receipts[sequence - 1]
        if receipt.get("event_sha256") != event_sha256 or receipt.get("sequence") != sequence:
            raise ValueError("acceptance event receipt binding mismatch")
        return datetime.fromisoformat(receipt["received_at"])

    return _update(ledger, read, now=now)


def record_acceptance_event_receipt(
    ledger: Path, *, expected_scope: dict, source_workflow_run_id: int,
    event_type: str, sequence: int, event_sha256: str,
    observed_at: datetime, received_at: datetime,
) -> str:
    """Persist one already verified event arrival without exposing ledger writes to the producer."""
    required = _SCOPE_FIELDS | {"run_id", "run_attempt", "challenge"}
    if (
        set(expected_scope) != required or type(sequence) is not int or sequence not in range(1, len(_EVENT_ORDER) + 1)
        or event_type != _EVENT_ORDER[sequence - 1]
        or not re.fullmatch(r"[0-9a-f]{64}", event_sha256)
    ):
        raise ValueError("acceptance event receipt invalid")
    observed_at = observed_at.astimezone(timezone.utc)
    received_at = received_at.astimezone(timezone.utc)
    if (
        received_at < observed_at or received_at - observed_at > _RUN_LIFETIME
        or received_at > datetime.now(timezone.utc) + timedelta(seconds=30)
    ):
        raise ValueError("acceptance event receipt time invalid")

    def mutate(runs):
        matches = [item for item in runs if isinstance(item, dict) and item.get("run_id") == expected_scope["run_id"]]
        if len(matches) != 1 or matches[0].get("state") not in {"issued", "observing"}:
            raise ValueError("acceptance run missing or consumed")
        record = matches[0]
        if record.get("state") == "issued":
            _require_live(record, received_at)
        else:
            _require_observation_live(record, received_at)
        if record.get("source_workflow_run_id") != source_workflow_run_id or any(
            type(record.get(field)) is not type(expected_scope[field])
            or record.get(field) != expected_scope[field] for field in required
        ):
            raise ValueError("acceptance run scope mismatch")
        receipts = record.setdefault("event_receipts", [])
        receipt = {
            "event_type": event_type, "sequence": sequence,
            "event_sha256": event_sha256,
            "observed_at": observed_at.isoformat(), "received_at": received_at.isoformat(),
        }
        if len(receipts) >= sequence:
            if all(receipts[sequence - 1].get(field) == value for field, value in receipt.items() if field != "received_at"):
                return "recovered"
            raise ValueError("acceptance event receipt replay")
        if len(receipts) != sequence - 1:
            raise ValueError("acceptance event receipt order invalid")
        receipts.append(receipt)
        record["state"] = "observing"
        return "recorded"

    return _update(ledger, mutate, now=received_at)


def complete_acceptance_run(
    ledger: Path, *, expected_scope: dict, source_workflow_run_id: int,
    transaction_sha256: str, published_path: Path, now: datetime | None = None,
) -> str:
    """Commit a reservation only after a SHA-bound formal output exists."""
    try:
        content = published_path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        sidecar = Path(f"{published_path}.sha256").read_text(encoding="ascii").strip().split()
    except FileNotFoundError as exc:
        raise RuntimeError("published evidence missing") from exc
    if sidecar != [digest, published_path.name]:
        raise RuntimeError("published evidence binding invalid")
    required = _SCOPE_FIELDS | {"run_id", "run_attempt", "challenge"}
    if set(expected_scope) != required or not re.fullmatch(r"[0-9a-f]{64}", transaction_sha256):
        raise ValueError("acceptance transaction binding invalid")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    def mutate(runs):
        matches = [item for item in runs if isinstance(item, dict) and item.get("run_id") == expected_scope["run_id"]]
        if len(matches) != 1:
            raise ValueError("acceptance run missing or consumed")
        record = matches[0]
        if record.get("source_workflow_run_id") != source_workflow_run_id:
            raise ValueError("acceptance source workflow mismatch")
        for field in required:
            if type(record.get(field)) is not type(expected_scope[field]) or record.get(field) != expected_scope[field]:
                raise ValueError("acceptance run scope mismatch")
        if record.get("transaction_sha256") != transaction_sha256:
            raise ValueError("acceptance run reserved by different transaction")
        _require_observation_live(record, now)
        if record.get("state") == "consumed":
            if record.get("published_sha256") != digest:
                raise ValueError("acceptance published evidence changed")
            return "recovered"
        if record.get("state") != "reserved":
            raise ValueError("acceptance run missing or consumed")
        try:
            staged = base64.b64decode(record["pending_output_base64"], validate=True)
        except (KeyError, TypeError, ValueError):
            raise ValueError("acceptance staged output missing") from None
        if (
            record.get("pending_output_sha256") != digest
            or hashlib.sha256(staged).hexdigest() != digest
            or staged != content
        ):
            raise ValueError("acceptance published output differs from staged output")
        record.update({
            "state": "consumed", "consumed_at": now.isoformat(),
            "published_sha256": digest, "pending_output_base64": None,
        })
        return "consumed"

    return _update(ledger, mutate, now=now)


def stage_acceptance_output(
    ledger: Path, *, expected_scope: dict, source_workflow_run_id: int,
    transaction_sha256: str, content: bytes, now: datetime | None = None,
) -> str:
    """Persist the exact formal output bytes before publishing either output file."""
    if not content or len(content) > _MAX_STAGED_OUTPUT_BYTES:
        raise ValueError("acceptance staged output size invalid")
    digest = hashlib.sha256(content).hexdigest()
    encoded = base64.b64encode(content).decode("ascii")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    def mutate(runs):
        matches = [item for item in runs if isinstance(item, dict) and item.get("run_id") == expected_scope["run_id"]]
        if len(matches) != 1:
            raise ValueError("acceptance run missing or consumed")
        record = matches[0]
        _require_observation_live(record, now)
        if (
            record.get("state") != "reserved"
            or record.get("source_workflow_run_id") != source_workflow_run_id
            or record.get("transaction_sha256") != transaction_sha256
            or any(record.get(field) != expected_scope[field] for field in (_SCOPE_FIELDS | {"run_id", "run_attempt", "challenge"}))
        ):
            raise ValueError("acceptance output transaction mismatch")
        previous = record.get("pending_output_sha256")
        if previous is not None and (previous != digest or record.get("pending_output_base64") != encoded):
            raise ValueError("acceptance output changed during recovery")
        record["pending_output_sha256"] = digest
        record["pending_output_base64"] = encoded
        return digest

    return _update(ledger, mutate, now=now)


def recover_staged_acceptance_output(
    ledger: Path, *, expected_scope: dict, source_workflow_run_id: int,
    transaction_sha256: str, now: datetime | None = None,
) -> bytes | None:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    def mutate(runs):
        matches = [item for item in runs if isinstance(item, dict) and item.get("run_id") == expected_scope["run_id"]]
        if len(matches) != 1:
            raise ValueError("acceptance run missing or consumed")
        record = matches[0]
        _require_observation_live(record, now)
        if (
            record.get("state") != "reserved"
            or record.get("source_workflow_run_id") != source_workflow_run_id
            or record.get("transaction_sha256") != transaction_sha256
        ):
            raise ValueError("acceptance output transaction mismatch")
        encoded = record.get("pending_output_base64")
        if encoded is None:
            return None
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ValueError("acceptance staged output invalid") from None
        if hashlib.sha256(content).hexdigest() != record.get("pending_output_sha256"):
            raise ValueError("acceptance staged output invalid")
        return content

    return _update(ledger, mutate, now=now)


def validate_acceptance_run(
    ledger: Path, *, expected_scope: dict, source_workflow_run_id: int,
    transaction_sha256: str | None = None,
    now: datetime | None = None,
) -> None:
    required = _SCOPE_FIELDS | {"run_id", "run_attempt", "challenge"}
    if set(expected_scope) != required:
        raise ValueError("acceptance run binding invalid")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    _validate_parent(ledger)
    lock_descriptor = _open_protected(Path(f"{ledger}.lock"))
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_SH)
        descriptor = _open_protected(ledger)
        try:
            with os.fdopen(os.dup(descriptor), "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        finally:
            os.close(descriptor)
        if (
            not isinstance(payload, dict) or set(payload) != {"schema_version", "runs"}
            or payload["schema_version"] != 1 or not isinstance(payload["runs"], list)
        ):
            raise ValueError("acceptance run ledger invalid")
        runs = payload["runs"]
        matches = [item for item in runs or [] if isinstance(item, dict) and item.get("run_id") == expected_scope["run_id"]]
        if len(matches) != 1 or matches[0].get("state") not in {"issued", "observing", "reserved"}:
            raise ValueError("acceptance run missing or consumed")
        if matches[0].get("state") == "issued":
            _require_live(matches[0], now)
        else:
            _require_observation_live(matches[0], now)
        if matches[0].get("state") == "reserved" and (
            not re.fullmatch(r"[0-9a-f]{64}", transaction_sha256 or "")
            or matches[0].get("transaction_sha256") != transaction_sha256
        ):
            raise ValueError("acceptance transaction binding mismatch")
        if matches[0].get("source_workflow_run_id") != source_workflow_run_id:
            raise ValueError("acceptance source workflow mismatch")
        for field in required:
            if type(matches[0].get(field)) is not type(expected_scope[field]) or matches[0].get(field) != expected_scope[field]:
                raise ValueError("acceptance run scope mismatch")
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)


def validate_acceptance_run_snapshot(
    binding: Path, *, expected_scope: dict, source_workflow_run_id: int,
    now: datetime | None = None,
) -> None:
    """Validate the orchestrator's immutable read-only run snapshot."""
    required = _SCOPE_FIELDS | {"run_id", "run_attempt", "challenge"}
    if set(expected_scope) != required:
        raise ValueError("acceptance run binding invalid")
    parent = binding.parent.lstat()
    if binding.parent.is_symlink() or not stat.S_ISDIR(parent.st_mode) or stat.S_IMODE(parent.st_mode) & 0o022:
        raise RuntimeError("acceptance run snapshot directory permissions invalid")

    trusted_owner = os.geteuid() if os.getenv("APP_ENV", "").strip().lower() == "test" else 0

    def read_protected(path: Path) -> bytes:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or metadata.st_uid != trusted_owner or stat.S_IMODE(metadata.st_mode) & 0o222
            ):
                raise RuntimeError("acceptance run snapshot permissions invalid")
            with os.fdopen(os.dup(descriptor), "rb") as handle:
                return handle.read()
        finally:
            os.close(descriptor)

    content = read_protected(binding)
    digest = hashlib.sha256(content).hexdigest()
    sidecar = read_protected(Path(f"{binding}.sha256")).decode("ascii").strip().split()
    if sidecar != [digest, binding.name]:
        raise RuntimeError("acceptance run snapshot binding invalid")
    try:
        record = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("acceptance run snapshot invalid") from exc
    if not isinstance(record, dict) or record.get("state") != "issued":
        raise ValueError("acceptance run snapshot invalid")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    _require_live(record, now)
    if record.get("source_workflow_run_id") != source_workflow_run_id:
        raise ValueError("acceptance source workflow mismatch")
    for field in required:
        if type(record.get(field)) is not type(expected_scope[field]) or record.get(field) != expected_scope[field]:
            raise ValueError("acceptance run scope mismatch")


def main() -> int:
    import argparse
    from ops.r297_evidence_events import write_sha256_bound_file

    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-workflow-run-id", type=int, required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--store-id", type=int, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--release-sha", required=True)
    args = parser.parse_args()
    record = issue_acceptance_run(
        args.ledger,
        scope={
            "namespace": args.namespace, "tenant_id": args.tenant_id,
            "company_id": args.company_id, "store_id": args.store_id,
            "platform": args.platform, "release_sha": args.release_sha,
        },
        source_workflow_run_id=args.source_workflow_run_id,
        run_attempt=args.run_attempt,
    )
    digest = write_sha256_bound_file(
        args.output, (json.dumps(record, sort_keys=True) + "\n").encode(),
    )
    print(f"R297_ACCEPTANCE_RUN_BINDING={args.output}")
    print(f"R297_ACCEPTANCE_RUN_BINDING_SHA256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
