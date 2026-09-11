"""Native Windows original-receipt recovery probe, never new business Evidence.

Run from the pinned installed signer with protected approvals and an original
signed event. Never sign, replay business actions, or rewrite source evidence.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

from ops.r297_trusted_windows_observer import (
    _fixed_signer_checkout, _read_bound_json, _relay_receipt_time,
    _trusted_artifact_manifest, _trusted_run_binding, _trusted_page_observer_ack,
    _trusted_windows_relay_receipt, recover_trusted_output,
)
from ops.r297_windows_file_security import _RecoveryIO, protected_open, read_protected


def recover_original(body, inputs):
    if recover_trusted_output(body, **inputs) is not True:
        raise RuntimeError("R297_NATIVE_ORIGINAL_OUTPUT_MISSING")


def _load_original(request_path, event_path, head):
    content = read_protected(event_path, output=True)
    marker = read_protected(Path(str(event_path) + ".sha256"), output=True)
    if marker != f"{hashlib.sha256(content).hexdigest()}  {event_path.name}\n".encode("ascii"):
        raise RuntimeError("R297_NATIVE_SOURCE_SIDECAR_INVALID")
    wrapper = json.loads(content)
    request = _read_bound_json(request_path)
    receipt = _trusted_windows_relay_receipt()
    current = datetime.now(timezone.utc)
    event = wrapper["event"]
    observed = datetime.fromisoformat(event["observed_at"].replace("Z", "+00:00"))
    if observed.tzinfo is None or current - observed <= timedelta(minutes=5):
        raise RuntimeError("R297_NATIVE_OLD_ORIGINAL_EVENT_REQUIRED")
    # Require the real protected receipt, never a caller-supplied trusted time.
    _relay_receipt_time(receipt, event, request, current)
    return content, dict(request=request, signer_sha=head,
                         artifact_manifest=_trusted_artifact_manifest(),
                         run_binding=_trusted_run_binding(),
                         page_observer_ack=_trusted_page_observer_ack(),
                         relay_receipt=receipt)


def _child(*args):
    root = str(Path(__file__).resolve().parents[1])
    entry = f"import sys;sys.path.insert(0,{root!r});from ops.r297_windows_recovery_probe import entrypoint;raise SystemExit(entrypoint())"
    return [sys.executable, "-I", "-c", entry, *map(str, args)]


def _recover_concurrently(scratch, *source_args):
    children = []
    successes = 0
    try:
        for _ in range(2):
            children.append(subprocess.Popen(_child(scratch, "--recover", *source_args),
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        for child in children:
            try:
                _, error = child.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                raise RuntimeError("R297_NATIVE_RECOVERY_TIMED_OUT") from None
            if child.returncode == 0:
                successes += 1
            elif error.strip() != b"R297_WINDOWS_PUBLICATION_BUSY_OR_UNSAFE":
                raise RuntimeError("R297_NATIVE_RECOVERY_CHILD_FAILED")
        if successes == 0:
            raise RuntimeError("R297_NATIVE_NO_CHILD_COMPLETED_RECOVERY")
    finally:
        cleanup_failed = False
        for child in children:
            try:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                cleanup_failed = True
        if cleanup_failed:
            raise RuntimeError("R297_NATIVE_CHILD_CLEANUP_FAILED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outbox", type=Path)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--original-event", type=Path, required=True)
    parser.add_argument("--prepare", choices=("body", "sidecar"))
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("R297_NATIVE_WINDOWS_HOST_REQUIRED")
    if os.getenv("APP_ENV") != "acceptance":
        raise RuntimeError("R297_NATIVE_PROTECTED_ENVIRONMENT_REQUIRED")
    head = _fixed_signer_checkout()
    content, inputs = _load_original(args.request, args.original_event, head)
    source_args = ("--request", args.request, "--original-event", args.original_event)
    with protected_open(args.outbox, output=True, directory=True):
        pass
    body = args.outbox / "event.json"
    sidecar = Path(str(body) + ".sha256")
    if args.prepare:
        with _RecoveryIO().lock(args.outbox):
            with body.open("xb") as stream:
                stream.write(content); stream.flush(); os.fsync(stream.fileno())
            if args.prepare == "sidecar":
                with sidecar.open("xb") as stream:
                    stream.write(f"{hashlib.sha256(content).hexdigest()}  event.json\n".encode())
                    stream.flush(); os.fsync(stream.fileno())
            target = body if args.prepare == "body" else sidecar
            os.link(target, target.with_name(f".{target.name}.0123456789abcdef"))
            os._exit(97)  # No Python finally/cleanup: genuine producer-process interruption.
    if args.recover:
        recover_original(body, inputs)
        return 0
    checks = 0
    retained = []
    for phase in ("body", "sidecar"):
        with protected_open(args.outbox, output=True, directory=True):
            scratch = Path(tempfile.mkdtemp(prefix=".r297-native-recovery-", dir=args.outbox))
        retained.append(str(scratch))
        result = subprocess.run(_child(scratch, "--prepare", phase, *source_args), capture_output=True, timeout=30)
        if result.returncode != 97:
            raise RuntimeError("R297_NATIVE_PREPARE_DID_NOT_REACH_CRASH_POINT")
        body = scratch / "event.json"
        target = body if phase == "body" else Path(str(body) + ".sha256")
        original_id = target.stat().st_ino
        try:
            read_protected(target, output=True)
        except RuntimeError as exc:
            if "HARDLINK_REJECTED" not in str(exc):
                raise
        else:
            raise RuntimeError("R297_NATIVE_PUBLIC_READ_WIDENED")
        checks += 1
        # Negative facts must reach the same complete entry, not a mock validator.
        for receipt in (None, {**inputs["relay_receipt"], "event_sha256": "invalid"}):
            try:
                recover_original(body, {**inputs, "relay_receipt": receipt})
            except RuntimeError as exc:
                if "relay receipt" not in str(exc):
                    raise RuntimeError("R297_NATIVE_UNEXPECTED_NEGATIVE_FAILURE") from None
            else:
                raise RuntimeError("R297_NATIVE_INVALID_RECEIPT_ACCEPTED")
            if (body.read_bytes() != content or target.stat().st_ino != original_id
                    or target.stat().st_nlink != 2
                    or (phase == "body" and Path(str(body) + ".sha256").exists())):
                raise RuntimeError("R297_NATIVE_FAILED_RECOVERY_MUTATED_OUTPUT")
            checks += 1
        # A held native publication lock must make both children fail, not PASS.
        with _RecoveryIO().lock(scratch):
            try:
                _recover_concurrently(scratch, *source_args)
            except RuntimeError as exc:
                if str(exc) != "R297_NATIVE_NO_CHILD_COMPLETED_RECOVERY":
                    raise
            else:
                raise RuntimeError("R297_NATIVE_BUSY_RECOVERY_ACCEPTED")
        checks += 1
        # Two fresh processes exercise the native directory publication lock.
        _recover_concurrently(scratch, *source_args)
        # Retry also verifies cleanup/flush idempotency after the first process exits.
        recover_original(body, inputs)
        if target.stat().st_ino != original_id or target.stat().st_nlink != 1:
            raise RuntimeError("R297_NATIVE_ORIGINAL_OBJECT_CHANGED")
        if (read_protected(body, output=True) != content
                or read_protected(Path(str(body) + ".sha256"), output=True)
                != f"{hashlib.sha256(content).hexdigest()}  event.json\n".encode()
                or list(scratch.glob(".*.0123456789abcdef"))):
            raise RuntimeError("R297_NATIVE_RECOVERY_OUTPUT_INVALID")
        checks += 1
    print(json.dumps({"head": head, "native_process_crash_checks": checks,
                      "result": "PASS", "formal_evidence": "NOT_PRODUCED",
                      "coverage": "recover_trusted_output_original_receipt_body_sidecar",
                      "power_loss_reboot": "NOT_TESTED", "retained_fixture_directories": retained}))
    return 0


def entrypoint():
    try:
        return main()
    except Exception as exc:
        message = ("R297_WINDOWS_PUBLICATION_BUSY_OR_UNSAFE"
                   if type(exc) is RuntimeError and str(exc) == "R297_WINDOWS_PUBLICATION_BUSY_OR_UNSAFE"
                   else "R297_NATIVE_RECOVERY_PROBE=BLOCK")
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(entrypoint())
