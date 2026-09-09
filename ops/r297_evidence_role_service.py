#!/usr/bin/env python3
"""Narrow local RPC for the isolated page Receiver and database Observer."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import grp
import os
from pathlib import Path
import pwd
import socketserver
import stat

from ops.r297_authenticated_observer import (
    _SCOPE_FIELDS,
    _produce_authenticated_observer,
    _record_receipt,
    _validate_subject_event,
    _write_signed_event,
    load_native_pagehide_artifact,
    load_pagehide_artifact_binding,
    produce_page_event_receiver,
    read_scheduler_snapshot,
)
from ops.r297_broker_client import peer_uid
from ops.r297_event_receipt import _read_bound_event
from ops.r297_evidence_events import signed_event_sha256

_MAX = 64 * 1024


def _child(root: Path, name: str) -> Path:
    if not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."}:
        raise ValueError("role service path invalid")
    return root / name


class RoleService:
    def __init__(self, *, role: str, inbox: Path, events: Path, verifier_uid: int):
        self.role, self.inbox, self.events, self.verifier_uid = role, inbox, events, verifier_uid

    def dispatch(self, request: dict, *, uid: int) -> dict:
        if uid != self.verifier_uid:
            raise PermissionError("role service peer denied")
        if self.role == "receiver":
            return self._receive(request)
        if self.role == "windows-relay":
            return self._relay(request)
        return self._observe(request)

    def _receive(self, request: dict) -> dict:
        if set(request) != {"action", "artifact_directory", "artifact_archive", "scope"} or request["action"] != "receive":
            raise ValueError("receiver request invalid")
        scope = request["scope"]
        if not isinstance(scope, dict) or set(scope) != set(_SCOPE_FIELDS):
            raise ValueError("receiver scope invalid")
        environment = os.environ.get("APP_ENV", "")
        raw = load_native_pagehide_artifact(
            _child(self.inbox, request["artifact_directory"]),
            expected_release_sha=scope["release_sha"],
            binding=load_pagehide_artifact_binding(environment),
            archive_path=_child(self.inbox, request["artifact_archive"]),
        )
        binding = Path("/var/lib/tiantong-r297/snapshots") / scope["run_id"] / "acceptance-run-binding.json"
        output = self._output(scope["run_id"], "01-pagehide.json")
        expected_payload = {
            "closed": True, "source": "browser_pagehide",
            **{field: raw[field] for field in (
                "artifact_evidence_sha256", "artifact_archive_sha256", "artifact_id",
                "artifact_name", "workflow_run_id",
            )},
        }
        recovered = output.exists()
        if recovered:
            event = self._recover_event(
                output, "web_page_close", "page_event_receiver", scope,
                expected_payload=expected_payload,
            )
        else:
            event = produce_page_event_receiver(raw, scope, run_binding_path=binding)
            _write_signed_event(output, event)
        _record_receipt(output, event, raw["workflow_run_id"], recover=recovered)
        return {"result": "recorded", "event": event, "source_workflow_run_id": raw["workflow_run_id"]}

    def _observe(self, request: dict) -> dict:
        if set(request) != {"action", "subject", "source_workflow_run_id"} or request["action"] != "observe":
            raise ValueError("observer request invalid")
        source = request["source_workflow_run_id"]
        if type(source) is not int or source <= 0:
            raise ValueError("observer source run invalid")
        subject = request["subject"]
        if not isinstance(subject, dict):
            raise ValueError("observer subject invalid")
        output = self._output(subject["run_id"], f"{subject['sequence'] + 1:02d}-observer.json")
        recovered = output.exists()
        if recovered:
            event = self._recover_event(output, "authenticated_observer", "authenticated_observer", {
                field: subject[field] for field in _SCOPE_FIELDS
            }, subject=subject)
        else:
            now = datetime.now(timezone.utc)
            environment = os.environ.get("APP_ENV", "")
            manifest = _validate_subject_event(subject, environment, now=now)
            database_url = os.environ.get("R297_OBSERVER_DATABASE_URL", "")
            if not database_url:
                raise RuntimeError("observer database URL missing")
            event = _produce_authenticated_observer(
                subject, read_scheduler_snapshot(database_url, subject),
                observed_at=now, environment=environment, manifest=manifest,
            )
            _write_signed_event(output, event)
        _record_receipt(output, event, source, recover=recovered)
        return {"result": "recorded", "event": event}

    def _relay(self, request: dict) -> dict:
        if set(request) != {"action", "event", "source_workflow_run_id"} or request["action"] != "relay":
            raise ValueError("Windows relay request invalid")
        event, source = request["event"], request["source_workflow_run_id"]
        if not isinstance(event, dict) or type(source) is not int or source <= 0:
            raise ValueError("Windows relay request invalid")
        output = self._output(event["run_id"], "03-electron-exit.json")
        recovered_existing = output.exists()
        if recovered_existing:
            recovered = self._recover_event(output, "electron_exit", "windows_runner", {
                field: event[field] for field in _SCOPE_FIELDS
            })
            if signed_event_sha256(recovered) != signed_event_sha256(event):
                raise ValueError("Windows relay event changed")
            event = recovered
        else:
            _validate_subject_event(event, os.environ.get("APP_ENV", ""), now=datetime.now(timezone.utc))
            _write_signed_event(output, event)
        _record_receipt(output, event, source, recover=recovered_existing)
        return {"result": "recorded", "event": event}

    def _output(self, run_id: str, name: str) -> Path:
        if not isinstance(run_id, str) or not run_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-" for character in run_id):
            raise ValueError("run id invalid")
        root = _child(self.events, run_id)
        root.mkdir(mode=0o700, exist_ok=True)
        return root / name

    @staticmethod
    def _recover_event(
        path: Path, event_type: str, issuer: str, scope: dict,
        subject: dict | None = None, expected_payload: dict | None = None,
    ) -> dict:
        content = path.read_bytes()
        sidecar = Path(f"{path}.sha256")
        if not sidecar.exists():
            from ops.r297_evidence_events import write_sha256_bound_file
            write_sha256_bound_file(path, content)
        event = _read_bound_event(path)
        if any(type(event.get(field)) is not type(value) or event.get(field) != value for field, value in scope.items()):
            raise ValueError("role event recovery scope mismatch")
        if subject is not None and (
            event.get("sequence") != subject["sequence"] + 1
            or event.get("payload", {}).get("subject_nonce") != subject.get("nonce")
            or event.get("payload", {}).get("subject_event_sha256") != signed_event_sha256(subject)
        ):
            raise ValueError("role event recovery subject mismatch")
        if expected_payload is not None:
            payload = dict(event.get("payload", {}))
            payload.pop("freshness_receipt", None)
            if payload != expected_payload:
                raise ValueError("role event recovery artifact mismatch")
        return event


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(20)
        line = self.rfile.readline(_MAX + 1)
        if not line or len(line) > _MAX:
            return
        try:
            value = self.server.service.dispatch(json.loads(line), uid=peer_uid(self.request))
            response = {"ok": True, "value": value}
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            response = {"ok": False, "error": "ROLE_REQUEST_REJECTED"}
        self.wfile.write((json.dumps(response, sort_keys=True) + "\n").encode())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("receiver", "observer", "windows-relay"), required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--inbox", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--socket-group", default="r297-evidence-producers")
    args = parser.parse_args()
    service = RoleService(role=args.role, inbox=args.inbox, events=args.events,
                          verifier_uid=pwd.getpwnam("r297-verifier").pw_uid)
    if args.socket.exists() or args.socket.is_symlink():
        meta = args.socket.lstat()
        if not stat.S_ISSOCK(meta.st_mode):
            raise RuntimeError("role socket path occupied")
        args.socket.unlink()
    with socketserver.UnixStreamServer(str(args.socket), _Handler) as server:
        server.service = service
        os.chown(args.socket, os.geteuid(), grp.getgrnam(args.socket_group).gr_gid)
        args.socket.chmod(0o660)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
