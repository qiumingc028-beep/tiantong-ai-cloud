"""Verify signed R297 client events without trusting client success claims."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat


_SHA_RE = re.compile(r"[0-9a-f]{40}")
_NONCE_RE = re.compile(r"[A-Za-z0-9_-]{16,128}")
_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")
_TEST_TRUST_MANIFEST = Path(__file__).with_name("r297_evidence_trust_manifest.test.json")
_TEST_TRUST_MANIFEST_SHA256 = "0eac4b3fc49f913f33762dbedbe41916c3ef50eb1128211d7d93281c78902fed"
_PRODUCTION_TRUST_MANIFEST = Path("/etc/tiantong/r297-evidence-trust-manifest.json")
_PRODUCTION_TRUST_MANIFEST_SIDECAR = Path("/etc/tiantong/r297-evidence-trust-manifest.json.sha256")
_TEST_KEY_FINGERPRINTS = {
    "0eddedd66e432bc8105bf196092793328ff2f9d83039d80223dd00faee9f4d84",
    "f49dbfbcf14774d5449ba88417fd32b04a028f9911008abeea6d8adf7533c599",
    "fc974bd3604d0c416b49c03639f9c80e6f0d98b1f6edb9519d9ecd3cf6157ce6",
}
_EVENT_ORDER = (
    ("web_page_close", "page_event_receiver"),
    ("authenticated_observer", "authenticated_observer"),
    ("electron_exit", "windows_runner"),
    ("authenticated_observer", "authenticated_observer"),
)
_ALLOWED_EVENTS_BY_ISSUER = {
    "page_event_receiver": ["web_page_close"],
    "authenticated_observer": ["authenticated_observer"],
    "windows_runner": ["electron_exit"],
}
_SCOPE_FIELDS = {
    "namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha",
}
_FIELDS = {
    *_SCOPE_FIELDS, "event_type", "issuer", "observed_at",
    "sequence", "nonce", "key_id", "payload", "signature",
}
_MANIFEST_FIELDS = {"schema_version", "manifest_id", "environment", "keys"}
_KEY_FIELDS = {
    "issuer", "key_id", "algorithm", "allowed_event_types", "valid_from", "valid_until", "n", "e",
}


def _decode(value: str) -> bytes:
    if not isinstance(value, str) or not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid evidence signature")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise ValueError("invalid evidence signature") from exc


def _canonical(event: dict) -> bytes:
    unsigned = {key: value for key, value in event.items() if key != "signature"}
    return json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def signed_event_sha256(event: dict) -> str:
    return hashlib.sha256(
        json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def validate_page_event_payload(payload: object) -> None:
    fields = {
        "closed", "source", "artifact_evidence_sha256", "artifact_archive_sha256",
        "artifact_id", "artifact_name", "workflow_run_id",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != fields
        or payload.get("closed") is not True
        or payload.get("source") != "browser_pagehide"
        or not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("artifact_evidence_sha256", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("artifact_archive_sha256", "")))
        or type(payload.get("artifact_id")) is not int
        or payload["artifact_id"] <= 0
        or type(payload.get("workflow_run_id")) is not int
        or payload["workflow_run_id"] <= 0
        or not re.fullmatch(r"r297-native-pagehide-[A-Za-z0-9._-]+", str(payload.get("artifact_name", "")))
    ):
        raise ValueError("page close event invalid")


def _read_protected_file(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o222:
            raise RuntimeError("production evidence trust manifest is not immutable")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def _timestamp(value: object, error: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(error) from exc
    if parsed.tzinfo is None:
        raise ValueError(error)
    return parsed.astimezone(timezone.utc)


def _scope_identity(value: object) -> bool:
    return (
        type(value) is int and value > 0
        or isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value) is not None
    )


def _key_fingerprint(key: dict) -> str:
    modulus = int.from_bytes(_decode(key.get("n")), "big")
    exponent = int.from_bytes(_decode(key.get("e")), "big")
    return hashlib.sha256(f"{modulus}:{exponent}".encode()).hexdigest()


def _validate_trust_manifest(manifest: object, *, environment: str) -> dict:
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_FIELDS:
        raise ValueError("evidence trust manifest schema mismatch")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("environment") != environment
        or not re.fullmatch(r"[A-Za-z0-9._-]{8,128}", str(manifest.get("manifest_id", "")))
    ):
        raise ValueError("evidence trust manifest identity mismatch")
    keys = manifest.get("keys")
    expected_issuers = {issuer for _, issuer in _EVENT_ORDER}
    if not isinstance(keys, list) or len(keys) != 3:
        raise ValueError("evidence issuer keys not isolated")
    by_issuer = {}
    for key in keys:
        if not isinstance(key, dict) or set(key) != _KEY_FIELDS:
            raise ValueError("evidence trust key schema mismatch")
        issuer = key.get("issuer")
        if issuer in by_issuer or issuer not in expected_issuers:
            raise ValueError("evidence issuer keys not isolated")
        allowed = key.get("allowed_event_types")
        if (
            key.get("algorithm") != "RS256"
            or not isinstance(allowed, list)
            or not allowed
            or allowed != _ALLOWED_EVENTS_BY_ISSUER[issuer]
            or not re.fullmatch(r"[A-Za-z0-9._-]{8,128}", str(key.get("key_id", "")))
        ):
            raise ValueError("evidence trust key policy invalid")
        if _timestamp(key.get("valid_from"), "evidence trust key validity invalid") >= _timestamp(
            key.get("valid_until"), "evidence trust key validity invalid"
        ):
            raise ValueError("evidence trust key validity invalid")
        if environment in {"acceptance", "production"} and (
            _key_fingerprint(key) in _TEST_KEY_FINGERPRINTS
            or str(key.get("key_id", "")).endswith("-test")
        ):
            raise ValueError("test evidence key forbidden in production")
        by_issuer[issuer] = key
    if set(by_issuer) != expected_issuers or len({_key_fingerprint(key) for key in keys}) != 3:
        raise ValueError("evidence issuer keys not isolated")
    return manifest


def load_trust_manifest(*, environment: str) -> tuple[dict, str]:
    """Load the only trust anchor allowed for this runtime environment."""
    environment = environment.strip().lower()
    if environment in {"acceptance", "production"}:
        path = _PRODUCTION_TRUST_MANIFEST
        sidecar = _PRODUCTION_TRUST_MANIFEST_SIDECAR
        manifest_bytes = _read_protected_file(path)
        parts = _read_protected_file(sidecar).decode("ascii").strip().split()
        if len(parts) != 2 or parts[1] != path.name or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise RuntimeError("production evidence trust manifest sidecar invalid")
        expected_digest = parts[0]
    elif environment == "test":
        path = _TEST_TRUST_MANIFEST
        manifest_bytes = path.read_bytes()
        expected_digest = _TEST_TRUST_MANIFEST_SHA256
    else:
        raise RuntimeError("evidence trust manifest environment is not configured")
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    if digest != expected_digest:
        raise RuntimeError("evidence trust manifest digest mismatch")
    manifest = _validate_trust_manifest(json.loads(manifest_bytes.decode("utf-8")), environment=environment)
    return manifest, digest


def _verify_signature(event: dict, key: dict) -> None:
    modulus = int.from_bytes(_decode(key.get("n")), "big")
    exponent = int.from_bytes(_decode(key.get("e")), "big")
    signature = _decode(event.get("signature"))
    size = (modulus.bit_length() + 7) // 8
    signature_value = int.from_bytes(signature, "big")
    if (
        size != 256
        or modulus % 2 != 1
        or exponent != 65537
        or len(signature) != size
        or signature_value >= modulus
    ):
        raise ValueError("invalid evidence signature")
    encoded = pow(signature_value, exponent, modulus).to_bytes(size, "big")
    digest_info = _DIGEST_INFO + hashlib.sha256(_canonical(event)).digest()
    expected = b"\x00\x01" + b"\xff" * (size - len(digest_info) - 3) + b"\x00" + digest_info
    if not secrets.compare_digest(encoded, expected):
        raise ValueError("invalid evidence signature")


def verify_signed_event(
    event: dict, *, event_type: str, issuer: str, environment: str, now: datetime,
    maximum_age: timedelta = timedelta(minutes=5),
) -> tuple[dict, dict]:
    """Verify one producer event against the fixed trust anchor and time window."""
    if not isinstance(event, dict) or set(event) != _FIELDS:
        raise ValueError("evidence event schema mismatch")
    if event.get("event_type") != event_type or event.get("issuer") != issuer:
        raise ValueError("evidence event role mismatch")
    if any(not _scope_identity(event.get(field)) for field in _SCOPE_FIELDS - {"store_id", "platform", "release_sha"}):
        raise ValueError("invalid evidence event scope")
    if (
        type(event.get("store_id")) is not int
        or event["store_id"] <= 0
        or not isinstance(event.get("platform"), str)
        or re.fullmatch(r"[a-z0-9_-]{1,32}", event["platform"]) is None
        or not _SHA_RE.fullmatch(str(event.get("release_sha", "")))
        or type(event.get("sequence")) is not int
        or not isinstance(event.get("nonce"), str)
        or _NONCE_RE.fullmatch(event["nonce"]) is None
        or not isinstance(event.get("payload"), dict)
    ):
        raise ValueError("invalid evidence event scope")
    occurred_at = _timestamp(event.get("observed_at"), "invalid evidence event time")
    now = now.astimezone(timezone.utc)
    if occurred_at < now - maximum_age:
        raise ValueError("expired evidence event")
    if occurred_at > now + timedelta(seconds=30):
        raise ValueError("future evidence event")
    manifest, _ = load_trust_manifest(environment=environment)
    key = next((candidate for candidate in manifest["keys"] if candidate["issuer"] == issuer), None)
    if (
        key is None
        or event.get("key_id") != key["key_id"]
        or event_type not in key["allowed_event_types"]
        or not (_timestamp(key["valid_from"], "evidence trust key validity invalid") <= occurred_at < _timestamp(
            key["valid_until"], "evidence trust key validity invalid"
        ))
    ):
        raise ValueError("evidence issuer key missing")
    if event_type in {"web_page_close", "electron_exit"} and "scheduler_continues" in event["payload"]:
        raise ValueError("client scheduler claim forbidden")
    _verify_signature(event, key)
    return manifest, key


def _observer_result(event: dict, subject_event: dict, expected_store_id: int) -> dict:
    payload = event["payload"]
    if (
        payload.get("subject_nonce") != subject_event["nonce"]
        or payload.get("subject_event_sha256") != signed_event_sha256(subject_event)
        or payload.get("scheduler_continues") is not True
        or payload.get("observation_source") != "postgresql_scheduler_state"
        or payload.get("database_read_only") is not True
    ):
        raise ValueError("observer subject mismatch")
    before = payload.get("cloud_cycles_before")
    after = payload.get("cloud_cycles_after")
    eligible = payload.get("eligible_store_ids")
    collected = payload.get("collected_store_ids_after")
    if (
        type(before) is not int
        or type(after) is not int
        or before < 0
        or after <= before
        or not isinstance(eligible, list)
        or not isinstance(collected, list)
        or any(type(store_id) is not int or store_id <= 0 for store_id in eligible + collected)
        or expected_store_id not in eligible
        or sorted(collected) != sorted(eligible)
    ):
        raise ValueError("observer scheduler evidence invalid")
    return {
        "cloud_cycles_before": before,
        "cloud_cycles_after": after,
        "eligible_store_ids": eligible,
        "collected_store_ids_after": collected,
        "observation_source": "postgresql_scheduler_state",
        "database_read_only": True,
    }


def _record_nonces(nonce_ledger: Path, bindings: list[dict]) -> None:
    nonce_ledger.parent.mkdir(parents=True, exist_ok=True)
    lock_path = nonce_ledger.with_suffix(nonce_ledger.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger_values: set[str] = set()
        if nonce_ledger.exists():
            loaded = json.loads(nonce_ledger.read_text(encoding="utf-8"))
            if not isinstance(loaded, list) or not all(isinstance(value, dict) for value in loaded):
                raise ValueError("evidence nonce ledger invalid")
            ledger_values.update(json.dumps(value, separators=(",", ":"), sort_keys=True) for value in loaded)
        canonical_bindings = {
            json.dumps(value, separators=(",", ":"), sort_keys=True) for value in bindings
        }
        if ledger_values.intersection(canonical_bindings):
            raise ValueError("replayed evidence nonce")
        temporary = nonce_ledger.with_name(f".{nonce_ledger.name}.{secrets.token_hex(8)}")
        updated = [json.loads(value) for value in sorted(ledger_values.union(canonical_bindings))]
        temporary.write_text(json.dumps(updated, sort_keys=True) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, nonce_ledger)
        nonce_ledger.chmod(0o600)


def verify_acceptance_event_bundle(
    bundle: dict,
    *,
    expected_scope: dict,
    now: datetime,
    nonce_ledger: Path,
    maximum_age: timedelta = timedelta(minutes=5),
) -> dict:
    """Return acceptance sections only after all four independently signed events verify."""
    events = bundle.get("events") if isinstance(bundle, dict) else None
    if not isinstance(events, list) or len(events) != len(_EVENT_ORDER):
        raise ValueError("evidence event count mismatch")
    if not isinstance(expected_scope, dict) or set(expected_scope) != _SCOPE_FIELDS:
        raise ValueError("invalid expected evidence binding")
    if (
        not _SHA_RE.fullmatch(str(expected_scope.get("release_sha", "")))
        or not _scope_identity(expected_scope.get("namespace"))
        or not _scope_identity(expected_scope.get("tenant_id"))
        or not _scope_identity(expected_scope.get("company_id"))
        or type(expected_scope.get("store_id")) is not int
        or expected_scope["store_id"] <= 0
        or not isinstance(expected_scope.get("platform"), str)
        or re.fullmatch(r"[a-z0-9_-]{1,32}", expected_scope["platform"]) is None
    ):
        raise ValueError("invalid expected evidence binding")
    manifest, manifest_digest = load_trust_manifest(
        environment=os.getenv("APP_ENV", "").strip().lower()
    )
    public_keys = {key["issuer"]: key for key in manifest["keys"]}
    now = now.astimezone(timezone.utc)
    replay_bindings: list[dict] = []
    bundle_nonces: set[str] = set()
    previous_time = None
    for sequence, (event, (event_type, issuer)) in enumerate(zip(events, _EVENT_ORDER), 1):
        if not isinstance(event, dict) or set(event) != _FIELDS:
            raise ValueError("evidence event schema mismatch")
        if event.get("event_type") != event_type or event.get("issuer") != issuer:
            raise ValueError("evidence event role mismatch")
        for scope_field in _SCOPE_FIELDS:
            if (
                type(event.get(scope_field)) is not type(expected_scope[scope_field])
                or event.get(scope_field) != expected_scope[scope_field]
            ):
                raise ValueError(f"{scope_field} mismatch")
        if type(event.get("sequence")) is not int or event.get("sequence") != sequence:
            raise ValueError("event sequence mismatch")
        nonce = event.get("nonce")
        if not isinstance(nonce, str) or not _NONCE_RE.fullmatch(nonce) or nonce in bundle_nonces:
            raise ValueError("replayed evidence nonce")
        bundle_nonces.add(nonce)
        replay_binding = {field: event[field] for field in _SCOPE_FIELDS}
        replay_binding.update({"event_type": event_type, "key_id": event["key_id"], "nonce": nonce})
        if replay_binding in replay_bindings:
            raise ValueError("replayed evidence nonce")
        replay_bindings.append(replay_binding)
        occurred_at = _timestamp(event.get("observed_at"), "invalid evidence event time")
        if occurred_at < now - maximum_age:
            raise ValueError("expired evidence event")
        if occurred_at > now + timedelta(seconds=30):
            raise ValueError("future evidence event")
        if previous_time is not None and occurred_at <= previous_time:
            raise ValueError("event time order mismatch")
        previous_time = occurred_at
        if not isinstance(event.get("payload"), dict):
            raise ValueError("evidence event schema mismatch")
        if event_type in {"web_page_close", "electron_exit"} and "scheduler_continues" in event["payload"]:
            raise ValueError("client scheduler claim forbidden")
        key = public_keys.get(issuer) if isinstance(public_keys, dict) else None
        if (
            not isinstance(key, dict)
            or event.get("key_id") != key.get("key_id")
            or event_type not in key.get("allowed_event_types", [])
            or not (_timestamp(key["valid_from"], "evidence trust key validity invalid") <= occurred_at < _timestamp(
                key["valid_until"], "evidence trust key validity invalid"
            ))
        ):
            raise ValueError("evidence issuer key missing")
        _verify_signature(event, key)

    page, page_observer, electron, electron_observer = events
    validate_page_event_payload(page["payload"])
    process_id = electron["payload"].get("process_id")
    if electron["payload"].get("exited") is not True or type(process_id) is not int or process_id <= 0:
        raise ValueError("electron exit event invalid")
    page_result = _observer_result(page_observer, page, expected_scope["store_id"])
    electron_result = _observer_result(electron_observer, electron, expected_scope["store_id"])

    _record_nonces(nonce_ledger, replay_bindings)

    return {
        "evidence_trust_manifest_id": manifest["manifest_id"],
        "evidence_trust_manifest_sha256": manifest_digest,
        "web_page_close": {"closed": True, **page_result},
        "electron_exit": {"exited": True, "process_id": process_id, **electron_result},
        "authenticated_observer": {
            "issuer": "authenticated_observer",
            **expected_scope,
            "verified_subject_count": 2,
            "subject_nonces": [page["nonce"], electron["nonce"]],
        },
    }
