from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

import pytest

from ops.r297_evidence_events import (
    load_trust_manifest, signed_event_sha256, verify_acceptance_event_bundle,
    write_sha256_bound_file,
)
from tests.test_r291_jd_workbench_cloud import TEST_RSA_D, TEST_RSA_N_B64


_PAGE_N = "yZNc_C6r9P7c1DgsOoyxwx2xaJq-NQx0C-2nkJgx0FTeTsL-usd7DVMEXMXHh-IHZEy_rgC43cGo41RgbIXJgEBmffUGjz3I5LH_w3LGs9aJaNnkalHRGJFzKgH5Qz7o9mj65asJ2GGZUl6qEOZ7wmrApOZmGzQ6FQ8cPD6u3Cl5GaFBJpnvE1QL2Rzpg90AEFIeRLU_9d1zy53mBtXE6GwPljagVaaotw4GZrgxBquOd8Q0_IQf-MLEdgwhksw6lbUQuEfVb4JW0tuxVd0F9iBtQTSNKXMiW8d0hxBQ1FzLfcjBXQgfhaY9-BHp3yp8hfPiDjmW7917mj3oPL-odQ"
_PAGE_D = "BXdB8q3bw4JO5zy5KMLQNLKxk3C2H_WCBtKfXfKsY21TjPH1k4ebDYI1scPYFbOi3OgBF4DI5PbIIlvEb7uqNWdOkWS2bPnCiAN3S9CuAR3DXaHdX5LR6b1msxxxqqI16lTmGfx-snaWu2sOBX5fYLqrZHSt-38q5KNK3ma3zZH8vmdXpxwEgW0u9sSiSKmE1oAxlYcxQVjGXwU37hGQ3yvO-1Q3MoPlRrwW7Nyxd7ADjIQHbwbR7-YeiSJUZmAVApqGdY9cyI53X6kvmQ9fg_v_NhU667J6LFaZkm3lIJloOnPJTFnYDnxjZW7XnDr_fgqXFPjw3dfkr33oo_rQyQ"
_WINDOWS_N = "3gopfQl3LtI1-yVIGGVF5wrt7ab-Z5rj-N36Efuy7gFv428S5KyQFf_JXvl_StuiIcnb44I44hVUdZMeBAlAFvnoCyagOI8sU2TDkm0PoZGGHuXRBYN4j76O13gwqzRoB7Bj1O-XMhxECvfz6F5fTd9zzpSWqfF7afVZUGM7nYRB84Wdarh3hpftcTmsuvpczTsGhjlzt5v2gUq_mMVHkFK_Xi10LLwhIEubgmsYASG5Ui9gtpusqL9fY3foaAsovvs8Ukx3Gs0IBV4MeUwzJ-_ern932h36DgdCoaqdg20E3HTbxz0GKKXRMMwT1JdJCHMewGukTcAiPgmCsIz8JQ"
_WINDOWS_D = "AqmBB1aAdw9-pbDz_RTjwmojYaTNqozVHGP-7k3D_q4GOyYXBiZagOUE805O_CUHe9u5dvAWAgHq9hDqPHam7c-XvGB9bcgrqiFMZfpIRHHj94VeXPBPVvvcJxGyFa9maucuvzwTJj7oAvCnnDrbbinWb9zgtI9oYSQXqsrRyWjpkOpXl24zar_Nb9lfSPpvBVDvIGOLusvN74EQuhtW8xP8XcwbwHNat_cRqAoo3xiNEIpDuQxJxxwXjj6lZ6kaTRFSzYkwU9aq6zTjI2-C6QR0-AylViqWEOd2o-FNojAwS7rTKeCjiil2bIv97nJOzZGjMIyt-AMoTGeje9We2Q"
_PRIVATE_KEYS = {
    "page_event_receiver": (_PAGE_N, _PAGE_D),
    "authenticated_observer": (TEST_RSA_N_B64, base64.urlsafe_b64encode(TEST_RSA_D.to_bytes(256, "big")).rstrip(b"=").decode()),
    "windows_runner": (_WINDOWS_N, _WINDOWS_D),
}


