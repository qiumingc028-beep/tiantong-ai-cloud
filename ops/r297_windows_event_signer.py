#!/usr/bin/env python3
"""Sign an Electron exit observed by the controlled Windows runner."""

from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets

try:
    from ops.r297_evidence_events import load_trust_manifest, sign_event, verify_signed_event
except ModuleNotFoundError as exc:
    if exc.name != "ops":
        raise
    from r297_evidence_events import load_trust_manifest, sign_event, verify_signed_event


_SCOPE_FIELDS = {"namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha"}


def _windows_process_is_running(process_id: int) -> bool:
    synchronize = 0x00100000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(synchronize, False, process_id)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: the PID no longer exists.
            return False
        raise OSError(error, "cannot verify Electron process exit")
    try:
        wait_result = kernel32.WaitForSingleObject(handle, 0)
        if wait_result == 0x00000000:  # WAIT_OBJECT_0
            return False
        if wait_result == 0x00000102:  # WAIT_TIMEOUT
            return True
        raise OSError(ctypes.get_last_error(), "cannot verify Electron process exit")
    finally:
        kernel32.CloseHandle(handle)


def _process_is_running(process_id: int) -> bool:
    if os.name == "nt":
        return _windows_process_is_running(process_id)
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def produce_electron_exit_event(
    *, scope: dict, process_id: int, process_started_at: datetime,
    observed_at: datetime | None = None, process_is_running=_process_is_running,
) -> dict:
    environment = os.getenv("APP_ENV", "").strip().lower()
    if environment not in {"acceptance", "production", "test"}:
        raise RuntimeError("windows runner signer environment is not configured")
    private_key_variable = (
        "R297_WINDOWS_RUNNER_TEST_PRIVATE_KEY_PATH"
        if environment == "test" else "R297_WINDOWS_RUNNER_PRIVATE_KEY_PATH"
    )
    if not os.getenv(private_key_variable, ""):
        raise RuntimeError("windows runner private key missing")
    if set(scope) != _SCOPE_FIELDS:
        raise ValueError("electron exit scope invalid")
    observed_at = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    process_started_at = process_started_at.astimezone(timezone.utc)
    if (
        type(process_id) is not int
        or process_id <= 0
        or process_started_at >= observed_at
        or process_is_running(process_id)
    ):
        raise RuntimeError("electron process still running")
    manifest, _ = load_trust_manifest(environment=environment)
    event = {
        **scope,
        "event_type": "electron_exit",
        "issuer": "windows_runner",
        "observed_at": observed_at.isoformat(),
        "sequence": 3,
        "nonce": secrets.token_urlsafe(24),
        "payload": {
            "exited": True,
            "process_id": process_id,
            "process_started_at": process_started_at.isoformat(),
        },
    }
    signed = sign_event(event, environment=environment, manifest=manifest, issuer="windows_runner")
    verify_signed_event(
        signed, event_type="electron_exit", issuer="windows_runner",
        environment=environment, now=observed_at,
    )
    return signed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--tenant-id", type=int, required=True)
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--store-id", type=int, required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--process-id", type=int, required=True)
    parser.add_argument("--process-started-at", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.release_sha):
        raise RuntimeError("electron exit release invalid")
    started_at = datetime.fromisoformat(args.process_started_at.replace("Z", "+00:00"))
    if started_at.tzinfo is None:
        raise RuntimeError("electron process start time invalid")
    scope = {field: getattr(args, field) for field in _SCOPE_FIELDS}
    event = produce_electron_exit_event(
        scope=scope, process_id=args.process_id, process_started_at=started_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.output.write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    args.output.chmod(0o600)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    sidecar = Path(f"{args.output}.sha256")
    sidecar.write_text(f"{digest}  {args.output.name}\n", encoding="ascii")
    sidecar.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
