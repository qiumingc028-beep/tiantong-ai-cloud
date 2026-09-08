import json
from pathlib import Path

import pytest

from ops.r297_evidence_broker import EvidenceBroker


def _scope():
    return {
        "namespace": "r297-controlled-canary",
        "tenant_id": 1,
        "company_id": 1,
        "store_id": 3,
        "platform": "jd",
        "release_sha": "a" * 40,
    }


def test_broker_is_the_only_ledger_writer_and_publishes_read_only_snapshot(tmp_path):
    run_ledger = tmp_path / "broker" / "runs.json"
    nonce_ledger = tmp_path / "broker" / "nonces.json"
    snapshot_root = tmp_path / "snapshots"
    calls = []

    def issue(_ledger, *, scope, source_workflow_run_id, run_attempt):
        calls.append((_ledger, scope, source_workflow_run_id, run_attempt))
        return {
            **scope,
            "source_workflow_run_id": source_workflow_run_id,
            "run_id": "r297-run-000000000001",
            "run_attempt": run_attempt,
            "challenge": "challenge-value-00000001",
            "issued_at": "2026-09-08T00:00:00+00:00",
            "consumed_at": None,
            "state": "issued",
            "event_receipts": [],
        }

    broker = EvidenceBroker(
        run_ledger=run_ledger,
        nonce_ledger=nonce_ledger,
        snapshot_root=snapshot_root,
        role_uids={"verifier": 100, "page_event_receiver": 101, "authenticated_observer": 102,
                   "windows_relay": 103},
        issue_run=issue,
    )
    result = broker.dispatch({
        "action": "issue",
        "scope": _scope(),
        "source_workflow_run_id": 34123456789,
        "run_attempt": 1,
    }, peer_uid=100)

    snapshot = Path(result["snapshot"])
    assert calls == [(run_ledger, _scope(), 34123456789, 1)]
    assert snapshot.parent.parent == snapshot_root
    assert snapshot.stat().st_mode & 0o777 == 0o444
    assert Path(f"{snapshot}.sha256").stat().st_mode & 0o777 == 0o444
    assert json.loads(snapshot.read_text())["challenge"] == "challenge-value-00000001"
    recovered = broker.dispatch({
        "action": "issue", "scope": _scope(),
        "source_workflow_run_id": 34123456789, "run_attempt": 1,
    }, peer_uid=100)
    assert recovered["snapshot"] == str(snapshot)
    assert calls == [(run_ledger, _scope(), 34123456789, 1)] * 2
    with pytest.raises(PermissionError, match="broker action denied"):
        broker.dispatch({
            "action": "issue", "scope": _scope(),
            "source_workflow_run_id": 34123456789, "run_attempt": 1,
        }, peer_uid=101)


def test_broker_fences_receipts_by_real_peer_role(tmp_path):
    received = []
    broker = EvidenceBroker(
        run_ledger=tmp_path / "runs.json",
        nonce_ledger=tmp_path / "nonces.json",
        snapshot_root=tmp_path / "snapshots",
        role_uids={"verifier": 100, "page_event_receiver": 101, "authenticated_observer": 102,
                   "windows_relay": 103},
        record_event=lambda ledger, event, source, now=None: received.append(
            (ledger, event["sequence"], source)
        ) or "recorded",
    )
    event = {"sequence": 1, "event_type": "web_page_close"}
    assert broker.dispatch({
        "action": "receipt", "event": event, "source_workflow_run_id": 7,
    }, peer_uid=101) == {"result": "recorded"}
    assert received == [(tmp_path / "runs.json", 1, 7)]

    with pytest.raises(PermissionError, match="receipt role denied"):
        broker.dispatch({
            "action": "receipt", "event": {"sequence": 3, "event_type": "electron_exit"},
            "source_workflow_run_id": 7,
        }, peer_uid=101)


def test_broker_health_discloses_no_paths_or_material(tmp_path):
    broker = EvidenceBroker(
        run_ledger=tmp_path / "runs.json", nonce_ledger=tmp_path / "nonces.json",
        snapshot_root=tmp_path / "snapshots",
        role_uids={"verifier": 100, "page_event_receiver": 101, "authenticated_observer": 102,
                   "windows_relay": 103},
    )
    assert broker.dispatch({"action": "health"}, peer_uid=999) == {
        "result": "ready", "private_key_count": 0,
    }


def test_issue_recovers_directory_only_crash(tmp_path):
    snapshot_root = tmp_path / "snapshots"
    run_root = snapshot_root / "r297-run-000000000001"
    run_root.mkdir(parents=True, mode=0o700)
    record = {
        **_scope(), "source_workflow_run_id": 8, "run_id": run_root.name,
        "run_attempt": 1, "challenge": "challenge-value-00000001",
        "issued_at": "2026-09-08T00:00:00+00:00", "consumed_at": None,
        "state": "issued", "event_receipts": [],
    }
    broker = EvidenceBroker(
        run_ledger=tmp_path / "runs.json", nonce_ledger=tmp_path / "nonces.json",
        snapshot_root=snapshot_root,
        role_uids={"verifier": 100, "page_event_receiver": 101, "authenticated_observer": 102,
                   "windows_relay": 103},
        issue_run=lambda *_args, **_kwargs: record,
    )
    result = broker.dispatch({
        "action": "issue", "scope": _scope(), "source_workflow_run_id": 8, "run_attempt": 1,
    }, peer_uid=100)
    assert Path(result["snapshot"]).stat().st_mode & 0o777 == 0o444
    assert run_root.stat().st_mode & 0o777 == 0o755


@pytest.mark.parametrize("hardlink_crash", [False, True])
def test_issue_recovers_snapshot_body_only_crash(tmp_path, hardlink_crash):
    snapshot_root = tmp_path / "snapshots"
    run_root = snapshot_root / "r297-run-000000000001"
    run_root.mkdir(parents=True, mode=0o700)
    record = {
        **_scope(), "source_workflow_run_id": 8, "run_id": run_root.name,
        "run_attempt": 1, "challenge": "challenge-value-00000001",
        "issued_at": "2026-09-08T00:00:00+00:00", "consumed_at": None,
        "state": "issued", "event_receipts": [],
    }
    content = (json.dumps(record, sort_keys=True) + "\n").encode()
    snapshot = run_root / "acceptance-run-binding.json"
    snapshot.write_bytes(content)
    snapshot.chmod(0o600)
    temporary = run_root / ".acceptance-run-binding.json.0123456789abcdef"
    if hardlink_crash:
        temporary.hardlink_to(snapshot)
    broker = EvidenceBroker(
        run_ledger=tmp_path / "runs.json", nonce_ledger=tmp_path / "nonces.json",
        snapshot_root=snapshot_root,
        role_uids={"verifier": 100, "page_event_receiver": 101, "authenticated_observer": 102,
                   "windows_relay": 103},
        issue_run=lambda *_args, **_kwargs: record,
    )
    result = broker.dispatch({
        "action": "issue", "scope": _scope(), "source_workflow_run_id": 8, "run_attempt": 1,
    }, peer_uid=100)
    assert Path(result["snapshot"]).stat().st_mode & 0o777 == 0o444
    assert Path(f'{result["snapshot"]}.sha256').is_file()
    assert not temporary.exists()