@pytest.fixture(autouse=True)
def _use_test_trust_manifest(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")


def test_embedded_test_trust_manifest_is_versioned_and_role_scoped():
    manifest, digest = load_trust_manifest(environment="test")

    assert manifest["schema_version"] == 1
    assert manifest["environment"] == "test"
    assert digest == "0eac4b3fc49f913f33762dbedbe41916c3ef50eb1128211d7d93281c78902fed"
    assert all("d" not in key and "private_key" not in key for key in manifest["keys"])
    assert {key["issuer"] for key in manifest["keys"]} == set(_PRIVATE_KEYS)
    assert {key["algorithm"] for key in manifest["keys"]} == {"RS256"}
    assert len({key["key_id"] for key in manifest["keys"]}) == 3
    assert {
        key["issuer"]: key["allowed_event_types"]
        for key in manifest["keys"]
    } == {
        "page_event_receiver": ["web_page_close"],
        "authenticated_observer": ["authenticated_observer"],
        "windows_runner": ["electron_exit"],
    }


def test_production_rejects_test_fixture_trust_manifest():
    from ops import r297_evidence_events

    source = r297_evidence_events._TEST_TRUST_MANIFEST
    relabelled = json.loads(source.read_text())
    relabelled["environment"] = "production"
    relabelled["manifest_id"] = "r297-evidence-trust-production-v1"
    for key in relabelled["keys"]:
        key["key_id"] = key["key_id"].removesuffix("-test") + "-production"
    with pytest.raises(ValueError, match="test evidence key forbidden in production"):
        r297_evidence_events._validate_trust_manifest(relabelled, environment="production")


def test_production_rejects_equivalent_test_key_encoding():
    from ops import r297_evidence_events

    relabelled = json.loads(r297_evidence_events._TEST_TRUST_MANIFEST.read_text())
    relabelled["environment"] = "production"
    relabelled["manifest_id"] = "r297-evidence-trust-production-v1"
    for key in relabelled["keys"]:
        key["key_id"] = key["key_id"].removesuffix("-test") + "-production"
        key["n"] = base64.urlsafe_b64encode(b"\0" + base64.urlsafe_b64decode(
            key["n"] + "=" * (-len(key["n"]) % 4)
        )).rstrip(b"=").decode()

    with pytest.raises(ValueError, match="test evidence key forbidden in production"):
        r297_evidence_events._validate_trust_manifest(relabelled, environment="production")


def test_manifest_rejects_equivalent_key_encodings_for_different_roles():
    from ops import r297_evidence_events

    manifest = json.loads(r297_evidence_events._TEST_TRUST_MANIFEST.read_text())
    page_key = manifest["keys"][0]
    observer_key = manifest["keys"][1]
    observer_key["n"] = base64.urlsafe_b64encode(b"\0" + base64.urlsafe_b64decode(
        page_key["n"] + "=" * (-len(page_key["n"]) % 4)
    )).rstrip(b"=").decode()
    observer_key["e"] = page_key["e"]

    with pytest.raises(ValueError, match="evidence issuer keys not isolated"):
        r297_evidence_events._validate_trust_manifest(manifest, environment="test")


def _scope() -> dict:
    return {
        "namespace": "r297-acceptance-9b466ac80122",
        "tenant_id": "tenant-1",
        "company_id": "company-1",
        "store_id": 7,
        "platform": "jd",
        "release_sha": "9b466ac80122e35893cbaa408735136acc88331a",
        "run_id": "r297-run-20260907-0001",
        "run_attempt": 1,
        "challenge": "challenge-value-00000001",
    }


def _nonce_ledger(tmp_path):
    root = tmp_path / "nonce-ledger"
    root.mkdir(mode=0o700)
    ledger = root / "seen-nonces.json"
    ledger.write_text("[]\n", encoding="utf-8")
    ledger.chmod(0o600)
    lock = root / "seen-nonces.json.lock"
    lock.write_text("", encoding="utf-8")
    lock.chmod(0o600)
    return ledger


def test_bound_file_publish_recovers_body_only_crash(tmp_path):
    output = tmp_path / "evidence" / "event.json"
    output.parent.mkdir(mode=0o700)
    content = b'{"event":"signed"}\n'
    output.write_bytes(content)
    output.chmod(0o600)

    digest = write_sha256_bound_file(output, content)

    assert output.read_bytes() == content
    assert Path(f"{output}.sha256").read_text(encoding="ascii") == f"{digest}  event.json\n"


def test_bound_file_publish_recovers_verified_hardlink_publish_crash(monkeypatch, tmp_path):
    output = tmp_path / "evidence" / "event.json"
    output.parent.mkdir(mode=0o700)
    content = b'{"event":"signed"}\n'
    temporary = output.with_name(f".{output.name}.0123456789abcdef")
    temporary.write_bytes(content)
    temporary.chmod(0o600)
    os.link(temporary, output)
    published_inode = output.stat().st_ino
    parent_inode = output.parent.stat().st_ino
    synced_directory_inodes = []
    original_fsync = os.fsync

    def record_fsync(descriptor):
        metadata = os.fstat(descriptor)
        if stat.S_ISDIR(metadata.st_mode):
            synced_directory_inodes.append(metadata.st_ino)
        return original_fsync(descriptor)

    monkeypatch.setattr("ops.r297_evidence_events.os.fsync", record_fsync)

    digest = write_sha256_bound_file(output, content)

    metadata = output.stat()
    sidecar = Path(f"{output}.sha256")
    sidecar_metadata = sidecar.stat()
    assert output.read_bytes() == content
    assert metadata.st_ino == published_inode
    assert output.stat().st_nlink == 1
    assert metadata.st_mode & 0o777 == 0o600
    assert sidecar_metadata.st_mode & 0o777 == 0o600
    assert output.parent.stat().st_mode & 0o777 == 0o700
    if os.name != "nt":
        assert metadata.st_uid == os.geteuid()
        assert sidecar_metadata.st_uid == os.geteuid()
        assert output.parent.stat().st_uid == os.geteuid()
    assert not temporary.exists()
    assert not list(output.parent.glob(f".{output.name}.*"))
    assert sidecar.read_text(encoding="ascii") == f"{digest}  event.json\n"
    if os.name != "nt":
        assert synced_directory_inodes.count(parent_inode) >= 2


def test_bound_file_publish_rejects_unknown_second_hardlink(tmp_path):
    output = tmp_path / "evidence" / "event.json"
    output.parent.mkdir(mode=0o700)
    content = b'{"event":"signed"}\n'
    output.write_bytes(content)
    output.chmod(0o600)
    unknown = output.parent / "unknown-link"
    os.link(output, unknown)

    with pytest.raises(FileExistsError):
        write_sha256_bound_file(output, content)

    assert unknown.exists()
    assert not Path(f"{output}.sha256").exists()


def test_bound_file_publish_rejects_mismatched_or_committed_output(tmp_path):
    output = tmp_path / "evidence" / "event.json"
    output.parent.mkdir(mode=0o700)
    output.write_bytes(b"wrong")
    output.chmod(0o600)
    with pytest.raises(FileExistsError):
        write_sha256_bound_file(output, b"right")
    output.unlink()
    write_sha256_bound_file(output, b"right")
    with pytest.raises(FileExistsError):
        write_sha256_bound_file(output, b"right")


def test_bound_file_publish_is_exclusive_under_concurrency(tmp_path):
    output = tmp_path / "evidence" / "event.json"
    output.parent.mkdir(mode=0o700)

    def publish(content):
        try:
            write_sha256_bound_file(output, content)
            return "published"
        except FileExistsError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, (b"first", b"second")))

    assert sorted(results) == ["published", "rejected"]
    content = output.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    assert Path(f"{output}.sha256").read_text(encoding="ascii") == f"{digest}  event.json\n"


