#!/usr/bin/env python3
"""Root-owned, keyless Unix-socket broker for protected R297 ledgers."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import grp
import json
import os
from pathlib import Path
import pwd
import socket
import socketserver
import stat
import struct

from ops.r297_acceptance_run import issue_acceptance_run, record_acceptance_event_receipt
from ops.r297_evidence_events import signed_event_sha256, verify_signed_event, write_sha256_bound_file


_ORDER = (
    ("web_page_close", "page_event_receiver"),
    ("authenticated_observer", "authenticated_observer"),
    ("electron_exit", "windows_relay"),
    ("authenticated_observer", "authenticated_observer"),
)
_ISSUER = {
    "page_event_receiver": "page_event_receiver",
    "authenticated_observer": "authenticated_observer",
    "windows_relay": "windows_runner",
}
_SCOPE_FIELDS = (
    "namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha",
    "run_id", "run_attempt", "challenge",
)
_MAX_REQUEST_BYTES = 1024 * 1024


def _record_event(ledger: Path, event: dict, source_workflow_run_id: int, now=None) -> str:
    received_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    sequence = event.get("sequence")
    if type(sequence) is not int or sequence not in range(1, len(_ORDER) + 1):
        raise ValueError("evidence event sequence invalid")
    event_type, role = _ORDER[sequence - 1]
    verify_signed_event(
        event, event_type=event_type, issuer=_ISSUER[role],
        environment=os.getenv("APP_ENV", "").strip().lower(), now=received_at,
    )
    return record_acceptance_event_receipt(
        ledger,
        expected_scope={field: event[field] for field in _SCOPE_FIELDS},
        source_workflow_run_id=source_workflow_run_id,
        event_type=event_type,
        sequence=sequence,
        event_sha256=signed_event_sha256(event),
        observed_at=datetime.fromisoformat(event["observed_at"].replace("Z", "+00:00")),
        received_at=received_at,
    )


class EvidenceBroker:
    def __init__(
        self, *, run_ledger: Path, nonce_ledger: Path, snapshot_root: Path,
        role_uids: dict[str, int], issue_run=issue_acceptance_run, record_event=_record_event,
    ):
        self.run_ledger = run_ledger
        self.nonce_ledger = nonce_ledger
        self.snapshot_root = snapshot_root
        self.role_uids = role_uids
        self.issue_run = issue_run
        self.record_event = record_event

    def _publish_snapshot(self, record: dict) -> Path:
        self.snapshot_root.mkdir(parents=True, exist_ok=True, mode=0o755)
        run_root = self.snapshot_root / record["run_id"]
        try:
            run_root.mkdir(mode=0o700)
        except FileExistsError:
            metadata = run_root.lstat()
            if (
                run_root.is_symlink() or not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) not in {0o700, 0o755}
            ):
                raise RuntimeError("acceptance run snapshot directory changed") from None
        snapshot = run_root / "acceptance-run-binding.json"
        content = (json.dumps(record, sort_keys=True) + "\n").encode()
        if snapshot.exists():
            sidecar = Path(f"{snapshot}.sha256")
            digest = __import__("hashlib").sha256(content).hexdigest()
            if (
                snapshot.read_bytes() != content
                or sidecar.read_text(encoding="ascii").strip().split() != [digest, snapshot.name]
            ):
                raise RuntimeError("acceptance run snapshot changed")
        else:
            write_sha256_bound_file(snapshot, content)
        snapshot.chmod(0o444)
        Path(f"{snapshot}.sha256").chmod(0o444)
        run_root.chmod(0o755)
        directory = os.open(run_root, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return snapshot

    def dispatch(self, request: dict, *, peer_uid: int) -> dict:
        action = request.get("action")
        if action == "health" and set(request) == {"action"}:
            return {"result": "ready", "private_key_count": 0}
        if action == "issue" and set(request) == {
            "action", "scope", "source_workflow_run_id", "run_attempt",
        }:
            if peer_uid != self.role_uids["verifier"]:
                raise PermissionError("broker action denied")
            record = self.issue_run(
                self.run_ledger,
                scope=request["scope"],
                source_workflow_run_id=request["source_workflow_run_id"],
                run_attempt=request["run_attempt"],
            )
            return {"result": "issued", "record": record, "snapshot": str(self._publish_snapshot(record))}
        if action == "receipt" and set(request) == {
            "action", "event", "source_workflow_run_id",
        }:
            sequence = request["event"].get("sequence") if isinstance(request["event"], dict) else None
            if type(sequence) is not int or sequence not in range(1, len(_ORDER) + 1):
                raise ValueError("evidence event sequence invalid")
            role = _ORDER[sequence - 1][1]
            if peer_uid != self.role_uids[role]:
                raise PermissionError("receipt role denied")
            result = self.record_event(
                self.run_ledger, request["event"], request["source_workflow_run_id"],
            )
            return {"result": result}
        raise ValueError("broker request invalid")


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        peer_uid = struct.unpack("3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
        line = self.rfile.readline(_MAX_REQUEST_BYTES + 1)
        if not line or len(line) > _MAX_REQUEST_BYTES:
            return
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("broker request invalid")
            response = {"ok": True, "value": self.server.broker.dispatch(request, peer_uid=peer_uid)}
        except (KeyError, OSError, RuntimeError, ValueError, PermissionError) as exc:
            response = {"ok": False, "error": type(exc).__name__}
        self.wfile.write((json.dumps(response, sort_keys=True) + "\n").encode())


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False


def serve(socket_path: Path, broker: EvidenceBroker, *, socket_group: str) -> None:
    if socket_path.exists() or socket_path.is_symlink():
        metadata = socket_path.lstat()
        if not stat.S_ISSOCK(metadata.st_mode):
            raise RuntimeError("broker socket path occupied")
        socket_path.unlink()
    socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    with _Server(str(socket_path), _Handler) as server:
        server.broker = broker
        os.chown(socket_path, 0, grp.getgrnam(socket_group).gr_gid)
        socket_path.chmod(0o660)
        server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--run-ledger", type=Path, required=True)
    parser.add_argument("--nonce-ledger", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--socket-group", default="r297-evidence-producers")
    args = parser.parse_args()
    role_users = {
        "verifier": "r297-verifier",
        "page_event_receiver": "r297-page-receiver",
        "authenticated_observer": "r297-observer",
        "windows_relay": "r297-windows-relay",
    }
    broker = EvidenceBroker(
        run_ledger=args.run_ledger,
        nonce_ledger=args.nonce_ledger,
        snapshot_root=args.snapshot_root,
        role_uids={role: pwd.getpwnam(user).pw_uid for role, user in role_users.items()},
    )
    serve(args.socket, broker, socket_group=args.socket_group)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
