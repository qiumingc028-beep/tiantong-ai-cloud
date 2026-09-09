import json
from pathlib import Path

import pytest

from ops.r297_evidence_broker import EvidenceBroker


@pytest.fixture
def transaction_broker(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from ops.r297_evidence_storage import provision_acceptance_storage
    from tests import test_r297_evidence_event_protocol as protocol
    monkeypatch.setenv("APP_ENV", "test")
    now = datetime.now(timezone.utc)
    run, nonce = tmp_path / "ledger/runs.json", tmp_path / "ledger/nonces.json"
    provision_acceptance_storage(run, nonce)
    broker = EvidenceBroker(run_ledger=run, nonce_ledger=nonce, snapshot_root=tmp_path / "snapshots",
        role_uids={"verifier": 100, "page_event_receiver": 101, "authenticated_observer": 102, "windows_relay": 103})
    issued = broker.dispatch({"action": "issue", "scope": {**_scope(), "store_id": 7}, "source_workflow_run_id": 33949515935, "run_attempt": 1}, peer_uid=100)
    scope = {key: value for key, value in issued["record"].items() if key in protocol._scope()}
    monkeypatch.setattr(protocol, "_scope", lambda: scope)
    bundle = protocol._bundle(now)
    return broker, bundle, scope


@pytest.mark.parametrize("index,uid", [(1, 102), (2, 103)])
def test_producer_recovers_only_own_preverified_fact_after_five_minutes(transaction_broker, monkeypatch, index, uid):
    from datetime import datetime, timedelta, timezone
    from ops import r297_event_receipt
    from ops.r297_evidence_events import signed_event_sha256
    broker, bundle, scope = transaction_broker
    for event, role_uid in zip(bundle["events"][:index + 1], (101, 102, 103)):
        assert broker.dispatch({"action": "receipt", "event": event, "source_workflow_run_id": 33949515935}, peer_uid=role_uid)["result"] == "recorded"
    original_ledger = broker.run_ledger.read_bytes()
    original_nonce = broker.nonce_ledger.read_bytes()
    later = datetime.now(timezone.utc) + timedelta(minutes=6)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return later
    monkeypatch.setattr(r297_event_receipt, "datetime", Clock)
    request = {"action": "recover_receipt", "event": bundle["events"][index], "source_workflow_run_id": 33949515935}
    result = broker.dispatch(request, peer_uid=uid)
    assert result == {"result": "recovered", "event_sha256": signed_event_sha256(request["event"])}
    assert broker.dispatch(request, peer_uid=uid) == result
    for other_uid in (100, 101, 102, 103, 999):
        if other_uid != uid:
            with pytest.raises(PermissionError):
                broker.dispatch(request, peer_uid=other_uid)
    for field, changed in (("run_id", "another-run-00000001"), ("run_attempt", 2), ("challenge", "another-challenge-00000001"), ("store_id", 99)):
        with pytest.raises(ValueError):
            broker.dispatch({**request, "event": {**request["event"], field: changed}}, peer_uid=uid)
    from tests.test_r297_evidence_event_protocol import _sign
    rewritten = _sign({**request["event"], "observed_at": later.isoformat()})
    with pytest.raises(ValueError):
        broker.dispatch({**request, "event": rewritten}, peer_uid=uid)
    with pytest.raises(ValueError):
        broker.dispatch({**request, "now": later.isoformat()}, peer_uid=uid)
    later += timedelta(hours=12)
    with pytest.raises(ValueError, match="expired"):
        broker.dispatch(request, peer_uid=uid)
    assert broker.run_ledger.read_bytes() == original_ledger
    assert broker.nonce_ledger.read_bytes() == original_nonce


@pytest.mark.parametrize("index,uid", [(1, 102), (2, 103)])
def test_expired_unverified_producer_fact_cannot_create_recovery_receipt(transaction_broker, monkeypatch, index, uid):
    from datetime import datetime, timedelta, timezone
    from ops import r297_event_receipt
    broker, bundle, _ = transaction_broker
    for event, role_uid in zip(bundle["events"][:index], (101, 102)):
        broker.dispatch({"action": "receipt", "event": event, "source_workflow_run_id": 33949515935}, peer_uid=role_uid)
    original = broker.run_ledger.read_bytes()
    later = datetime.now(timezone.utc) + timedelta(minutes=6)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return later
    monkeypatch.setattr(r297_event_receipt, "datetime", Clock)
    request = {"action": "recover_receipt", "event": bundle["events"][index], "source_workflow_run_id": 33949515935}
    with pytest.raises(ValueError, match="RECEIPT_NOT_VERIFIED"):
        broker.dispatch(request, peer_uid=uid)
    with pytest.raises(ValueError):
        broker.dispatch({**request, "action": "receipt"}, peer_uid=uid)
    assert broker.run_ledger.read_bytes() == original


def test_broker_reserve_crash_recovers_original_transaction_and_fences_producers(transaction_broker):
    broker, bundle, scope = transaction_broker
    request = {"action": "reserve", "scope": scope, "bundle": bundle}
    with pytest.raises(PermissionError):
        broker.dispatch(request, peer_uid=101)
    result = broker.dispatch(request, peer_uid=100)
    recovered = broker.dispatch(request, peer_uid=100)
    assert recovered["transaction_sha256"] == result["transaction_sha256"]
    assert recovered["verified"] == result["verified"]
    assert len(json.loads(broker.nonce_ledger.read_text())) == 4
    started = broker.dispatch({"action": "begin", "scope": scope, "transaction_sha256": result["transaction_sha256"], "source_workflow_run_id": 33949515935}, peer_uid=100)
    assert started["result"] == "started"
    with pytest.raises(RuntimeError, match="PROCESS_SIDE_EFFECTS_UNKNOWN"):
        broker.dispatch({"action": "begin", "scope": scope, "transaction_sha256": result["transaction_sha256"], "source_workflow_run_id": 33949515935}, peer_uid=100)


@pytest.mark.parametrize("after_write", [False, True])
def test_broker_nonce_commit_crash_and_complete_response_loss(transaction_broker, monkeypatch, after_write):
    import base64
    from concurrent.futures import ThreadPoolExecutor
    from ops import r297_evidence_events
    broker, bundle, scope = transaction_broker
    reserve = {"action": "reserve", "scope": scope, "bundle": bundle}
    original = r297_evidence_events._record_nonces
    def crash(*args, **kwargs):
        if after_write:
            original(*args, **kwargs)
        raise OSError("nonce publication interrupted")
    monkeypatch.setattr(r297_evidence_events, "_record_nonces", crash)
    with pytest.raises(OSError, match="interrupted"):
        broker.dispatch(reserve, peer_uid=100)
    monkeypatch.setattr(r297_evidence_events, "_record_nonces", original)
    broker = EvidenceBroker(run_ledger=broker.run_ledger, nonce_ledger=broker.nonce_ledger,
        snapshot_root=broker.snapshot_root, role_uids=broker.role_uids)
    record = broker.dispatch(reserve, peer_uid=100)
    args = {"scope": scope, "source_workflow_run_id": 33949515935, "transaction_sha256": record["transaction_sha256"]}
    from tests.test_r297_acceptance_run import process_evidence_fixture
    _, content, _, _ = process_evidence_fixture(broker.run_ledger.parent.parent, verified=record["verified"], head=scope["release_sha"], transaction=record["transaction_sha256"])
    encoded = base64.b64encode(content).decode()
    with pytest.raises(ValueError, match="begin required"):
        broker.dispatch({"action": "stage", **args, "content_base64": encoded}, peer_uid=100)
    broker.dispatch({"action": "begin", **args}, peer_uid=100)
    broker.dispatch({"action": "stage", **args, "content_base64": encoded}, peer_uid=100)
    with pytest.raises(ValueError, match="binding mismatch|changed"):
        broker.dispatch({"action": "stage", **args, "content_base64": base64.b64encode(b'{}').decode()}, peer_uid=100)
    staged = broker.dispatch({"action": "recover", **args}, peer_uid=100)
    assert staged["content_base64"] == encoded
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: broker.dispatch({"action": "complete", **args}, peer_uid=100), range(2)))
    assert results[0] == results[1]
    assert results[0]["state"] == "consumed"
    assert broker.dispatch(reserve, peer_uid=100)["content_base64"] == encoded
    assert len(json.loads(broker.nonce_ledger.read_text())) == 4
    for action in ("validate", "verify", "reserve", "nonce", "begin", "stage", "complete", "recover"):
        for uid in (101, 102, 103, 999):
            with pytest.raises(PermissionError):
                broker.dispatch({"action": action, **args}, peer_uid=uid)