def test_bound_file_publish_recovers_sidecar_write_crash(monkeypatch, tmp_path):
    from ops import r297_evidence_events

    output = tmp_path / "evidence" / "event.json"
    output.parent.mkdir(mode=0o700)
    content = b'{"event":"signed"}\n'
    original_replace = r297_evidence_events._replace_file
    original_fsync = r297_evidence_events.os.fsync
    parent_inode = output.parent.stat().st_ino
    synced_directory_inodes = []
    calls = 0

    def record_fsync(descriptor):
        metadata = os.fstat(descriptor)
        if stat.S_ISDIR(metadata.st_mode):
            synced_directory_inodes.append(metadata.st_ino)
        return original_fsync(descriptor)

    def crash_before_sidecar(path, value):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("sidecar crash injection")
        original_replace(path, value)

    monkeypatch.setattr(r297_evidence_events.os, "fsync", record_fsync)
    monkeypatch.setattr(r297_evidence_events, "_replace_file", crash_before_sidecar)
    with pytest.raises(OSError, match="sidecar crash injection"):
        write_sha256_bound_file(output, content)
    published_inode = output.stat().st_ino
    assert output.read_bytes() == content
    assert output.stat().st_ino == published_inode
    assert not Path(f"{output}.sha256").exists()

    monkeypatch.setattr(r297_evidence_events, "_replace_file", original_replace)
    digest = write_sha256_bound_file(output, content)
    sidecar = Path(f"{output}.sha256")
    assert output.read_bytes() == content
    assert output.stat().st_ino == published_inode
    assert output.stat().st_mode & 0o777 == 0o600
    assert sidecar.stat().st_mode & 0o777 == 0o600
    assert output.parent.stat().st_mode & 0o777 == 0o700
    if os.name != "nt":
        assert output.stat().st_uid == os.geteuid()
        assert sidecar.stat().st_uid == os.geteuid()
        assert output.parent.stat().st_uid == os.geteuid()
    assert not list(output.parent.glob(f".{output.name}.*"))
    assert sidecar.read_text(encoding="ascii") == f"{digest}  event.json\n"
    if os.name != "nt":
        assert synced_directory_inodes.count(parent_inode) >= 2


def test_bound_file_publish_rejects_hardlinked_body_and_orphan_sidecar(tmp_path):
    output = tmp_path / "evidence" / "event.json"
    output.parent.mkdir(mode=0o700)
    content = b'{"event":"signed"}\n'
    output.write_bytes(content)
    output.chmod(0o600)
    os.link(output, output.with_name("attacker-hardlink"))
    with pytest.raises(FileExistsError):
        write_sha256_bound_file(output, content)

    output.with_name("attacker-hardlink").unlink()
    output.unlink()
    Path(f"{output}.sha256").write_text(f"{'0' * 64}  {output.name}\n", encoding="ascii")
    with pytest.raises(FileExistsError):
        write_sha256_bound_file(output, content)

def _integer(value: str) -> int:
    return int.from_bytes(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)), "big")


