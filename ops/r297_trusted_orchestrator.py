#!/usr/bin/env python3
"""Verifier-only orchestration across the keyless Broker and isolated producers."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from ops.r297_broker_client import broker_request
from ops.r297_evidence_bundle import build_bundle
from ops.r297_evidence_events import write_sha256_bound_file
from ops.r297_role_client import role_request


def _bound(path: Path) -> dict:
    content = path.read_bytes()
    if Path(f"{path}.sha256").read_text(encoding="ascii").strip().split() != [hashlib.sha256(content).hexdigest(), path.name]:
        raise RuntimeError("orchestrator input sidecar mismatch")
    return json.loads(content)


def _publish(path: Path, value: dict) -> None:
    content = (json.dumps(value, sort_keys=True) + "\n").encode()
    if path.exists() or Path(f"{path}.sha256").exists():
        if path.exists() and not Path(f"{path}.sha256").exists() and path.read_bytes() == content:
            write_sha256_bound_file(path, content)
        if _bound(path) != value or path.read_bytes() != content:
            raise RuntimeError("orchestrator output changed")
        return
    write_sha256_bound_file(path, content)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receiver-socket", type=Path, default=Path("/run/tiantong-r297-receiver/receiver.sock"))
    parser.add_argument("--observer-socket", type=Path, default=Path("/run/tiantong-r297-observer/observer.sock"))
    parser.add_argument("--relay-socket", type=Path, default=Path("/run/tiantong-r297-windows-relay/windows-relay.sock"))
    sub = parser.add_subparsers(dest="command", required=True)
    issue = sub.add_parser("issue")
    issue.add_argument("output", type=Path)
    for command in (issue,):
        command.add_argument("--namespace", required=True); command.add_argument("--tenant-id", type=int, required=True)
        command.add_argument("--company-id", type=int, required=True); command.add_argument("--store-id", type=int, required=True)
        command.add_argument("--platform", default="jd"); command.add_argument("--release-sha", required=True)
        command.add_argument("--source-workflow-run-id", type=int, required=True); command.add_argument("--run-attempt", type=int, required=True)
    first = sub.add_parser("first-pair")
    first.add_argument("binding", type=Path); first.add_argument("artifact_directory"); first.add_argument("artifact_archive")
    first.add_argument("output", type=Path)
    finish = sub.add_parser("finish")
    finish.add_argument("binding", type=Path); finish.add_argument("first_pair", type=Path)
    finish.add_argument("electron_event", type=Path); finish.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "issue":
        scope = {name: getattr(args, name) for name in ("namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha")}
        result = broker_request({"action": "issue", "scope": scope, "source_workflow_run_id": args.source_workflow_run_id, "run_attempt": args.run_attempt})
        _publish(args.output, result["record"])
        return 0
    binding = _bound(args.binding)
    scope = {name: binding[name] for name in ("namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha", "run_id", "run_attempt", "challenge")}
    source = binding["source_workflow_run_id"]
    if args.command == "first-pair":
        page = role_request(args.receiver_socket, {"action": "receive", "artifact_directory": args.artifact_directory, "artifact_archive": args.artifact_archive, "scope": scope}, expected_user="r297-page-receiver")["event"]
        observer = role_request(args.observer_socket, {"action": "observe", "subject": page, "source_workflow_run_id": source}, expected_user="r297-observer")["event"]
        raw = {"event": "web_page_close", "observed_at": page["observed_at"], "release_sha": scope["release_sha"], "store_id": scope["store_id"]}
        ack = broker_request({
            "action": "ack", "scope": scope, "source_workflow_run_id": source, "raw_event": raw,
            "receiver_content_base64": base64.b64encode((json.dumps(page, sort_keys=True) + "\n").encode()).decode(),
            "observer_content_base64": base64.b64encode((json.dumps(observer, sort_keys=True) + "\n").encode()).decode(),
        })
        _publish(args.output, {"events": [page, observer], "ack": ack})
        return 0
    first_pair = _bound(args.first_pair)
    wrapper = _bound(args.electron_event)
    expected_signer = os.environ.get("R297_TRUSTED_SIGNER_SHA", "")
    if (
        set(wrapper) != {"signer_sha", "event"} or not isinstance(wrapper["event"], dict)
        or wrapper["signer_sha"] != expected_signer
    ):
        raise RuntimeError("trusted Windows output wrapper invalid")
    electron = wrapper["event"]
    relayed = role_request(args.relay_socket, {"action": "relay", "event": electron, "source_workflow_run_id": source}, expected_user="r297-windows-relay")["event"]
    observer = role_request(args.observer_socket, {"action": "observe", "subject": relayed, "source_workflow_run_id": source}, expected_user="r297-observer")["event"]
    bundle = build_bundle([*first_pair["events"], relayed, observer], expected_scope=scope, now=datetime.now(timezone.utc))
    _publish(args.output, bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
