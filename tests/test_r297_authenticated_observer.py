from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import secrets
import sys
import uuid
import zipfile

import psycopg2
import pytest
from psycopg2 import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def _page_event(observed_at: datetime) -> dict:
    from tests.test_r297_evidence_event_protocol import _sign

    return _sign({
        "namespace": "r297-acceptance-0850641e7b62",
        "tenant_id": 1,
        "company_id": 2,
        "store_id": 7,
        "platform": "jd",
        "release_sha": "0850641e7b624109e7a30456889fdbd2331d8d75",
        "event_type": "web_page_close",
        "issuer": "page_event_receiver",
        "observed_at": observed_at.isoformat(),
        "sequence": 1,
        "nonce": "page-close-nonce-0001",
        "payload": {
            "closed": True, "source": "browser_pagehide",
            "artifact_evidence_sha256": "1" * 64,
            "artifact_archive_sha256": "2" * 64,
            "artifact_id": 9965082823,
            "artifact_name": "r297-native-pagehide-test",
            "workflow_run_id": 33949515935,
        },
    })


def test_native_pagehide_artifact_is_raw_input_not_observer_result(tmp_path):
    from ops.r297_authenticated_observer import load_native_pagehide_artifact

    release = "0850641e7b624109e7a30456889fdbd2331d8d75"
    evidence_name = f"r297-native-pagehide-evidence-{release}.json"
    evidence = {
        "schema_version": "1.0",
        "release_sha": release,
        "generator_sha": release,
        "frontend_source_diff": "EMPTY",
        "playwright_operations": [],
        "event_listener": 'window.addEventListener("pagehide", handler)',
        "native_events": [{
            "event": "pagehide",
            "observed_at": "2026-09-05T07:12:06.706Z",
            "event_is_trusted": True,
            "event_constructor": "PageTransitionEvent",
        }],
        "raw_events": [{
            "event": "web_page_close",
            "observed_at": "2026-09-05T07:12:06.709Z",
            "store_id": 7,
            "release_sha": release,
        }],
        "synthetic_event_rejected": {"constructed_event": False, "plain_object": False},
    }
    evidence_bytes = (json.dumps(evidence, indent=2) + "\n").encode()
    (tmp_path / evidence_name).write_bytes(evidence_bytes)
    digest = hashlib.sha256(evidence_bytes).hexdigest()
    (tmp_path / f"{evidence_name}.sha256").write_text(f"{digest}  {evidence_name}\n")
    (tmp_path / f"r297-native-pagehide-manifest-{release}.json").write_text(json.dumps({
        "schema_version": "1.0",
        "release_sha": release,
        "evidence_file": evidence_name,
        "evidence_sha256": digest,
    }))

    result = load_native_pagehide_artifact(tmp_path, expected_release_sha=release)

    assert result == {
        "artifact_evidence_sha256": digest,
        "event_type": "web_page_close",
        "observed_at": "2026-09-05T07:12:06.709Z",
        "release_sha": release,
        "store_id": 7,
    }
    assert "scheduler_continues" not in result


def test_native_pagehide_artifact_rejects_cross_head(tmp_path):
    from ops.r297_authenticated_observer import load_native_pagehide_artifact

    (tmp_path / "r297-native-pagehide-manifest-old.json").write_text("{}")
    with pytest.raises(ValueError, match="pagehide artifact release mismatch"):
        load_native_pagehide_artifact(tmp_path, expected_release_sha="0" * 40)


def test_native_pagehide_artifact_rejects_path_escape(tmp_path):
    from ops.r297_authenticated_observer import load_native_pagehide_artifact

    release = "0850641e7b624109e7a30456889fdbd2331d8d75"
    (tmp_path / f"r297-native-pagehide-manifest-{release}.json").write_text(json.dumps({
        "schema_version": "1.0", "release_sha": release,
        "evidence_file": "../outside.json", "evidence_sha256": "0" * 64,
    }))

    with pytest.raises(ValueError, match="pagehide artifact file path invalid"):
        load_native_pagehide_artifact(tmp_path, expected_release_sha=release)


