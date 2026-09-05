#!/usr/bin/env python3
"""Produce a signed scheduler observation from a read-only PostgreSQL role."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import zipfile

import psycopg2

try:
    from ops.r297_evidence_events import (
        sign_event,
        load_trust_manifest,
        signed_event_sha256,
        validate_page_event_payload,
        verify_signed_event,
    )
except ModuleNotFoundError as exc:
    if exc.name != "ops":
        raise
    from r297_evidence_events import (
        sign_event,
        load_trust_manifest,
        signed_event_sha256,
        validate_page_event_payload,
        verify_signed_event,
    )


_SHA_RE = re.compile(r"[0-9a-f]{40}")
_ARTIFACT_MANIFEST_RE = re.compile(r"r297-native-pagehide-manifest-[0-9a-f]{40}\.json")
_SCOPE_FIELDS = ("namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha")
_RAW_PAGE_EVENT_FIELDS = {"event", "observed_at", "store_id", "release_sha"}
_PAGEHIDE_BINDING = Path("/etc/tiantong/r297-pagehide-artifact-binding.json")
_BINDING_FIELDS = {
    "schema_version", "artifact_id", "artifact_name", "workflow_run_id",
    "release_sha", "archive_sha256", "evidence_sha256",
}


def _read_binding_file(path: Path, *, environment: str) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        allowed_owner = metadata.st_uid == 0 if environment != "test" else metadata.st_uid == os.geteuid()
        if not stat.S_ISREG(metadata.st_mode) or not allowed_owner or metadata.st_mode & 0o222:
            raise RuntimeError("pagehide artifact binding is not immutable")
        return os.read(descriptor, metadata.st_size)
    finally:
        os.close(descriptor)


def load_pagehide_artifact_binding(environment: str) -> dict:
    test_path = os.getenv("R297_PAGEHIDE_TEST_BINDING_PATH", "")
    if environment == "test" and not test_path:
        raise RuntimeError("pagehide artifact binding missing")
    path = Path(test_path) if environment == "test" else _PAGEHIDE_BINDING
    content = _read_binding_file(path, environment=environment)
    sidecar = _read_binding_file(Path(f"{path}.sha256"), environment=environment).decode("ascii").strip().split()
    digest = hashlib.sha256(content).hexdigest()
    if sidecar != [digest, path.name]:
        raise RuntimeError("pagehide artifact binding sidecar invalid")
    binding = json.loads(content)
    if (
        not isinstance(binding, dict)
        or set(binding) != _BINDING_FIELDS
        or binding.get("schema_version") != 1
        or type(binding.get("artifact_id")) is not int
        or binding["artifact_id"] <= 0
        or type(binding.get("workflow_run_id")) is not int
        or binding["workflow_run_id"] <= 0
        or not _SHA_RE.fullmatch(str(binding.get("release_sha", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(binding.get("archive_sha256", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(binding.get("evidence_sha256", "")))
        or not re.fullmatch(r"r297-native-pagehide-[A-Za-z0-9._-]+", str(binding.get("artifact_name", "")))
    ):
        raise RuntimeError("pagehide artifact binding invalid")
    return binding


def load_native_pagehide_artifact(
    root: Path, *, expected_release_sha: str, binding: dict | None = None,
    archive_path: Path | None = None,
) -> dict:
    """Validate PR #51 output as raw client input, never as an observer result."""
    manifests = [path for path in root.iterdir() if path.is_file() and _ARTIFACT_MANIFEST_RE.fullmatch(path.name)]
    if len(manifests) != 1:
        raise ValueError("pagehide artifact release mismatch")
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    if manifest.get("release_sha") != expected_release_sha:
        raise ValueError("pagehide artifact release mismatch")
    if set(manifest) != {"schema_version", "release_sha", "evidence_file", "evidence_sha256"}:
        raise ValueError("pagehide artifact manifest schema mismatch")
    evidence_name = f"r297-native-pagehide-evidence-{expected_release_sha}.json"
    if manifest["evidence_file"] != evidence_name:
        raise ValueError("pagehide artifact file path invalid")
    evidence_path = root / evidence_name
    sidecar_path = root / f"{manifest['evidence_file']}.sha256"
    expected_names = {manifests[0].name, evidence_path.name, sidecar_path.name}
    if {path.name for path in root.iterdir()} != expected_names or any(
        path.is_symlink() or not path.is_file() for path in (manifests[0], evidence_path, sidecar_path)
    ):
        raise ValueError("pagehide artifact file set mismatch")
    evidence_bytes = evidence_path.read_bytes()
    digest = hashlib.sha256(evidence_bytes).hexdigest()
    sidecar = sidecar_path.read_text(encoding="ascii").strip().split()
    if (
        manifest.get("schema_version") != "1.0"
        or not re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("evidence_sha256", "")))
        or digest != manifest["evidence_sha256"]
        or sidecar != [digest, evidence_path.name]
    ):
        raise ValueError("pagehide artifact digest mismatch")
    evidence = json.loads(evidence_bytes)
    raw_events = evidence.get("raw_events") if isinstance(evidence, dict) else None
    native_events = evidence.get("native_events") if isinstance(evidence, dict) else None
    rejected = evidence.get("synthetic_event_rejected") if isinstance(evidence, dict) else None
    if (
        evidence.get("release_sha") != expected_release_sha
        or evidence.get("generator_sha") != expected_release_sha
        or not isinstance(raw_events, list)
        or len(raw_events) != 1
        or not isinstance(native_events, list)
        or len(native_events) != 1
        or native_events[0].get("event") != "pagehide"
        or native_events[0].get("event_is_trusted") is not True
        or set(raw_events[0]) != _RAW_PAGE_EVENT_FIELDS
        or raw_events[0].get("event") != "web_page_close"
        or raw_events[0].get("release_sha") != expected_release_sha
        or rejected != {"constructed_event": False, "plain_object": False}
        or type(raw_events[0].get("store_id")) is not int
        or raw_events[0]["store_id"] <= 0
    ):
        raise ValueError("pagehide artifact content invalid")
    result = {
        "artifact_evidence_sha256": digest,
        "event_type": "web_page_close",
        "observed_at": raw_events[0]["observed_at"],
        "release_sha": expected_release_sha,
        "store_id": raw_events[0]["store_id"],
    }
    if binding is not None:
        if (
            archive_path is None
            or binding["release_sha"] != expected_release_sha
            or binding["evidence_sha256"] != digest
        ):
            raise ValueError("pagehide artifact provenance mismatch")
        archive_bytes = archive_path.read_bytes()
        if hashlib.sha256(archive_bytes).hexdigest() != binding["archive_sha256"]:
            raise ValueError("pagehide artifact archive digest mismatch")
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if len(members) != len(expected_names) or set(names) != expected_names or any(
                archive.read(member) != (root / member.filename).read_bytes() for member in members
            ):
                raise ValueError("pagehide artifact archive content mismatch")
        result.update({
            "artifact_archive_sha256": binding["archive_sha256"],
            "artifact_id": binding["artifact_id"],
            "artifact_name": binding["artifact_name"],
            "workflow_run_id": binding["workflow_run_id"],
        })
    return result


