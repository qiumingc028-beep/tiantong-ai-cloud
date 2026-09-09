#!/usr/bin/env python3
"""Root-owned, keyless Unix-socket broker for protected R297 ledgers."""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
from datetime import datetime, timezone
import grp
import json
import os
from pathlib import Path
import pwd
import socket
import socketserver
import stat
import threading

from ops.r297_acceptance_run import _update, _require_observation_live, acceptance_transaction, complete_acceptance_run, issue_acceptance_run, stage_acceptance_output, validate_acceptance_run
from ops.r297_event_receipt import record_event_value
from ops.r297_evidence_events import _observer_result, _verify_acceptance_event_bundle_local, signed_event_sha256, verify_signed_event, validate_page_event_payload, write_sha256_bound_file


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
_MAX_REQUEST_BYTES = 4 * 1024 * 1024


def _record_event(ledger: Path, event: dict, source_workflow_run_id: int, now=None) -> str:
    return record_event_value(ledger, event, source_workflow_run_id=source_workflow_run_id, now=now)


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
        if set(role_uids) != {"verifier", "page_event_receiver", "authenticated_observer", "windows_relay"} or len(set(role_uids.values())) != 4 or any(type(uid) is not int or uid < 0 for uid in role_uids.values()):
            raise ValueError("broker role identities must be distinct")
        self._lock = threading.RLock()

    def _publish_snapshot(self, record: dict) -> Path:
        self.snapshot_root.mkdir(parents=True, exist_ok=True, mode=0o755)
        root = self.snapshot_root.lstat()
        if not stat.S_ISDIR(root.st_mode) or root.st_uid != os.geteuid() or stat.S_IMODE(root.st_mode) & 0o022:
            raise ValueError("snapshot root untrusted")
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
        self._publish_readonly(snapshot, content)
        return snapshot

    def dispatch(self, request: dict, *, peer_uid: int) -> dict:
        # ponytail: one Broker serializes publication; partition by run only if throughput requires it.
        with self._lock:
            return self._dispatch(request, peer_uid=peer_uid)

    def _dispatch(self, request: dict, *, peer_uid: int) -> dict:
        action = request.get("action")
        if action == "health" and set(request) == {"action"}:
            return {"result": "ready", "private_key_count": 0}
        if action in {"validate", "verify", "reserve", "nonce", "begin", "stage", "complete", "recover", "ack"}:
            if peer_uid != self.role_uids["verifier"]:
                raise PermissionError("broker action denied")
            if action == "ack":
                return self._ack(request)
            return self._transaction(request)
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
        if action in {"receipt", "recover_receipt"} and set(request) == {
            "action", "event", "source_workflow_run_id",
        }:
            sequence = request["event"].get("sequence") if isinstance(request["event"], dict) else None
            if type(sequence) is not int or sequence not in range(1, len(_ORDER) + 1):
                raise ValueError("evidence event sequence invalid")
            role = _ORDER[sequence - 1][1]
            if peer_uid != self.role_uids[role]:
                raise PermissionError("receipt role denied")
            if action == "recover_receipt":
                result = record_event_value(self.run_ledger, request["event"],
                    source_workflow_run_id=request["source_workflow_run_id"], require_existing=True)
                return {"result": result, "event_sha256": signed_event_sha256(request["event"])}
            result = self.record_event(
                self.run_ledger, request["event"], request["source_workflow_run_id"],
            )
            return {"result": result}
        raise ValueError("broker request invalid")

    def _transaction(self, request: dict) -> dict:
        action = request["action"]
        now = datetime.now(timezone.utc)
        scope = request.get("scope")
        if not isinstance(scope, dict) or set(scope) != set(_SCOPE_FIELDS):
            raise ValueError("broker transaction scope invalid")
        if action == "validate" and "bundle" not in request:
            if set(request) != {"action", "scope", "source_workflow_run_id", "transaction_sha256"}:
                raise ValueError("broker request invalid")
            validate_acceptance_run(self.run_ledger, expected_scope=scope,
                source_workflow_run_id=request["source_workflow_run_id"], transaction_sha256=request["transaction_sha256"], now=now)
            return {"result": "valid"}
        if action in {"validate", "verify", "reserve", "nonce"}:
            if set(request) - {"action", "scope", "bundle", "transaction_sha256", "consume_run", "allow_nonce_recovery"}:
                raise ValueError("broker request invalid")
            bundle = request["bundle"]
            source = bundle["events"][0]["payload"]["workflow_run_id"]
            transaction = signed_event_sha256({"bundle": bundle, "scope": scope})
            if request.get("transaction_sha256") not in {None, transaction}:
                raise ValueError("acceptance transaction binding mismatch")
            if action in {"reserve", "nonce", "verify"}:
                try:
                    previous = acceptance_transaction(self.run_ledger, expected_scope=scope,
                        source_workflow_run_id=source, transaction_sha256=transaction, now=now)
                except ValueError:
                    previous = None
                if previous is not None and previous["state"] == "consumed":
                    if action == "verify":
                        return {"verified": previous["verified"], "transaction_sha256": transaction}
                    return previous
            verified = _verify_acceptance_event_bundle_local(
                bundle, expected_scope=scope, now=now,
                nonce_ledger=self.nonce_ledger, _run_ledger=self.run_ledger,
                consume_run=action == "verify" and request.get("consume_run") is True,
                allow_nonce_recovery=True, reserved_transaction_sha256=transaction,
                _preview=action == "validate",
            )
            if action in {"validate", "verify"}:
                return {"verified": verified, "transaction_sha256": transaction}
            return acceptance_transaction(self.run_ledger, expected_scope=scope,
                source_workflow_run_id=source, transaction_sha256=transaction, now=now)
        fields = {"action", "scope", "source_workflow_run_id", "transaction_sha256"}
        if set(request) != fields | ({"content_base64"} if action == "stage" else set()):
            raise ValueError("broker request invalid")
        arguments = {"expected_scope": scope, "source_workflow_run_id": request["source_workflow_run_id"],
                     "transaction_sha256": request["transaction_sha256"], "now": now}
        record = acceptance_transaction(self.run_ledger, **arguments, begin=action == "begin")
        if action == "begin":
            return {**record, "result": "started"}
        if action == "stage":
            if not record["started"]:
                raise ValueError("Process begin required before stage")
            content = base64.b64decode(request["content_base64"], validate=True)
            document = json.loads(content)
            if (not isinstance(document, dict) or document.get("commit") != scope["release_sha"]
                or document.get("acceptance_transaction_sha256") != request["transaction_sha256"]
                or any(document.get(key) != value for key, value in record["verified"].items())):
                raise ValueError("acceptance output binding mismatch")
            if record["state"] == "consumed":
                if record["content_base64"] != request["content_base64"]:
                    raise ValueError("acceptance output changed during recovery")
            else:
                stage_acceptance_output(self.run_ledger, **arguments, content=content)
            return acceptance_transaction(self.run_ledger, **arguments)
        if action == "complete":
            if not record["content_base64"]:
                raise ValueError("acceptance staged output missing")
            content = base64.b64decode(record["content_base64"], validate=True)
            # Output locations are server-owned and never supplied by a peer.
            output = self.run_ledger.parent / "outputs" / scope["run_id"] / "R297_PROCESS_ACCEPTANCE_EVIDENCE.json"
            sidecar = Path(f"{output}.sha256")
            if sidecar.exists() and sidecar.lstat().st_nlink == 1:
                for path in (output, sidecar):
                    meta = path.lstat()
                    if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_uid != os.geteuid() or stat.S_IMODE(meta.st_mode) != 0o600:
                        raise ValueError("acceptance publication metadata invalid")
                if output.read_bytes() != content or sidecar.read_bytes() != f"{hashlib.sha256(content).hexdigest()}  {output.name}\n".encode():
                    raise ValueError("acceptance publication changed")
            else:
                write_sha256_bound_file(output, content)
            complete_acceptance_run(self.run_ledger, **arguments, published_path=output)
            return acceptance_transaction(self.run_ledger, **arguments)
        return record

    def _ack(self, request: dict) -> dict:
        required = {"action", "scope", "source_workflow_run_id", "raw_event", "receiver_content_base64", "observer_content_base64"}
        if (set(request) != required or not isinstance(request["scope"], dict)
            or set(request["scope"]) != set(_SCOPE_FIELDS)
            or type(request["source_workflow_run_id"]) is not int or request["source_workflow_run_id"] <= 0):
            raise ValueError("broker request invalid")
        scope, raw = request["scope"], request["raw_event"]
        contents = [base64.b64decode(request[name], validate=True) for name in ("receiver_content_base64", "observer_content_base64")]
        events = [json.loads(content) for content in contents]
        page, observer = events
        if (not isinstance(raw, dict) or set(raw) != {"event", "observed_at", "release_sha", "store_id"}
            or type(raw["store_id"]) is not int
            or raw != {"event": "web_page_close", "observed_at": page["observed_at"], "release_sha": scope["release_sha"], "store_id": scope["store_id"]}):
            raise ValueError("raw event binding mismatch")
        now = datetime.now(timezone.utc)
        def persist(runs):
            records = [record for record in runs if record.get("run_id") == scope["run_id"]]
            if len(records) != 1:
                raise ValueError("acceptance run missing")
            record = records[0]
            _require_observation_live(record, now)
            if record.get("source_workflow_run_id") != request["source_workflow_run_id"] or any(type(record.get(k)) is not type(v) or record.get(k) != v for k, v in scope.items()):
                raise ValueError("acceptance run scope mismatch")
            receipts = record.get("event_receipts", [])
            if len(receipts) < 2:
                raise ValueError("acceptance event receipt chain missing")
            for i, event in enumerate(events):
                if (event.get("sequence") != i + 1 or receipts[i]["event_sha256"] != signed_event_sha256(event)
                    or any(type(event.get(k)) is not type(v) or event.get(k) != v for k, v in scope.items())):
                    raise ValueError("acceptance event receipt binding mismatch")
                event_type, role = _ORDER[i]
                verify_signed_event(event, event_type=event_type, issuer=_ISSUER[role],
                    environment=os.getenv("APP_ENV", ""), now=datetime.fromisoformat(receipts[i]["received_at"]))
            validate_page_event_payload(page["payload"])
            if page["payload"]["workflow_run_id"] != request["source_workflow_run_id"]:
                raise ValueError("source workflow binding mismatch")
            _observer_result(observer, page, scope["store_id"])
            snapshot = self.snapshot_root / scope["run_id"] / "acceptance-run-binding.json"
            value = {
                "schema_version": 1, "verifier_id": "tiantong-r297-ack-broker-v1", "result": "VERIFIED",
                "verified_at": now.isoformat(), "binding_file_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                "receiver_ack_file_sha256": hashlib.sha256(contents[0]).hexdigest(),
                "observer_ack_file_sha256": hashlib.sha256(contents[1]).hexdigest(),
                "raw_event_sha256": signed_event_sha256(raw),
                "receiver_event_sha256": signed_event_sha256(page), "observer_event_sha256": signed_event_sha256(observer),
            }
            previous = record.get("ack_verification")
            if previous is not None:
                if any(previous.get(k) != v for k, v in value.items() if k != "verified_at"):
                    raise ValueError("ACK verification binding mismatch")
                return previous
            record["ack_verification"] = value
            return value
        value = _update(self.run_ledger, persist, now=now)
        root = self.snapshot_root / scope["run_id"] / "ack"
        root.mkdir(mode=0o700, exist_ok=True)
        receiver_path, observer_path = root / "01-pagehide.json", root / "02-observer.json"
        for event_path, content in zip((receiver_path, observer_path), contents):
            self._publish_readonly(event_path, content)
        path = root / "ack-broker-result.json"
        self._publish_readonly(path, (json.dumps(value, sort_keys=True) + "\n").encode())
        return {"result": "verified", "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "receiver_path": str(receiver_path), "observer_path": str(observer_path),
                "binding_path": str(self.snapshot_root / scope["run_id"] / "acceptance-run-binding.json")}

    def _publish_readonly(self, path: Path, content: bytes) -> None:
        parent = path.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) not in {0o700, 0o755}:
            raise ValueError("publication directory invalid")
        sidecar = Path(f"{path}.sha256")
        expected = f"{hashlib.sha256(content).hexdigest()}  {path.name}\n".encode()
        if sidecar.exists() and sidecar.lstat().st_nlink == 1:
            for member, wanted in ((path, content), (sidecar, expected)):
                meta = member.lstat()
                if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.geteuid() or meta.st_nlink != 1
                    or stat.S_IMODE(meta.st_mode) not in {0o444, 0o600} or member.read_bytes() != wanted):
                    raise ValueError("publication changed")
        else:
            # The same Broker publishes several immutable files in this directory.
            # Temporarily restore the private staging mode; no peer can write it.
            path.parent.chmod(0o700)
            write_sha256_bound_file(path, content)
        path.chmod(0o444)
        sidecar.chmod(0o444)
        path.parent.chmod(0o755)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        from ops.r297_broker_client import peer_uid
        self.request.settimeout(15)
        uid = peer_uid(self.request)
        line = self.rfile.readline(_MAX_REQUEST_BYTES + 1)
        if not line or len(line) > _MAX_REQUEST_BYTES:
            return
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("broker request invalid")
            response = {"ok": True, "value": self.server.broker.dispatch(request, peer_uid=uid)}
        except (KeyError, OSError, RuntimeError, ValueError, TypeError, IndexError) as exc:
            code = "INVALID_REQUEST"
            if isinstance(exc, PermissionError):
                code = "PERMISSION_DENIED"
            elif "PROCESS_SIDE_EFFECTS_UNKNOWN" in str(exc):
                code = "PROCESS_SIDE_EFFECTS_UNKNOWN"
            elif str(exc) == "RECEIPT_NOT_VERIFIED":
                code = "RECEIPT_NOT_VERIFIED"
            elif "expired" in str(exc):
                code = "RECOVERY_EXPIRED"
            elif isinstance(exc, OSError):
                code = "IO_RETRY"
            elif any(word in str(exc) for word in ("mismatch", "changed", "replay", "different")):
                code = "TRANSACTION_CONFLICT"
            response = {"ok": False, "error": code}
        try:
            self.wfile.write((json.dumps(response, sort_keys=True) + "\n").encode())
        except OSError:
            pass  # The durable result is recovered by retry, not rolled back on a lost response.


class _Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = False


def serve(socket_path: Path, broker: EvidenceBroker, *, socket_group: str) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    parent = socket_path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or stat.S_IMODE(parent.st_mode) & 0o022:
        raise RuntimeError("broker socket directory untrusted")
    descriptor = os.open(Path(f"{socket_path}.lock"), os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    metadata = os.fstat(descriptor)
    if metadata.st_uid != 0 or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or stat.S_IMODE(metadata.st_mode) != 0o600:
        os.close(descriptor)
        raise RuntimeError("broker lock untrusted")
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if socket_path.exists() or socket_path.is_symlink():
            metadata = socket_path.lstat()
            if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != 0:
                raise RuntimeError("broker socket path occupied")
            socket_path.unlink()
        with _Server(str(socket_path), _Handler) as server:
            server.broker = broker
            os.chown(socket_path, 0, grp.getgrnam(socket_group).gr_gid)
            socket_path.chmod(0o660)
            server.serve_forever()
    finally:
        os.close(descriptor)


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