def test_native_pagehide_artifact_binds_protected_archive(monkeypatch, tmp_path):
    from ops.r297_authenticated_observer import load_native_pagehide_artifact, load_pagehide_artifact_binding

    release = "0850641e7b624109e7a30456889fdbd2331d8d75"
    evidence_name = f"r297-native-pagehide-evidence-{release}.json"
    evidence = {
        "release_sha": release, "generator_sha": release,
        "native_events": [{"event": "pagehide", "event_is_trusted": True}],
        "raw_events": [{
            "event": "web_page_close", "observed_at": "2026-09-05T07:12:06.709Z",
            "store_id": 7, "release_sha": release,
        }],
        "synthetic_event_rejected": {"constructed_event": False, "plain_object": False},
    }
    evidence_bytes = json.dumps(evidence).encode()
    evidence_digest = hashlib.sha256(evidence_bytes).hexdigest()
    files = {
        evidence_name: evidence_bytes,
        f"{evidence_name}.sha256": f"{evidence_digest}  {evidence_name}\n".encode(),
        f"r297-native-pagehide-manifest-{release}.json": json.dumps({
            "schema_version": "1.0", "release_sha": release,
            "evidence_file": evidence_name, "evidence_sha256": evidence_digest,
        }).encode(),
    }
    content_root = tmp_path / "content"
    content_root.mkdir()
    for name, content in files.items():
        (content_root / name).write_bytes(content)
    archive_path = tmp_path / "artifact.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    binding = {
        "schema_version": 1, "artifact_id": 9965082823,
        "artifact_name": "r297-native-pagehide-test", "workflow_run_id": 33949515935,
        "release_sha": release,
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "evidence_sha256": evidence_digest,
    }
    binding_path = tmp_path / "binding.json"
    binding_bytes = json.dumps(binding).encode()
    binding_path.write_bytes(binding_bytes)
    binding_path.chmod(0o400)
    sidecar_path = binding_path.with_name(f"{binding_path.name}.sha256")
    sidecar_path.write_text(f"{hashlib.sha256(binding_bytes).hexdigest()}  {binding_path.name}\n")
    sidecar_path.chmod(0o400)
    monkeypatch.setenv("R297_PAGEHIDE_TEST_BINDING_PATH", str(binding_path))

    trusted_binding = load_pagehide_artifact_binding("test")
    result = load_native_pagehide_artifact(
        content_root, expected_release_sha=release, binding=trusted_binding, archive_path=archive_path,
    )

    assert result["artifact_id"] == 9965082823
    assert result["artifact_archive_sha256"] == binding["archive_sha256"]

    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr(evidence_name, evidence_bytes)
    binding["archive_sha256"] = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="pagehide artifact archive content mismatch"):
        load_native_pagehide_artifact(
            content_root, expected_release_sha=release, binding=binding, archive_path=archive_path,
        )


def test_native_pagehide_artifact_rejects_client_scheduler_claim(tmp_path):
    from ops.r297_authenticated_observer import load_native_pagehide_artifact

    release = "0850641e7b624109e7a30456889fdbd2331d8d75"
    evidence_name = f"r297-native-pagehide-evidence-{release}.json"
    evidence = {
        "release_sha": release,
        "generator_sha": release,
        "native_events": [{"event": "pagehide", "event_is_trusted": True}],
        "raw_events": [{
            "event": "web_page_close", "observed_at": "2026-09-05T07:12:06.709Z",
            "store_id": 7, "release_sha": release, "scheduler_continues": True,
        }],
        "synthetic_event_rejected": {"constructed_event": False, "plain_object": False},
    }
    evidence_bytes = json.dumps(evidence).encode()
    digest = hashlib.sha256(evidence_bytes).hexdigest()
    (tmp_path / evidence_name).write_bytes(evidence_bytes)
    (tmp_path / f"{evidence_name}.sha256").write_text(f"{digest}  {evidence_name}\n")
    (tmp_path / f"r297-native-pagehide-manifest-{release}.json").write_text(json.dumps({
        "schema_version": "1.0", "release_sha": release,
        "evidence_file": evidence_name, "evidence_sha256": digest,
    }))

    with pytest.raises(ValueError, match="pagehide artifact content invalid"):
        load_native_pagehide_artifact(tmp_path, expected_release_sha=release)