def read_scheduler_snapshot(database_url: str, page_event: dict) -> dict:
    """Read the exact scoped scheduler state using a role without DML privileges."""
    page_time = datetime.fromisoformat(str(page_event["observed_at"]).replace("Z", "+00:00"))
    database_url = database_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    connection = psycopg2.connect(database_url)
    try:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            if cursor.fetchone()[0] != "on":
                raise RuntimeError("observer database transaction is not read only")
            cursor.execute(
                """
                SELECT count(*) FILTER (WHERE has_table_privilege(current_user, name, 'INSERT,UPDATE,DELETE'))
                FROM unnest(ARRAY['stores','jd_workbench_sync_policies','jd_sync_logs']) AS name
                """
            )
            write_privilege_count = int(cursor.fetchone()[0])
            if write_privilege_count:
                raise RuntimeError("observer database role has write privileges")
            cursor.execute(
                """
                SELECT p.enabled,
                       count(l.id) FILTER (
                           WHERE l.status = 'success' AND l.source = 'cloud_scheduler'
                             AND coalesce(l.finished_at, l.created_at) <= %s
                       ),
                       count(l.id) FILTER (
                           WHERE l.status = 'success' AND l.source = 'cloud_scheduler'
                             AND coalesce(l.finished_at, l.created_at) > %s
                       )
                FROM stores s
                JOIN jd_workbench_sync_policies p
                  ON (p.tenant_id, p.company_id, p.store_id) = (s.tenant_id, s.company_id, s.id)
                LEFT JOIN jd_sync_logs l
                  ON (l.tenant_id, l.company_id, l.store_id) = (s.tenant_id, s.company_id, s.id)
                WHERE s.tenant_id = %s AND s.company_id = %s AND s.id = %s AND s.platform = %s
                GROUP BY p.enabled
                """,
                (
                    page_time,
                    page_time,
                    page_event["tenant_id"],
                    page_event["company_id"],
                    page_event["store_id"],
                    page_event["platform"],
                ),
            )
            row = cursor.fetchone()
        connection.rollback()
    finally:
        connection.close()
    if row is None:
        raise RuntimeError("observer scheduler scope not found")
    enabled, before, since = bool(row[0]), int(row[1]), int(row[2])
    if not enabled or since < 1:
        raise RuntimeError("scheduler did not continue after observed event")
    return {
        "database_read_only": True,
        "write_privilege_count": write_privilege_count,
        "policy_enabled": enabled,
        "cloud_cycles_before": before,
        "cloud_cycles_after": before + since,
        "eligible_store_ids": [page_event["store_id"]],
        "collected_store_ids_after": [page_event["store_id"]],
    }