def test_broker_actual_socket_uses_peer_credentials_not_request_uid(transaction_broker, monkeypatch):
    import os
    import tempfile
    import threading
    from ops.r297_evidence_broker import _Server, _Handler
    from ops.r297_broker_client import broker_request
    broker, bundle, scope = transaction_broker
    uid = os.geteuid()
    broker.role_uids = {"verifier": uid, "page_event_receiver": uid + 1, "authenticated_observer": uid + 2, "windows_relay": uid + 3}
    with tempfile.TemporaryDirectory(prefix="r297-sock-", dir="/tmp") as root:
        address = str(Path(root) / "broker.sock")
        with _Server(address, _Handler) as server:
            Path(address).chmod(0o660)
            server.broker = broker
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            monkeypatch.setenv("R297_ACCEPTANCE_BROKER_SOCKET", address)
            try:
                assert broker_request({"action": "reserve", "scope": scope, "bundle": bundle})["verified"]["web_page_close"]["closed"] is True
                broker.role_uids["verifier"], broker.role_uids["page_event_receiver"] = uid + 1, uid
                with pytest.raises(RuntimeError, match="PERMISSION_DENIED"):
                    broker_request({"action": "complete", "scope": scope, "peer_uid": uid + 1})
            finally:
                server.shutdown()
                thread.join()