def test_page_event_receiver_signs_raw_artifact_with_separate_test_key(monkeypatch, tmp_path):
    from ops.r297_authenticated_observer import produce_page_event_receiver
    from ops.r297_evidence_events import _verify_signature, load_trust_manifest
    from tests.test_r297_evidence_event_protocol import _PRIVATE_KEYS

    monkeypatch.setenv("APP_ENV", "test")
    modulus, private = _PRIVATE_KEYS["page_event_receiver"]
    private_path = tmp_path / "page-receiver-test-key.json"
    private_path.write_text(json.dumps({
        "environment": "test", "key_id": "r297-page_event_receiver-test", "n": modulus, "d": private,
    }))
    private_path.chmod(0o600)
    monkeypatch.setenv("R297_PAGE_EVENT_RECEIVER_TEST_PRIVATE_KEY_PATH", str(private_path))
    scope = {
        "namespace": "r297-acceptance-0850641e7b62", "tenant_id": 1, "company_id": 2,
        "store_id": 7, "platform": "jd", "release_sha": "0850641e7b624109e7a30456889fdbd2331d8d75",
    }
    event = produce_page_event_receiver({
        "event_type": "web_page_close", "observed_at": "2026-09-05T07:12:06.709Z",
        "store_id": 7, "release_sha": scope["release_sha"],
        "artifact_evidence_sha256": "1" * 64, "artifact_archive_sha256": "2" * 64,
        "artifact_id": 9965082823, "artifact_name": "r297-native-pagehide-test",
        "workflow_run_id": 33949515935,
    }, scope)

    assert event["payload"]["artifact_id"] == 9965082823
    assert event["issuer"] == "page_event_receiver"
    manifest, _ = load_trust_manifest(environment="test")
    page_key = next(key for key in manifest["keys"] if key["issuer"] == "page_event_receiver")
    _verify_signature(event, page_key)


def test_observer_event_is_signed_from_read_only_database_snapshot(monkeypatch, tmp_path):
    from ops.r297_authenticated_observer import produce_authenticated_observer
    from ops.r297_evidence_events import _verify_signature, load_trust_manifest, signed_event_sha256
    from tests.test_r297_evidence_event_protocol import _PRIVATE_KEYS

    monkeypatch.setenv("APP_ENV", "test")
    modulus, private = _PRIVATE_KEYS["authenticated_observer"]
    private_path = tmp_path / "observer-test-key.json"
    private_path.write_text(json.dumps({
        "environment": "test",
        "key_id": "r297-authenticated_observer-test",
        "n": modulus,
        "d": private,
    }))
    private_path.chmod(0o600)
    monkeypatch.setenv("R297_OBSERVER_TEST_PRIVATE_KEY_PATH", str(private_path))
    now = datetime(2026, 9, 5, 7, 12, 10, tzinfo=timezone.utc)
    page = _page_event(now - timedelta(seconds=3))
    snapshot = {
        "database_read_only": True,
        "write_privilege_count": 0,
        "policy_enabled": True,
        "cloud_cycles_before": 2,
        "cloud_cycles_after": 3,
        "eligible_store_ids": [7],
        "collected_store_ids_after": [7],
    }

    event = produce_authenticated_observer(page, snapshot, observed_at=now)

    assert {field: event[field] for field in (
        "namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha",
    )} == {field: page[field] for field in (
        "namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha",
    )}
    assert event["payload"]["subject_nonce"] == page["nonce"]
    assert event["payload"]["subject_event_sha256"] == signed_event_sha256(page)
    assert event["payload"]["scheduler_continues"] is True
    manifest, _ = load_trust_manifest(environment="test")
    observer_key = next(key for key in manifest["keys"] if key["issuer"] == "authenticated_observer")
    _verify_signature(event, observer_key)


def test_observer_signing_fails_closed_without_deployment_secret(monkeypatch):
    from ops.r297_authenticated_observer import produce_authenticated_observer

    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.delenv("R297_OBSERVER_PRIVATE_KEY_PATH", raising=False)
    now = datetime(2026, 9, 5, 7, 12, 10, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError, match="observer private key missing"):
        produce_authenticated_observer(_page_event(now - timedelta(seconds=1)), {
            "database_read_only": True,
            "write_privilege_count": 0,
            "policy_enabled": True,
            "cloud_cycles_before": 1,
            "cloud_cycles_after": 2,
            "eligible_store_ids": [7],
            "collected_store_ids_after": [7],
        }, observed_at=now)