def produce_page_event_receiver(raw_artifact: dict, authenticated_scope: dict) -> dict:
    """Turn a native client event into a scoped event signed by the trusted receiver."""
    environment = os.getenv("APP_ENV", "").strip().lower()
    if environment not in {"acceptance", "production", "test"}:
        raise RuntimeError("page event receiver environment is not configured")
    if set(authenticated_scope) != set(_SCOPE_FIELDS):
        raise ValueError("authenticated page event scope invalid")
    if (
        raw_artifact.get("event_type") != "web_page_close"
        or raw_artifact.get("store_id") != authenticated_scope["store_id"]
        or raw_artifact.get("release_sha") != authenticated_scope["release_sha"]
    ):
        raise ValueError("pagehide artifact scope mismatch")
    manifest, _ = load_trust_manifest(environment=environment)
    event = {
        **authenticated_scope,
        "event_type": "web_page_close",
        "issuer": "page_event_receiver",
        "observed_at": raw_artifact["observed_at"],
        "sequence": 1,
        "nonce": secrets.token_urlsafe(24),
        "payload": {"closed": True, "source": "browser_pagehide"},
    }
    event["payload"].update({
        "artifact_evidence_sha256": raw_artifact["artifact_evidence_sha256"],
        "artifact_archive_sha256": raw_artifact["artifact_archive_sha256"],
        "artifact_id": raw_artifact["artifact_id"],
        "artifact_name": raw_artifact["artifact_name"],
        "workflow_run_id": raw_artifact["workflow_run_id"],
    })
    validate_page_event_payload(event["payload"])
    return sign_event(event, environment=environment, manifest=manifest, issuer="page_event_receiver")


def _validate_page_event_receiver(page_event: dict, environment: str, *, now: datetime) -> dict:
    if (
        page_event.get("event_type") != "web_page_close"
        or page_event.get("issuer") != "page_event_receiver"
        or not _SHA_RE.fullmatch(str(page_event.get("release_sha", "")))
    ):
        raise ValueError("invalid pagehide subject event")
    validate_page_event_payload(page_event.get("payload"))
    manifest, _ = verify_signed_event(
        page_event, event_type="web_page_close", issuer="page_event_receiver",
        environment=environment, now=now,
    )
    return manifest


