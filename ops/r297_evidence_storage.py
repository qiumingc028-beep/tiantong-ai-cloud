#!/usr/bin/env python3
"""Provision or validate the two persistent R297 acceptance ledgers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat


def _protected_file(path: Path, initial: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = path.parent.lstat()
    if (
        path.parent.is_symlink() or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise RuntimeError("evidence ledger directory permissions invalid")
    try:
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600,
        )
    except FileExistsError:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        os.close(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_nlink != 1
        ):
            raise RuntimeError("evidence ledger permissions invalid")
        return
    committed = False
    try:
        remaining = memoryview(initial)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("evidence ledger short write")
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        committed = True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not committed:
            path.unlink(missing_ok=True)


def provision_acceptance_storage(run_ledger: Path, nonce_ledger: Path) -> None:
    _protected_file(run_ledger, b'{"schema_version":1,"runs":[]}\n')
    _protected_file(Path(f"{run_ledger}.lock"), b"")
    _protected_file(nonce_ledger, b"[]\n")
    _protected_file(Path(f"{nonce_ledger}.lock"), b"")
    run = json.loads(run_ledger.read_text(encoding="utf-8"))
    nonces = json.loads(nonce_ledger.read_text(encoding="utf-8"))
    if set(run) != {"schema_version", "runs"} or run["schema_version"] != 1 or not isinstance(run["runs"], list):
        raise RuntimeError("acceptance run ledger invalid")
    if not isinstance(nonces, list):
        raise RuntimeError("evidence nonce ledger invalid")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-ledger", type=Path, required=True)
    parser.add_argument("--nonce-ledger", type=Path, required=True)
    args = parser.parse_args()
    provision_acceptance_storage(args.run_ledger, args.nonce_ledger)
    print("R297_ACCEPTANCE_STORAGE=READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