def test_formal_verifier_never_opens_root_ledgers(monkeypatch):
    from datetime import datetime, timezone
    from ops import r297_broker_client, r297_evidence_events
    called = []
    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.setattr(r297_broker_client, "broker_request", lambda request: called.append(request) or {"verified": {"transport": "broker"}})
    monkeypatch.setattr(r297_evidence_events, "_nonce_ledger_descriptor", lambda *a, **kw: pytest.fail("Verifier opened root-only ledger"))
    assert r297_evidence_events.verify_acceptance_event_bundle({}, expected_scope={}, now=datetime.now(timezone.utc), nonce_ledger=Path("/root-only/nonces")) == {"transport": "broker"}
    assert called[0]["action"] == "verify"


@pytest.mark.parametrize("phase", ["stage", "body", "sidecar_b", "complete"])
def test_process_recovers_original_staged_artifact_without_business_reentry(transaction_broker, tmp_path, monkeypatch, phase):
    import base64
    import hashlib
    from ops import r297_broker_client, r297_process_acceptance
    from ops.r297_evidence_events import write_sha256_bound_file
    from tests.test_r297_acceptance_run import process_evidence_fixture
    broker, bundle, scope = transaction_broker
    record = broker.dispatch({"action": "reserve", "bundle": bundle, "scope": scope}, peer_uid=100)
    args = {"scope": scope, "source_workflow_run_id": 33949515935, "transaction_sha256": record["transaction_sha256"]}
    broker.dispatch({"action": "begin", **args}, peer_uid=100)
    evidence, content, _, _ = process_evidence_fixture(tmp_path, verified=record["verified"], head=scope["release_sha"], transaction=record["transaction_sha256"])
    broker.dispatch({"action": "stage", **args, "content_base64": base64.b64encode(content).decode()}, peer_uid=100)
    if phase == "stage":
        evidence.unlink()
    if phase == "sidecar_b":
        sidecar = Path(f"{evidence}.sha256")
        temporary = sidecar.with_name(f".{sidecar.name}.0123456789abcdef")
        temporary.write_text(f"{hashlib.sha256(content).hexdigest()}  {evidence.name}\n")
        temporary.chmod(0o600)
        sidecar.hardlink_to(temporary)
    if phase == "complete":
        write_sha256_bound_file(evidence, content)
        broker.dispatch({"action": "complete", **args}, peer_uid=100)  # Response was lost.
    def request(value):
        assert value["action"] != "begin", "recovery must not re-run business side effects"
        return broker.dispatch(value, peer_uid=100)
    monkeypatch.setattr(r297_broker_client, "broker_request", request)
    monkeypatch.setenv("APP_ENV", "acceptance")
    from ops import r297_evidence_events
    trust = r297_evidence_events.load_trust_manifest(environment="test")
    monkeypatch.setattr(r297_evidence_events, "load_trust_manifest", lambda **kw: trust)
    for field, value in scope.items():
        env = "R297_ACCEPTANCE_" + {"run_id": "RUN_ID", "run_attempt": "RUN_ATTEMPT", "challenge": "CHALLENGE"}[field] if field in {"run_id", "run_attempt", "challenge"} else "R297_EVIDENCE_" + field.upper()
        monkeypatch.setenv(env, str(value))
    signed = tmp_path / "bundle.json"
    signed.write_text(json.dumps(bundle))
    recovered = r297_process_acceptance.prepare_acceptance_transaction(signed_event_bundle=signed, output=evidence.parent, head=scope["release_sha"], nonce_ledger=Path("/root-only/not-readable"))
    assert recovered["published_digest"] == hashlib.sha256(content).hexdigest()
    assert evidence.read_bytes() == content
    assert Path(f"{evidence}.sha256").read_text() == f"{hashlib.sha256(content).hexdigest()}  {evidence.name}\n"
    assert not list(evidence.parent.glob(".*.0123456789abcdef"))


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


