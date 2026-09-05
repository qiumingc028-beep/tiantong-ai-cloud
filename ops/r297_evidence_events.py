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


_SHA_RE = re.compile(r"[0-9a-f]{40}")
_NONCE_RE = re.compile(r"[A-Za-z0-9_-]{16,128}")
_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")
_EVENT_ORDER = (
    ("web_page_close", "page_event_receiver"),
    ("authenticated_observer", "authenticated_observer"),
    ("electron_exit", "windows_runner"),
    ("authenticated_observer", "authenticated_observer"),
)
_FIELDS = {
    "event_type", "issuer", "release_sha", "store_id", "occurred_at",
    "sequence", "nonce", "key_id", "payload", "signature",
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


def trusted_keys_sha256(public_keys: dict) -> str:
    canonical = json.dumps(public_keys, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(canonical).hexdigest()


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


def _observer_result(event: dict, subject_nonce: str, expected_store_id: int) -> dict:
    payload = event["payload"]
    if payload.get("subject_nonce") != subject_nonce or payload.get("scheduler_continues") is not True:
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
    }


def _record_nonces(nonce_ledger: Path, nonces: list[str]) -> None:
    nonce_ledger.parent.mkdir(parents=True, exist_ok=True)
    lock_path = nonce_ledger.with_suffix(nonce_ledger.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        lock_path.chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger_values: set[str] = set()
        if nonce_ledger.exists():
            loaded = json.loads(nonce_ledger.read_text(encoding="utf-8"))
            if not isinstance(loaded, list) or not all(isinstance(value, str) for value in loaded):
                raise ValueError("evidence nonce ledger invalid")
            ledger_values.update(loaded)
        if ledger_values.intersection(nonces):
            raise ValueError("replayed evidence nonce")
        temporary = nonce_ledger.with_name(f".{nonce_ledger.name}.{secrets.token_hex(8)}")
        temporary.write_text(json.dumps(sorted(ledger_values.union(nonces))) + "\n", encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, nonce_ledger)
        nonce_ledger.chmod(0o600)


def verify_acceptance_event_bundle(
    bundle: dict,
    public_keys: dict,
    *,
    expected_release_sha: str,
    expected_store_id: int,
    now: datetime,
    nonce_ledger: Path,
    expected_public_keys_sha256: str,
    maximum_age: timedelta = timedelta(minutes=5),
) -> dict:
    """Return acceptance sections only after all four independently signed events verify."""
    events = bundle.get("events") if isinstance(bundle, dict) else None
    if not isinstance(events, list) or len(events) != len(_EVENT_ORDER):
        raise ValueError("evidence event count mismatch")
    if not _SHA_RE.fullmatch(expected_release_sha) or type(expected_store_id) is not int or expected_store_id <= 0:
        raise ValueError("invalid expected evidence binding")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_public_keys_sha256):
        raise ValueError("trusted key digest missing")
    if trusted_keys_sha256(public_keys) != expected_public_keys_sha256:
        raise ValueError("trusted key digest mismatch")
    expected_issuers = {issuer for _, issuer in _EVENT_ORDER}
    if not isinstance(public_keys, dict) or set(public_keys) != expected_issuers:
        raise ValueError("evidence issuer keys not isolated")
    issuer_keys = [public_keys.get(issuer) for _, issuer in _EVENT_ORDER]
    unique_issuer_keys = {
        (key.get("n"), key.get("e"))
        for key in issuer_keys
        if isinstance(key, dict)
    }
    if len(issuer_keys) != 4 or len(unique_issuer_keys) != 3:
        raise ValueError("evidence issuer keys not isolated")
    now = now.astimezone(timezone.utc)
    nonces: list[str] = []
    previous_time = None
    for sequence, (event, (event_type, issuer)) in enumerate(zip(events, _EVENT_ORDER), 1):
        if not isinstance(event, dict) or set(event) != _FIELDS:
            raise ValueError("evidence event schema mismatch")
        if event.get("event_type") != event_type or event.get("issuer") != issuer:
            raise ValueError("evidence event role mismatch")
        if event.get("release_sha") != expected_release_sha:
            raise ValueError("release SHA mismatch")
        if type(event.get("store_id")) is not int or event.get("store_id") != expected_store_id:
            raise ValueError("store scope mismatch")
        if type(event.get("sequence")) is not int or event.get("sequence") != sequence:
            raise ValueError("event sequence mismatch")
        nonce = event.get("nonce")
        if not isinstance(nonce, str) or not _NONCE_RE.fullmatch(nonce) or nonce in nonces:
            raise ValueError("replayed evidence nonce")
        nonces.append(nonce)
        try:
            occurred_at = datetime.fromisoformat(str(event.get("occurred_at")).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid evidence event time") from exc
        if occurred_at.tzinfo is None:
            raise ValueError("invalid evidence event time")
        occurred_at = occurred_at.astimezone(timezone.utc)
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
            or set(key) != {"key_id", "n", "e"}
            or not isinstance(key.get("key_id"), str)
            or not re.fullmatch(r"[A-Za-z0-9._-]{8,128}", key["key_id"])
            or event.get("key_id") != key.get("key_id")
        ):
            raise ValueError("evidence issuer key missing")
        _verify_signature(event, key)

    page, page_observer, electron, electron_observer = events
    if page["payload"].get("closed") is not True or page["payload"].get("source") != "browser_pagehide":
        raise ValueError("page close event invalid")
    process_id = electron["payload"].get("process_id")
    if electron["payload"].get("exited") is not True or type(process_id) is not int or process_id <= 0:
        raise ValueError("electron exit event invalid")
    page_result = _observer_result(page_observer, page["nonce"], expected_store_id)
    electron_result = _observer_result(electron_observer, electron["nonce"], expected_store_id)

    _record_nonces(nonce_ledger, nonces)

    return {
        "web_page_close": {"closed": True, **page_result},
        "electron_exit": {"exited": True, "process_id": process_id, **electron_result},
        "authenticated_observer": {
            "issuer": "authenticated_observer",
            "release_sha": expected_release_sha,
            "store_id": expected_store_id,
            "verified_subject_count": 2,
            "subject_nonces": [page["nonce"], electron["nonce"]],
        },
    }