def _sign(event: dict) -> dict:
    modulus_b64, private_b64 = _PRIVATE_KEYS[event["issuer"]]
    event = {**event, "key_id": f"r297-{event['issuer']}-test"}
    canonical = json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(canonical).digest()
    encoded = b"\x00\x01" + b"\xff" * (256 - len(digest_info) - 3) + b"\x00" + digest_info
    signature = pow(int.from_bytes(encoded, "big"), _integer(private_b64), _integer(modulus_b64)).to_bytes(256, "big")
    return {**event, "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode()}


def _bundle(now: datetime, nonce_suffix: str = "") -> dict:
    common = _scope()
    page = _sign({
        **common,
        "event_type": "web_page_close",
        "issuer": "page_event_receiver",
        "nonce": f"page-close-nonce-0001{nonce_suffix}",
        "observed_at": (now - timedelta(seconds=4)).isoformat(),
        "sequence": 1,
        "payload": {
            "closed": True, "source": "browser_pagehide",
            "artifact_evidence_sha256": "1" * 64,
            "artifact_archive_sha256": "2" * 64,
            "artifact_id": 9965082823,
            "artifact_name": "r297-native-pagehide-test",
            "workflow_run_id": 33949515935,
        },
    })
    page_observer = _sign({
        **common,
        "event_type": "authenticated_observer",
        "issuer": "authenticated_observer",
        "nonce": f"page-observer-nonce-01{nonce_suffix}",
        "observed_at": (now - timedelta(seconds=3)).isoformat(),
        "sequence": 2,
        "payload": {
            "subject_nonce": page["nonce"],
            "subject_event_sha256": signed_event_sha256(page),
            "scheduler_continues": True,
            "observation_source": "postgresql_scheduler_state",
            "database_read_only": True,
            "cloud_cycles_before": 2,
            "cloud_cycles_after": 3,
            "eligible_store_ids": [7],
            "collected_store_ids_after": [7],
        },
    })
    electron = _sign({
        **common,
        "event_type": "electron_exit",
        "issuer": "windows_runner",
        "nonce": f"electron-exit-nonce-01{nonce_suffix}",
        "observed_at": (now - timedelta(seconds=2)).isoformat(),
        "sequence": 3,
        "payload": {"exited": True, "process_id": 4201},
    })
    electron_observer = _sign({
        **common,
        "event_type": "authenticated_observer",
        "issuer": "authenticated_observer",
        "nonce": f"electron-observer-0001{nonce_suffix}",
        "observed_at": (now - timedelta(seconds=1)).isoformat(),
        "sequence": 4,
        "payload": {
            "subject_nonce": electron["nonce"],
            "subject_event_sha256": signed_event_sha256(electron),
            "scheduler_continues": True,
            "observation_source": "postgresql_scheduler_state",
            "database_read_only": True,
            "cloud_cycles_before": 3,
            "cloud_cycles_after": 4,
            "eligible_store_ids": [7],
            "collected_store_ids_after": [7],
        },
    })
    return {"events": [page, page_observer, electron, electron_observer]}


def test_signed_evidence_events_bind_release_store_time_order_and_observer(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    ledger_path = _nonce_ledger(tmp_path)

    result = verify_acceptance_event_bundle(
        _bundle(now),
        expected_scope=_scope(),
        now=now,
        nonce_ledger=ledger_path,
    )

    assert result["web_page_close"] == {
        "closed": True,
        "cloud_cycles_before": 2,
        "cloud_cycles_after": 3,
        "eligible_store_ids": [7],
        "collected_store_ids_after": [7],
        "observation_source": "postgresql_scheduler_state",
        "database_read_only": True,
    }
    assert result["electron_exit"]["exited"] is True
    assert result["electron_exit"]["process_id"] == 4201
    assert result["electron_exit"]["cloud_cycles_after"] == 4
    assert result["authenticated_observer"]["verified_subject_count"] == 2
    assert result["evidence_trust_manifest_id"] == "r297-evidence-trust-test-v1"
    assert result["evidence_trust_manifest_sha256"] == "0eac4b3fc49f913f33762dbedbe41916c3ef50eb1128211d7d93281c78902fed"
    ledger = json.loads(ledger_path.read_text())
    assert len(ledger) == 4
    assert all(set(entry) == {
        "namespace", "tenant_id", "company_id", "store_id", "platform",
        "release_sha", "event_type", "key_id", "nonce",
        "run_id", "run_attempt", "challenge",
        "event_sha256", "verification",
    } for entry in ledger)
    assert {entry["event_sha256"] for entry in ledger} == {
        signed_event_sha256(event) for event in _bundle(now)["events"]
    }
    assert all(entry["verification"]["result"] == result for entry in ledger)

    with pytest.raises(ValueError, match="replayed acceptance run"):
        verify_acceptance_event_bundle(
            _bundle(now, "-fresh"), expected_scope=_scope(), now=now,
            nonce_ledger=ledger_path,
        )


def test_bundle_builder_accepts_only_complete_same_scope_signed_chain(monkeypatch):
    from ops.r297_evidence_bundle import build_bundle

    monkeypatch.setenv("APP_ENV", "test")
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    source = _bundle(now)

    assert build_bundle(source["events"], expected_scope=_scope(), now=now) == source

    source["events"][2]["release_sha"] = "0" * 40
    with pytest.raises(ValueError, match="release_sha mismatch"):
        build_bundle(source["events"], expected_scope=_scope(), now=now)


def test_bundle_precheck_preserves_run_until_formal_verification(monkeypatch, tmp_path):
    """Exercise acceptance control flow with the test trust provider, not formal evidence."""
    from ops import r297_evidence_events
    from ops.r297_acceptance_run import issue_acceptance_run, validate_acceptance_run
    from ops.r297_evidence_bundle import build_bundle
    from tests.test_r297_acceptance_run import _ledger

    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    scope = _scope()
    run_ledger = _ledger(tmp_path)
    record = issue_acceptance_run(run_ledger,
        scope={field: value for field, value in scope.items() if field not in {"run_id", "run_attempt", "challenge"}},
        source_workflow_run_id=33949515935, run_attempt=1, now=now)
    scope.update({field: record[field] for field in ("run_id", "run_attempt", "challenge")})
    monkeypatch.setitem(globals(), "_scope", lambda: scope)
    trust = load_trust_manifest(environment="test")
    monkeypatch.setattr(r297_evidence_events, "load_trust_manifest", lambda **kwargs: trust)
    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.setenv("R297_ACCEPTANCE_RUN_LEDGER", str(run_ledger))

    bundle = build_bundle(_bundle(now)["events"], expected_scope=scope, now=now)
    validate_acceptance_run(run_ledger, expected_scope=scope, source_workflow_run_id=33949515935, now=now)
    ledger = _nonce_ledger(tmp_path)
    result = verify_acceptance_event_bundle(bundle, expected_scope=scope, now=now, nonce_ledger=ledger)
    assert result["authenticated_observer"]["verified_subject_count"] == 2
    assert json.loads(run_ledger.read_text())["runs"][0]["state"] == "consumed"
    with pytest.raises(ValueError, match="missing or consumed"):
        verify_acceptance_event_bundle(bundle, expected_scope=scope, now=now, nonce_ledger=ledger)


@pytest.mark.parametrize("crash_after_nonce_write", [False, True])
@pytest.mark.parametrize("outage_minutes", [0, 6])
def test_bundle_verification_recovers_cross_ledger_crash(monkeypatch, tmp_path, crash_after_nonce_write, outage_minutes):
    from ops import r297_evidence_events
    from ops.r297_acceptance_run import issue_acceptance_run
    from ops.r297_evidence_bundle import build_bundle
    from tests.test_r297_acceptance_run import _ledger

    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    scope = _scope()
    run_ledger = _ledger(tmp_path)
    record = issue_acceptance_run(
        run_ledger,
        scope={field: value for field, value in scope.items() if field not in {"run_id", "run_attempt", "challenge"}},
        source_workflow_run_id=33949515935,
        run_attempt=1,
        now=now,
    )
    scope.update({field: record[field] for field in ("run_id", "run_attempt", "challenge")})
    monkeypatch.setitem(globals(), "_scope", lambda: scope)
    trust = load_trust_manifest(environment="test")
    monkeypatch.setattr(r297_evidence_events, "load_trust_manifest", lambda **_kwargs: trust)
    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.setenv("R297_ACCEPTANCE_RUN_LEDGER", str(run_ledger))
    bundle = build_bundle(_bundle(now)["events"], expected_scope=scope, now=now)
    nonce_ledger = _nonce_ledger(tmp_path)
    original_record_nonces = r297_evidence_events._record_nonces

    def crash_record_nonces(*args, **kwargs):
        if crash_after_nonce_write:
            original_record_nonces(*args, **kwargs)
        raise OSError("nonce ledger crash injection")

    monkeypatch.setattr(
        r297_evidence_events,
        "_record_nonces",
        crash_record_nonces,
    )

    with pytest.raises(OSError, match="nonce ledger crash injection"):
        verify_acceptance_event_bundle(bundle, expected_scope=scope, now=now, nonce_ledger=nonce_ledger)

    monkeypatch.setattr(r297_evidence_events, "_record_nonces", original_record_nonces)
    with pytest.raises(ValueError, match="reserved by different transaction"):
        verify_acceptance_event_bundle(
            {**bundle, "different_transaction": True}, expected_scope=scope,
            now=now, nonce_ledger=nonce_ledger,
        )

    def retry():
        try:
            return verify_acceptance_event_bundle(
                bundle, expected_scope=scope, now=now + timedelta(minutes=outage_minutes), nonce_ledger=nonce_ledger,
            )
        except ValueError as exc:
            assert "missing or consumed" in str(exc)
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: retry(), range(2)))
    assert sum(value is not None for value in results) == 1
    result = next(value for value in results if value is not None)
    assert result["authenticated_observer"]["verified_subject_count"] == 2
    assert json.loads(run_ledger.read_text())["runs"][0]["state"] == "consumed"
    assert len(json.loads(nonce_ledger.read_text())) == 4
    with pytest.raises(ValueError, match="missing or consumed"):
        verify_acceptance_event_bundle(bundle, expected_scope=scope, now=now, nonce_ledger=nonce_ledger)


