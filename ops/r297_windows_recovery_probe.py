"""Native Windows filesystem fault injection, never formal business Evidence.

Run from the pinned installed signer with its protected SID policy. Fixtures
contain no credentials and are retained in a fresh subdirectory for inspection.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from ops.r297_trusted_windows_observer import _fixed_signer_checkout
from ops.r297_windows_file_security import protected_open, read_protected, recover_bound_file

_CONTENT = b'{"native_filesystem_probe":"not-business-evidence"}\n'


def _validate(content):
    if content != _CONTENT:
        raise RuntimeError("R297_NATIVE_PROBE_CONTENT_CHANGED")


def _child(*args):
    root = str(Path(__file__).resolve().parents[1])
    entry = f"import sys;sys.path.insert(0,{root!r});from ops.r297_windows_recovery_probe import main;raise SystemExit(main())"
    return [sys.executable, "-I", "-c", entry, *map(str, args)]


def _recover_concurrently(scratch):
    children = []
    successes = 0
    try:
        for _ in range(2):
            children.append(subprocess.Popen(_child(scratch, "--recover"),
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        for child in children:
            try:
                _, error = child.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                raise RuntimeError("R297_NATIVE_RECOVERY_TIMED_OUT") from None
            if child.returncode == 0:
                successes += 1
            elif b"R297_WINDOWS_PUBLICATION_BUSY_OR_UNSAFE" not in error:
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
    parser.add_argument("--prepare", choices=("body", "sidecar"))
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("R297_NATIVE_WINDOWS_HOST_REQUIRED")
    head = _fixed_signer_checkout()
    with protected_open(args.outbox, output=True, directory=True):
        pass
    body = args.outbox / "event.json"
    sidecar = Path(str(body) + ".sha256")
    if args.prepare:
        with body.open("xb") as stream:
            stream.write(_CONTENT); stream.flush(); os.fsync(stream.fileno())
        if args.prepare == "sidecar":
            with sidecar.open("xb") as stream:
                stream.write(f"{hashlib.sha256(_CONTENT).hexdigest()}  event.json\n".encode())
                stream.flush(); os.fsync(stream.fileno())
        target = body if args.prepare == "body" else sidecar
        os.link(target, target.with_name(f".{target.name}.0123456789abcdef"))
        os._exit(97)  # No Python finally/cleanup: genuine producer-process interruption.
    if args.recover:
        recover_bound_file(body, validate=_validate)
        return 0
    checks = 0
    retained = []
    for phase in ("body", "sidecar"):
        scratch = Path(tempfile.mkdtemp(prefix=".r297-native-recovery-", dir=args.outbox))
        retained.append(str(scratch))
        result = subprocess.run(_child(scratch, "--prepare", phase), capture_output=True, timeout=30)
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
        # Two fresh processes exercise the native directory publication lock.
        _recover_concurrently(scratch)
        # Retry also verifies cleanup/flush idempotency after the first process exits.
        recover_bound_file(body, validate=_validate)
        if target.stat().st_ino != original_id or target.stat().st_nlink != 1:
            raise RuntimeError("R297_NATIVE_ORIGINAL_OBJECT_CHANGED")
        if body.read_bytes() != _CONTENT or list(scratch.glob(".*.0123456789abcdef")):
            raise RuntimeError("R297_NATIVE_RECOVERY_OUTPUT_INVALID")
        checks += 1
    print(json.dumps({"head": head, "native_process_crash_checks": checks,
                      "result": "PASS", "formal_evidence": "NOT_PRODUCED",
                      "coverage": "native_filesystem_only_not_full_receipt_protocol",
                      "power_loss_reboot": "NOT_TESTED", "retained_fixture_directories": retained}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