@pytest.mark.parametrize("hardlink_crash", [False, True, "sidecar_b"])
def test_issue_recovers_snapshot_body_only_crash(tmp_path, hardlink_crash):
    import hashlib
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
    if hardlink_crash is True:
        temporary.hardlink_to(snapshot)
    if hardlink_crash == "sidecar_b":
        sidecar = Path(f"{snapshot}.sha256")
        temporary = sidecar.with_name(f".{sidecar.name}.0123456789abcdef")
        temporary.write_text(f"{hashlib.sha256(content).hexdigest()}  {snapshot.name}\n")
        temporary.chmod(0o600)
        sidecar.hardlink_to(temporary)
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
    assert Path(f'{result["snapshot"]}.sha256').stat().st_nlink == 1


def test_ack_and_receipt_response_loss_recover_exact_original_proof(transaction_broker, monkeypatch):
    import base64
    from ops.r297_evidence_events import signed_event_sha256
    broker, bundle, scope = transaction_broker
    for index, uid in ((0, 101), (1, 102)):
        request = {"action": "receipt", "event": bundle["events"][index], "source_workflow_run_id": 33949515935}
        assert broker.dispatch(request, peer_uid=uid)["result"] == "recorded"
        assert broker.dispatch(request, peer_uid=uid)["result"] == "recovered"
    raw = {"event": "web_page_close", "observed_at": bundle["events"][0]["observed_at"], "release_sha": scope["release_sha"], "store_id": scope["store_id"]}
    request = {"action": "ack", "scope": scope, "source_workflow_run_id": 33949515935, "raw_event": raw,
        "receiver_content_base64": base64.b64encode(json.dumps(bundle["events"][0]).encode()).decode(),
        "observer_content_base64": base64.b64encode(json.dumps(bundle["events"][1]).encode()).decode()}
    for invalid in (
        {**request, "source_workflow_run_id": 33949515935.0},
        {**request, "raw_event": {**raw, "store_id": float(scope["store_id"])}},
    ):
        before = broker.run_ledger.read_bytes()
        with pytest.raises(ValueError):
            broker.dispatch(invalid, peer_uid=100)
        assert broker.run_ledger.read_bytes() == before
    publish = broker._publish_readonly
    monkeypatch.setattr(broker, "_publish_readonly", lambda *a: (_ for _ in ()).throw(OSError("publication interrupted")))
    with pytest.raises(OSError):
        broker.dispatch(request, peer_uid=100)
    persisted = json.loads(broker.run_ledger.read_text())["runs"][0]["ack_verification"]
    monkeypatch.setattr(broker, "_publish_readonly", publish)
    result = broker.dispatch(request, peer_uid=100)
    assert json.loads(Path(result["path"]).read_text()) == persisted
    for field, request_field in (("receiver_path", "receiver_content_base64"), ("observer_path", "observer_content_base64")):
        published = Path(result[field])
        assert published.read_bytes() == base64.b64decode(request[request_field])
        assert published.stat().st_mode & 0o777 == 0o444
        assert published.stat().st_nlink == 1
    assert Path(result["binding_path"]).read_bytes() == (broker.snapshot_root / scope["run_id"] / "acceptance-run-binding.json").read_bytes()
    with pytest.raises(ValueError, match="ACK verification binding mismatch"):
        broker.dispatch({**request, "receiver_content_base64": base64.b64encode(base64.b64decode(request["receiver_content_base64"]) + b"\n").decode()}, peer_uid=100)
    assert persisted["raw_event_sha256"] == signed_event_sha256(raw)
    assert broker.dispatch(request, peer_uid=100) == result
    for uid in (101, 102, 103):
        with pytest.raises(PermissionError):
            broker.dispatch(request, peer_uid=uid)
    with pytest.raises(ValueError):
        broker.dispatch({**request, "raw_event": {**raw, "observed_at": "2026-09-08T00:00:00Z"}}, peer_uid=100)
    assert json.loads(broker.run_ledger.read_text())["runs"][0]["ack_verification"] == persisted