def _produce_authenticated_observer(
    page_event: dict, snapshot: dict, *, observed_at: datetime, environment: str, manifest: dict
) -> dict:
    if (
        snapshot.get("database_read_only") is not True
        or snapshot.get("write_privilege_count") != 0
        or snapshot.get("policy_enabled") is not True
        or snapshot.get("cloud_cycles_after", 0) <= snapshot.get("cloud_cycles_before", 0)
    ):
        raise RuntimeError("observer database snapshot invalid")
    event = {
        **{field: page_event[field] for field in _SCOPE_FIELDS},
        "event_type": "authenticated_observer",
        "issuer": "authenticated_observer",
        "observed_at": observed_at.astimezone(timezone.utc).isoformat(),
        "sequence": page_event["sequence"] + 1,
        "nonce": secrets.token_urlsafe(24),
        "payload": {
            "subject_nonce": page_event["nonce"],
            "subject_event_sha256": signed_event_sha256(page_event),
            "scheduler_continues": True,
            "observation_source": "postgresql_scheduler_state",
            "database_read_only": True,
            "cloud_cycles_before": snapshot["cloud_cycles_before"],
            "cloud_cycles_after": snapshot["cloud_cycles_after"],
            "eligible_store_ids": snapshot["eligible_store_ids"],
            "collected_store_ids_after": snapshot["collected_store_ids_after"],
        },
    }
    return sign_event(event, environment=environment, manifest=manifest, issuer="authenticated_observer")


def produce_authenticated_observer(page_event: dict, snapshot: dict, *, observed_at: datetime) -> dict:
    environment = os.getenv("APP_ENV", "").strip().lower()
    if environment not in {"acceptance", "production", "test"}:
        raise RuntimeError("observer environment is not configured")
    private_key_variable = (
        "R297_OBSERVER_TEST_PRIVATE_KEY_PATH" if environment == "test" else "R297_OBSERVER_PRIVATE_KEY_PATH"
    )
    if not os.getenv(private_key_variable, ""):
        raise RuntimeError("observer private key missing")
    manifest = _validate_page_event_receiver(page_event, environment, now=observed_at)
    return _produce_authenticated_observer(
        page_event, snapshot, observed_at=observed_at, environment=environment, manifest=manifest
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    receive = subparsers.add_parser("receive")
    receive.add_argument("artifact_root", type=Path)
    receive.add_argument("artifact_archive", type=Path)
    receive.add_argument("output", type=Path)
    receive.add_argument("--namespace", required=True)
    receive.add_argument("--tenant-id", type=int, required=True)
    receive.add_argument("--company-id", type=int, required=True)
    receive.add_argument("--store-id", type=int, required=True)
    receive.add_argument("--platform", required=True)
    receive.add_argument("--release-sha", required=True)
    observe = subparsers.add_parser("observe")
    observe.add_argument("page_event", type=Path)
    observe.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "receive":
        scope = {field: getattr(args, field) for field in _SCOPE_FIELDS}
        environment = os.getenv("APP_ENV", "").strip().lower()
        binding = load_pagehide_artifact_binding(environment)
        raw = load_native_pagehide_artifact(
            args.artifact_root, expected_release_sha=args.release_sha,
            binding=binding, archive_path=args.artifact_archive,
        )
        event = produce_page_event_receiver(raw, scope)
        args.output.write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
        args.output.chmod(0o600)
        return 0
    database_url = os.getenv("R297_OBSERVER_DATABASE_URL", "")
    if not database_url:
        raise RuntimeError("observer database URL missing")
    page_event = json.loads(args.page_event.read_text(encoding="utf-8"))
    environment = os.getenv("APP_ENV", "").strip().lower()
    observed_at = datetime.now(timezone.utc)
    manifest = _validate_page_event_receiver(page_event, environment, now=observed_at)
    snapshot = read_scheduler_snapshot(database_url, page_event)
    event = _produce_authenticated_observer(
        page_event, snapshot, observed_at=observed_at,
        environment=environment, manifest=manifest,
    )
    args.output.write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
    args.output.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