def _resign_bundle_after(bundle: dict, elapsed: timedelta) -> dict:
    resigned = []
    for event in bundle["events"]:
        unsigned = {key: deepcopy(value) for key, value in event.items() if key not in {"key_id", "signature"}}
        unsigned["observed_at"] = (
            datetime.fromisoformat(unsigned["observed_at"]) + elapsed
        ).isoformat()
        if unsigned["event_type"] == "authenticated_observer":
            subject = next(item for item in resigned if item["nonce"] == unsigned["payload"]["subject_nonce"])
            unsigned["payload"]["subject_event_sha256"] = signed_event_sha256(subject)
        resigned.append(_sign(unsigned))
    return {"events": resigned}


def test_exact_preverified_bundle_recovers_after_five_minute_outage(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    bundle = _bundle(now)
    ledger = _nonce_ledger(tmp_path)
    initial = verify_acceptance_event_bundle(
        bundle, expected_scope=_scope(), now=now, nonce_ledger=ledger,
    )

    recovered = verify_acceptance_event_bundle(
        bundle, expected_scope=_scope(), now=now + timedelta(minutes=6),
        nonce_ledger=ledger, allow_nonce_recovery=True,
    )

    assert recovered == initial
    records = json.loads(ledger.read_text())
    assert len(records) == 4
    assert {
        record["event_sha256"] for record in records if record["event_type"] != "acceptance_run"
    } == {signed_event_sha256(event) for event in bundle["events"]}


def test_expired_never_verified_bundle_cannot_enter_recovery_path(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="expired evidence event"):
        verify_acceptance_event_bundle(
            _bundle(now), expected_scope=_scope(), now=now + timedelta(minutes=6),
            nonce_ledger=_nonce_ledger(tmp_path), allow_nonce_recovery=True,
        )


def test_preverified_bundle_rejects_resigned_timestamp_rewrite(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    bundle = _bundle(now)
    ledger = _nonce_ledger(tmp_path)
    verify_acceptance_event_bundle(
        bundle, expected_scope=_scope(), now=now, nonce_ledger=ledger,
    )

    with pytest.raises(ValueError, match="replayed evidence nonce|receipt binding mismatch"):
        verify_acceptance_event_bundle(
            _resign_bundle_after(bundle, timedelta(minutes=6)),
            expected_scope=_scope(), now=now + timedelta(minutes=6),
            nonce_ledger=ledger, allow_nonce_recovery=True,
        )


def test_candidate_bundle_builder_cannot_receive_any_signer_private_key(monkeypatch):
    from ops.r297_evidence_bundle import build_bundle

    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    variables = (
        "R297_PAGE_EVENT_RECEIVER_PRIVATE_KEY_PATH",
        "R297_OBSERVER_PRIVATE_KEY_PATH",
        "R297_WINDOWS_RUNNER_PRIVATE_KEY_PATH",
    )
    for variable in variables:
        with monkeypatch.context() as isolated:
            for candidate in variables:
                isolated.delenv(candidate, raising=False)
            isolated.setenv(variable, "/must-not-be-readable-by-candidate")
            with pytest.raises(RuntimeError, match="verifier must not receive signer private keys"):
                build_bundle(_bundle(now)["events"], expected_scope=_scope(), now=now)


def _attempt_events(now, expected_scope, *, splice=False):
    events = []
    for index, event in enumerate(_bundle(now)["events"]):
        unsigned = {key: value for key, value in event.items() if key not in {"key_id", "signature"}}
        payload = deepcopy(unsigned["payload"])
        if unsigned["event_type"] == "authenticated_observer":
            subject = next(item for item in events if item["nonce"] == payload["subject_nonce"])
            payload["subject_event_sha256"] = signed_event_sha256(subject)
        events.append(_sign({
            **unsigned,
            "payload": payload,
            "run_attempt": 1 if splice and index == 2 else expected_scope["run_attempt"],
            "challenge": "challenge-from-another-run-0001" if splice and index == 2 else expected_scope["challenge"],
        }))
    return events


def test_signed_chain_binds_run_attempt_and_random_challenge(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    expected_scope = {**_scope(), "run_attempt": 2, "challenge": "challenge-6ea4d915d7f8435880868439"}

    result = verify_acceptance_event_bundle(
        {"events": _attempt_events(now, expected_scope)},
        expected_scope=expected_scope, now=now, nonce_ledger=_nonce_ledger(tmp_path),
    )

    assert result["authenticated_observer"]["run_attempt"] == 2
    assert result["authenticated_observer"]["challenge"] == expected_scope["challenge"]


def test_signed_chain_rejects_cross_attempt_splice(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    expected_scope = {**_scope(), "run_attempt": 2, "challenge": "challenge-6ea4d915d7f8435880868439"}
    with pytest.raises(ValueError, match="run_attempt mismatch|challenge mismatch"):
        verify_acceptance_event_bundle(
            {"events": _attempt_events(now, expected_scope, splice=True)}, expected_scope=expected_scope, now=now,
            nonce_ledger=_nonce_ledger(tmp_path),
        )


def test_signed_evidence_events_reject_concurrent_replay(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    ledger = _nonce_ledger(tmp_path)

    def verify():
        try:
            verify_acceptance_event_bundle(
                _bundle(now), expected_scope=_scope(), now=now, nonce_ledger=ledger,
            )
            return "accepted"
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: verify(), range(2)))

    assert sorted(results) == ["accepted", "replayed acceptance run"]


def test_nonce_commit_exact_recovery_is_bounded_to_explicit_transaction_retry(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    ledger = _nonce_ledger(tmp_path)
    bundle = _bundle(now)

    verify_acceptance_event_bundle(
        bundle, expected_scope=_scope(), now=now, nonce_ledger=ledger,
        consume_run=False,
    )
    recovered = verify_acceptance_event_bundle(
        bundle, expected_scope=_scope(), now=now, nonce_ledger=ledger,
        consume_run=False, allow_nonce_recovery=True,
    )
    assert recovered["authenticated_observer"]["verified_subject_count"] == 2
    with pytest.raises(ValueError, match="replayed acceptance run"):
        verify_acceptance_event_bundle(
            bundle, expected_scope=_scope(), now=now, nonce_ledger=ledger,
            consume_run=False,
        )


def test_acceptance_source_run_is_consumed_once_across_scopes(tmp_path):
    from ops.r297_evidence_events import _record_nonces

    ledger = _nonce_ledger(tmp_path)
    first = {
        **_scope(), "event_type": "acceptance_run",
        "key_id": "source_pagehide_workflow", "nonce": _scope()["run_id"],
    }
    _record_nonces(ledger, [first])

    with pytest.raises(ValueError, match="replayed acceptance run"):
        _record_nonces(ledger, [{**first, "tenant_id": 999, "store_id": 999}])
    with pytest.raises(ValueError, match="replayed acceptance run"):
        _record_nonces(ledger, [first], allow_exact_recovery=True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("namespace", ""),
        ("tenant_id", True),
        ("company_id", "company with spaces"),
        ("store_id", True),
        ("platform", "JD"),
    ],
)
def test_signed_evidence_events_reject_invalid_expected_scope(field, value, tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    scope = _scope()
    scope[field] = value

    with pytest.raises(ValueError, match="invalid expected evidence binding"):
        verify_acceptance_event_bundle(
            _bundle(now), expected_scope=scope, now=now,
            nonce_ledger=tmp_path / "seen-nonces.json",
        )


def test_signed_evidence_events_reject_boolean_scope_alias(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    scope = _scope()
    scope["tenant_id"] = 1
    bundle = _bundle(now)
    for event in bundle["events"]:
        event["tenant_id"] = True

    with pytest.raises(ValueError, match="tenant_id mismatch"):
        verify_acceptance_event_bundle(
            bundle, expected_scope=scope, now=now,
            nonce_ledger=tmp_path / "seen-nonces.json",
        )


def test_process_evidence_rejects_caller_supplied_trust_anchor(monkeypatch, tmp_path):
    from ops import r297_process_acceptance

    output = tmp_path / "must-not-exist"
    bundle = tmp_path / "events.json"
    keys = tmp_path / "attacker-keys.json"
    bundle.write_text("{}")
    keys.write_text("{}")
    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.setattr(sys, "argv", [
        "r297_process_acceptance.py", str(output), "--runtime-image", "unused",
        "--signed-event-bundle", str(bundle), "--event-public-keys", str(keys),
    ])

    with pytest.raises(SystemExit):
        r297_process_acceptance.main()
    assert not output.exists()


def test_process_evidence_requires_real_signed_event_inputs(monkeypatch, tmp_path):
    from ops import r297_process_acceptance

    output = tmp_path / "must-not-exist"
    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.setattr(
        sys,
        "argv",
        ["r297_process_acceptance.py", str(output), "--runtime-image", "unused"],
    )

    with pytest.raises(SystemExit):
        r297_process_acceptance.main()
    assert not output.exists()


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda bundle, now: bundle["events"][0].update(release_sha="0" * 40), "release_sha mismatch"),
        (lambda bundle, now: bundle["events"][0].update(namespace="other"), "namespace mismatch"),
        (lambda bundle, now: bundle["events"][0].update(tenant_id="other"), "tenant_id mismatch"),
        (lambda bundle, now: bundle["events"][0].update(company_id="other"), "company_id mismatch"),
        (lambda bundle, now: bundle["events"][0].update(store_id=8), "store_id mismatch"),
        (lambda bundle, now: bundle["events"][0].update(platform="other"), "platform mismatch"),
        (lambda bundle, now: bundle["events"][0].update(run_id="other-run-000000"), "run_id mismatch"),
        (lambda bundle, now: bundle["events"][0].update(sequence=True), "event sequence mismatch"),
        (lambda bundle, now: bundle["events"][0].update(observed_at=(now - timedelta(minutes=6)).isoformat()), "expired evidence event"),
        (lambda bundle, now: bundle["events"][0].update(observed_at=(now + timedelta(minutes=1)).isoformat()), "future evidence event"),
        (lambda bundle, now: bundle["events"][1].update(sequence=1), "event sequence mismatch"),
        (lambda bundle, now: bundle["events"][0]["payload"].update(scheduler_continues=True), "client scheduler claim forbidden"),
        (lambda bundle, now: bundle["events"][1].update(signature=bundle["events"][0]["signature"]), "invalid evidence signature"),
    ],
)
def test_signed_evidence_events_fail_closed(mutation, error, tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    bundle = deepcopy(_bundle(now))
    mutation(bundle, now)

    with pytest.raises(ValueError, match=error):
        verify_acceptance_event_bundle(
            bundle, expected_scope=_scope(), now=now,
            nonce_ledger=_nonce_ledger(tmp_path),
        )


def test_nonce_ledger_missing_fails_closed(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError, match="nonce ledger missing"):
        verify_acceptance_event_bundle(
            _bundle(now), expected_scope=_scope(), now=now,
            nonce_ledger=tmp_path / "missing.json",
        )


@pytest.mark.parametrize("target", ["ledger", "lock", "directory"])
def test_nonce_ledger_permission_errors_fail_closed(tmp_path, target):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    ledger = _nonce_ledger(tmp_path)
    paths = {
        "ledger": ledger,
        "lock": ledger.with_suffix(ledger.suffix + ".lock"),
        "directory": ledger.parent,
    }
    paths[target].chmod(0o666 if target != "directory" else 0o777)

    with pytest.raises(RuntimeError, match="nonce ledger permissions invalid"):
        verify_acceptance_event_bundle(
            _bundle(now), expected_scope=_scope(), now=now, nonce_ledger=ledger,
        )


def test_nonce_ledger_corruption_fails_closed_without_replacement(tmp_path):
    now = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    ledger = _nonce_ledger(tmp_path)
    ledger.write_text("not-json\n", encoding="utf-8")
    original_inode = os.stat(ledger).st_ino

    with pytest.raises(ValueError, match="evidence nonce ledger invalid"):
        verify_acceptance_event_bundle(
            _bundle(now), expected_scope=_scope(), now=now, nonce_ledger=ledger,
        )

    assert ledger.read_text(encoding="utf-8") == "not-json\n"
    assert os.stat(ledger).st_ino == original_inode


def _receipted_bundle(fact_time: datetime, *, receipt_delay_seconds: int = 1) -> dict:
    signed = []
    for event in _bundle(fact_time)["events"]:
        unsigned = {key: value for key, value in event.items() if key not in {"key_id", "signature"}}
        observed = datetime.fromisoformat(unsigned["observed_at"])
        unsigned["payload"] = {
            **unsigned["payload"],
            "freshness_receipt": {
                "received_at": (observed + timedelta(seconds=receipt_delay_seconds)).isoformat(),
                "freshness_verified": True,
                "maximum_age_seconds": 300,
            },
        }
        if unsigned["event_type"] == "authenticated_observer":
            subject = signed[-1]
            unsigned["payload"]["subject_event_sha256"] = signed_event_sha256(subject)
        signed.append(_sign(unsigned))
    return {"events": signed}


def test_long_cycle_bundle_preserves_fact_time_with_signed_freshness_receipts(tmp_path):
    now = datetime(2026, 9, 5, 4, 0, tzinfo=timezone.utc)
    bundle = _receipted_bundle(now - timedelta(minutes=20))
    ledger = _nonce_ledger(tmp_path)
    original = verify_acceptance_event_bundle(
        bundle, expected_scope=_scope(), now=now - timedelta(minutes=20), nonce_ledger=ledger,
    )
    result = verify_acceptance_event_bundle(
        bundle, expected_scope=_scope(), now=now, nonce_ledger=ledger, allow_nonce_recovery=True,
    )
    assert result["authenticated_observer"]["verified_subject_count"] == 2
    assert result == original


def test_producer_freshness_claim_cannot_replace_durable_verification(tmp_path):
    now = datetime(2026, 9, 5, 4, 0, tzinfo=timezone.utc)
    ledger = _nonce_ledger(tmp_path)
    with pytest.raises(ValueError, match="expired evidence event"):
        verify_acceptance_event_bundle(
            _receipted_bundle(now - timedelta(minutes=20)),
            expected_scope=_scope(), now=now, nonce_ledger=ledger, allow_nonce_recovery=True,
        )
    assert json.loads(ledger.read_text()) == []


def test_exact_verification_recovery_expires_without_refreshing_proof(tmp_path):
    now = datetime(2026, 9, 5, 4, 0, tzinfo=timezone.utc)
    ledger = _nonce_ledger(tmp_path)
    bundle = _bundle(now)
    verify_acceptance_event_bundle(bundle, expected_scope=_scope(), now=now, nonce_ledger=ledger)
    original = ledger.read_bytes()
    with pytest.raises(ValueError, match="recovery period expired"):
        verify_acceptance_event_bundle(
            bundle, expected_scope=_scope(), now=now + timedelta(hours=12, seconds=1),
            nonce_ledger=ledger, allow_nonce_recovery=True,
        )
    assert ledger.read_bytes() == original


def test_long_cycle_bundle_rejects_receipt_outside_five_minutes(tmp_path):
    now = datetime(2026, 9, 5, 4, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="freshness receipt"):
        verify_acceptance_event_bundle(
            _receipted_bundle(now - timedelta(minutes=20), receipt_delay_seconds=301),
            expected_scope=_scope(), now=now, nonce_ledger=_nonce_ledger(tmp_path),
        )


def test_verified_event_receipt_entry_records_signed_arrival(monkeypatch, tmp_path):
    from ops.r297_acceptance_run import issue_acceptance_run
    from ops.r297_event_receipt import record_event
    from tests.test_r297_acceptance_run import _ledger

    now = datetime(2026, 9, 5, 4, 0, tzinfo=timezone.utc)
    event = _receipted_bundle(now)["events"][0]
    ledger = _ledger(tmp_path)
    issue_acceptance_run(
        ledger,
        scope={field: event[field] for field in {
            "namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha",
        }},
        source_workflow_run_id=event["payload"]["workflow_run_id"],
        run_attempt=event["run_attempt"], now=now - timedelta(seconds=5),
    )
    stored = json.loads(ledger.read_text())
    stored["runs"][0].update({
        field: event[field] for field in {"run_id", "run_attempt", "challenge"}
    })
    ledger.write_text(json.dumps(stored, sort_keys=True) + "\n")
    root = tmp_path / "event"
    root.mkdir(mode=0o700)
    event_path = root / "page.json"
    write_sha256_bound_file(
        event_path, (json.dumps(event, sort_keys=True) + "\n").encode(),
    )

    assert record_event(
        ledger, event_path,
        source_workflow_run_id=event["payload"]["workflow_run_id"], now=now,
    ) == "recorded"

    late = root / "late.json"
    write_sha256_bound_file(
        late, (json.dumps(event, sort_keys=True) + "\n").encode(),
    )
    original = ledger.read_bytes()
    for delay in (timedelta(seconds=1), timedelta(minutes=6)):
        assert record_event(
            ledger, late, source_workflow_run_id=event["payload"]["workflow_run_id"], now=now + delay,
        ) == "recovered"
        assert ledger.read_bytes() == original
    with pytest.raises(ValueError, match="expired"):
        record_event(
            ledger, late, source_workflow_run_id=event["payload"]["workflow_run_id"], now=now + timedelta(hours=13),
        )
    changed = root / "changed.json"
    rewritten = _resign_bundle_after(_receipted_bundle(now), timedelta(seconds=1))["events"][0]
    write_sha256_bound_file(changed, (json.dumps(rewritten, sort_keys=True) + "\n").encode())
    with pytest.raises(ValueError, match="receipt binding mismatch"):
        record_event(
            ledger, changed, source_workflow_run_id=event["payload"]["workflow_run_id"], now=now + timedelta(seconds=1),
        )
    second = root / "second.json"
    write_sha256_bound_file(second, (json.dumps(_receipted_bundle(now)["events"][1], sort_keys=True) + "\n").encode())
    with pytest.raises(ValueError, match="expired evidence event"):
        record_event(
            ledger, second, source_workflow_run_id=event["payload"]["workflow_run_id"], now=now + timedelta(minutes=6),
        )
    assert ledger.read_bytes() == original
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda delay: record_event(
            ledger, second, source_workflow_run_id=event["payload"]["workflow_run_id"], now=now + timedelta(seconds=delay),
        ), (1, 2)))
    assert sorted(results) == ["recorded", "recovered"]
    assert len(json.loads(ledger.read_text())["runs"][0]["event_receipts"]) == 2


def test_long_cycle_consumes_only_the_persisted_signed_receipt_chain(monkeypatch, tmp_path):
    from ops import r297_evidence_events
    from ops.r297_acceptance_run import issue_acceptance_run, record_acceptance_event_receipt
    from tests.test_r297_acceptance_run import _ledger

    fact_time = datetime(2026, 9, 5, 2, 0, tzinfo=timezone.utc)
    scope = _scope()
    run_ledger = _ledger(tmp_path)
    record = issue_acceptance_run(
        run_ledger,
        scope={field: value for field, value in scope.items() if field not in {"run_id", "run_attempt", "challenge"}},
        source_workflow_run_id=33949515935, run_attempt=1,
        now=fact_time - timedelta(seconds=5),
    )
    scope.update({field: record[field] for field in ("run_id", "run_attempt", "challenge")})
    monkeypatch.setitem(globals(), "_scope", lambda: scope)
    trust = load_trust_manifest(environment="test")
    monkeypatch.setattr(r297_evidence_events, "load_trust_manifest", lambda **_kwargs: trust)
    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.setenv("R297_ACCEPTANCE_RUN_LEDGER", str(run_ledger))
    bundle = _receipted_bundle(fact_time)
    for event in bundle["events"]:
        received_at = datetime.fromisoformat(event["payload"]["freshness_receipt"]["received_at"])
        record_acceptance_event_receipt(
            run_ledger, expected_scope=scope, source_workflow_run_id=33949515935,
            event_type=event["event_type"], sequence=event["sequence"],
            event_sha256=signed_event_sha256(event),
            observed_at=datetime.fromisoformat(event["observed_at"]), received_at=received_at,
        )

    result = verify_acceptance_event_bundle(
        bundle, expected_scope=scope, now=fact_time + timedelta(minutes=20),
        nonce_ledger=_nonce_ledger(tmp_path),
    )
    assert result["authenticated_observer"]["verified_subject_count"] == 2
    assert json.loads(run_ledger.read_text())["runs"][0]["state"] == "consumed"