def test_observer_cli_rejects_bad_signature_before_database_connect(monkeypatch, tmp_path):
    from ops import r297_authenticated_observer

    page = _page_event(datetime.now(timezone.utc))
    page["signature"] = "invalid-signature"
    page_path = tmp_path / "page.json"
    page_path.write_text(json.dumps(page))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("R297_OBSERVER_DATABASE_URL", "postgresql://must-not-connect")
    monkeypatch.setattr(sys, "argv", ["observer", "observe", str(page_path), str(tmp_path / "out")])
    monkeypatch.setattr(
        r297_authenticated_observer.psycopg2, "connect",
        lambda *_args, **_kwargs: pytest.fail("database was queried before signature validation"),
    )

    with pytest.raises(ValueError, match="invalid evidence signature"):
        r297_authenticated_observer.main()


def test_observer_reads_real_postgresql_with_read_only_role(postgres_database_factory):
    from backend.models import Company, JdSyncLog, JdWorkbenchSyncPolicy, Store, Tenant
    from ops.r297_authenticated_observer import read_scheduler_snapshot
    from tests.conftest import _alembic

    database_url = postgres_database_factory("r297_observer")
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    page_time = datetime.now(timezone.utc) - timedelta(seconds=5)
    db = sessions()
    try:
        tenant = Tenant(tenant_code=f"observer-{uuid.uuid4().hex[:8]}", tenant_name="Observer")
        db.add(tenant)
        db.flush()
        company = Company(
            tenant_id=tenant.id, company_code=f"observer-{uuid.uuid4().hex[:8]}", company_name="Observer",
        )
        db.add(company)
        db.flush()
        store = Store(
            tenant_id=tenant.id, company_id=company.id, platform="jd",
            store_code=f"observer-{uuid.uuid4().hex[:8]}", store_name="Observer",
        )
        db.add(store)
        db.flush()
        db.add(JdWorkbenchSyncPolicy(
            tenant_id=tenant.id, company_id=company.id, store_id=store.id, enabled=True,
        ))
        db.add_all([
            JdSyncLog(
                tenant_id=tenant.id, company_id=company.id, store_id=store.id,
                task_id=str(uuid.uuid4()), task_type="sync_jd_smart", source="cloud_scheduler",
                status="success", attempt=0, sync_window_started_at=page_time - timedelta(minutes=5),
                finished_at=page_time - timedelta(seconds=1),
            ),
            JdSyncLog(
                tenant_id=tenant.id, company_id=company.id, store_id=store.id,
                task_id=str(uuid.uuid4()), task_type="sync_jd_smart", source="cloud_scheduler",
                status="success", attempt=0, sync_window_started_at=page_time,
                finished_at=page_time + timedelta(seconds=1),
            ),
        ])
        db.commit()
        scope = {
            "namespace": "r297-acceptance-real-pg",
            "tenant_id": tenant.id,
            "company_id": company.id,
            "store_id": store.id,
            "platform": "jd",
            "release_sha": "0850641e7b624109e7a30456889fdbd2331d8d75",
            "event_type": "web_page_close",
            "issuer": "page_event_receiver",
            "observed_at": page_time.isoformat(),
        }
    finally:
        db.close()

    role = f"r297_observer_{uuid.uuid4().hex[:12]}"
    password = secrets.token_urlsafe(24)
    admin_url = make_url(database_url)
    admin_dsn = admin_url.set(drivername="postgresql").render_as_string(hide_password=False)
    connection = psycopg2.connect(admin_dsn)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD %s").format(sql.Identifier(role)), (password,))
            cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(admin_url.database), sql.Identifier(role),
            ))
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
            cursor.execute(sql.SQL(
                "GRANT SELECT ON stores, jd_workbench_sync_policies, jd_sync_logs TO {}"
            ).format(sql.Identifier(role)))
        observer_url = admin_url.set(username=role, password=password).render_as_string(hide_password=False)
        snapshot = read_scheduler_snapshot(observer_url, scope)
        assert snapshot == {
            "database_read_only": True,
            "write_privilege_count": 0,
            "policy_enabled": True,
            "cloud_cycles_before": 1,
            "cloud_cycles_after": 2,
            "eligible_store_ids": [store.id],
            "collected_store_ids_after": [store.id],
        }
    finally:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(role)))
            cursor.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
        connection.close()
        engine.dispose()
