from pathlib import Path

import pytest

from ops.r297_evidence_role_service import RoleService
from ops.r297_authenticated_observer import _write_signed_event
from tests.test_r297_evidence_broker import transaction_broker


@pytest.mark.parametrize("role,index", [("receiver", 0), ("observer", 1), ("windows-relay", 2)])
@pytest.mark.parametrize("trusted", [True, False])
def test_role_recovers_original_bytes_only_after_trusted_receipt(transaction_broker, monkeypatch, tmp_path, role, index, trusted):
    import base64
    import json
    from datetime import datetime, timedelta, timezone
    from ops import r297_broker_client, r297_event_receipt, r297_evidence_role_service as service_module
    broker, bundle, scope = transaction_broker
    for event, uid in zip(bundle["events"][:index + int(trusted)], (101, 102, 103)):
        broker.dispatch({"action": "receipt", "event": event, "source_workflow_run_id": 33949515935}, peer_uid=uid)
    service = RoleService(role=role, inbox=tmp_path / "inbox", events=tmp_path / "events", verifier_uid=42)
    service.events.mkdir()
    output = service._output(scope["run_id"], ("01-pagehide.json", "02-observer.json", "03-electron-exit.json")[index])
    original = json.dumps(bundle["events"][index], indent=3).encode() + b"\n\n"
    output.write_bytes(original)
    output.chmod(0o600)
    later = datetime.now(timezone.utc) + timedelta(minutes=6)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return later
    monkeypatch.setattr(service_module, "datetime", Clock)
    monkeypatch.setattr(r297_event_receipt, "datetime", Clock)
    def broker_call(request):
        try:
            return broker.dispatch(request, peer_uid=(101, 102, 103)[index])
        except ValueError as exc:
            if str(exc) == "RECEIPT_NOT_VERIFIED":
                raise RuntimeError("R297_BROKER_RECEIPT_NOT_VERIFIED") from None
            raise
    monkeypatch.setattr(r297_broker_client, "broker_request", broker_call)
    monkeypatch.setattr(service_module, "read_scheduler_snapshot", lambda *a: pytest.fail("recovery re-observed database"))
    monkeypatch.setattr(service_module, "_produce_authenticated_observer", lambda *a, **k: pytest.fail("recovery re-signed event"))
    monkeypatch.setenv("R297_OBSERVER_DATABASE_URL", "postgresql://must-not-connect")
    request = ({"action": "observe", "subject": bundle["events"][0]} if index == 1 else {"action": "relay", "event": bundle["events"][2]})
    request["source_workflow_run_id"] = 33949515935
    if index == 0:
        raw = {**bundle["events"][0]["payload"], "observed_at": bundle["events"][0]["observed_at"],
               "release_sha": scope["release_sha"], "store_id": scope["store_id"]}
        monkeypatch.setattr(service_module, "load_pagehide_artifact_binding", lambda *a: {})
        monkeypatch.setattr(service_module, "load_native_pagehide_artifact", lambda *a, **k: raw)
        monkeypatch.setattr(service_module, "produce_page_event_receiver", lambda *a, **k: pytest.fail("recovery re-signed page"))
        request = {"action": "receive", "artifact_directory": "raw", "artifact_archive": "raw.zip", "scope": scope}
    if trusted:
        result = service.dispatch(request, uid=42)
        assert base64.b64decode(result["content_base64"]) == original
        assert service.dispatch(request, uid=42) == result
    else:
        with pytest.raises((ValueError, RuntimeError)):
            service.dispatch(request, uid=42)
        assert not Path(f"{output}.sha256").exists()
    assert output.read_bytes() == original


def _scope():
    return {
        "namespace": "r297-controlled-canary", "tenant_id": 1, "company_id": 2,
        "store_id": 3, "platform": "jd", "release_sha": "a" * 40,
        "run_id": "r297-run-1234567890", "run_attempt": 1,
        "challenge": "challenge-value-12345678",
    }


def _receipt(event):
    from ops.r297_evidence_events import signed_event_sha256
    return {
        "schema_version": 1, "verifier_id": "tiantong-r297-receipt-broker-v1",
        "source_workflow_run_id": 99, "event_sha256": signed_event_sha256(event),
        "sequence": event["sequence"], "received_at": "2026-09-10T00:00:01+00:00",
        **{field: event[field] for field in _scope()},
    }


@pytest.mark.parametrize("missing_receipt_first", [False, True])
def test_recovery_transport_error_never_falls_back_to_receipt_or_publication(monkeypatch, tmp_path, missing_receipt_first):
    import json
    from ops.r297_authenticated_observer import _recover_signed_event
    output = tmp_path / "event.json"
    event = {**_scope(), "event_type": "electron_exit", "issuer": "windows_runner"}
    original = json.dumps(event).encode()
    output.write_bytes(original)
    calls = []
    def unavailable(request):
        calls.append(request["action"])
        if missing_receipt_first and request["action"] == "recover_receipt":
            raise RuntimeError("R297_BROKER_RECEIPT_NOT_VERIFIED")
        raise RuntimeError("R297_BROKER_UNAVAILABLE")
    monkeypatch.setattr("ops.r297_broker_client.broker_request", unavailable)
    with pytest.raises(RuntimeError, match="R297_BROKER_UNAVAILABLE"):
        _recover_signed_event(output, environment="acceptance", event_type="electron_exit",
                              issuer="windows_runner", expected_scope=_scope(), source_workflow_run_id=99)
    assert calls == (["recover_receipt", "receipt"] if missing_receipt_first else ["recover_receipt"])
    assert output.read_bytes() == original and not Path(f"{output}.sha256").exists()


def test_receiver_service_fences_peer_and_records_exact_event(monkeypatch, tmp_path):
    service = RoleService(role="receiver", inbox=tmp_path / "in", events=tmp_path / "events", verifier_uid=42)
    service.inbox.mkdir()
    service.events.mkdir()
    calls = []
    monkeypatch.setattr("ops.r297_evidence_role_service.load_pagehide_artifact_binding", lambda _env: {})
    monkeypatch.setattr("ops.r297_evidence_role_service.load_native_pagehide_artifact", lambda *_a, **_k: {
        "workflow_run_id": 99, "release_sha": "a" * 40, "store_id": 3,
        "artifact_evidence_sha256": "1" * 64, "artifact_archive_sha256": "2" * 64,
        "artifact_id": 10, "artifact_name": "r297-native-pagehide-test",
    })
    monkeypatch.setattr("ops.r297_evidence_role_service.produce_page_event_receiver", lambda _raw, scope, **_kwargs: {
        **scope, "event_type": "web_page_close",
    })
    monkeypatch.setattr("ops.r297_evidence_role_service._write_signed_event", lambda path, event: (_write_signed_event(path, event), calls.append(("write", path, event))))
    monkeypatch.setattr("ops.r297_evidence_role_service._record_receipt", lambda path, event, source, **kwargs: calls.append(("receipt", path, event, source, kwargs)))
    with pytest.raises(PermissionError):
        service.dispatch({"action": "receive"}, uid=41)
    result = service.dispatch({
        "action": "receive", "artifact_directory": "pagehide", "artifact_archive": "pagehide.zip", "scope": _scope(),
    }, uid=42)
    assert result["result"] == "recorded"
    assert calls[0][0] == "write" and calls[1][0] == "receipt"
    assert calls[1][3] == 99 and calls[1][4] == {}


def test_observer_service_uses_read_only_snapshot_and_role_receipt(monkeypatch, tmp_path):
    service = RoleService(role="observer", inbox=tmp_path / "in", events=tmp_path / "events", verifier_uid=42)
    service.events.mkdir()
    subject = {
        **_scope(), "sequence": 1, "event_type": "web_page_close",
    }
    monkeypatch.setattr("ops.r297_evidence_role_service._validate_subject_event", lambda *_a, **_k: {})
    monkeypatch.setattr("ops.r297_evidence_role_service.read_scheduler_snapshot", lambda url, event: {
        "database_read_only": True, "write_privilege_count": 0, "policy_enabled": True,
        "cloud_cycles_before": 1, "cloud_cycles_after": 2,
        "eligible_store_ids": [3], "collected_store_ids_after": [3],
    })
    monkeypatch.setattr("ops.r297_evidence_role_service._produce_authenticated_observer", lambda subject, snapshot, **_k: {
        **_scope(), "sequence": 2, "event_type": "authenticated_observer",
    })
    calls = []
    monkeypatch.setattr("ops.r297_evidence_role_service._write_signed_event", lambda path, event: (_write_signed_event(path, event), calls.append("write")))
    monkeypatch.setattr("ops.r297_evidence_role_service._record_receipt", lambda path, event, source, **kwargs: calls.append(("receipt", kwargs)))
    monkeypatch.setenv("R297_OBSERVER_DATABASE_URL", "postgresql://read-only")
    result = service.dispatch({
        "action": "observe", "subject": subject,
        "source_workflow_run_id": 99,
    }, uid=42)
    assert result["result"] == "recorded"
    assert calls == ["write", ("receipt", {})]


def test_role_output_uses_private_writer_directory(tmp_path):
    root = tmp_path / "events"
    root.mkdir(mode=0o700)
    service = RoleService(role="receiver", inbox=tmp_path / "in", events=root, verifier_uid=42)
    output = service._output("r297-run-1234567890", "01-pagehide.json")
    _write_signed_event(output, {"machine_generated": True})
    assert output.parent.stat().st_mode & 0o777 == 0o700
    assert output.is_file() and Path(f"{output}.sha256").is_file()


def test_windows_relay_recovers_write_before_receipt(monkeypatch, tmp_path):
    root = tmp_path / "events"
    root.mkdir(mode=0o700)
    service = RoleService(role="windows-relay", inbox=tmp_path / "in", events=root, verifier_uid=42)
    event = {**_scope(), "sequence": 3, "event_type": "electron_exit", "issuer": "windows_runner"}
    monkeypatch.setattr("ops.r297_evidence_role_service._validate_subject_event", lambda *_a, **_k: {})
    broker_calls = []
    monkeypatch.setattr(
        "ops.r297_broker_client.broker_request",
        lambda request: broker_calls.append(request) or {
            "result": "recovered", "receipt": _receipt(request["event"]),
        },
    )
    fresh_receipts = []
    monkeypatch.setattr(
        "ops.r297_evidence_role_service._record_receipt",
        lambda _path, published, _source, **kwargs: fresh_receipts.append(kwargs) or {
            "result": "recorded", "receipt": _receipt(published),
        },
    )
    request = {"action": "relay", "event": event, "source_workflow_run_id": 99}
    assert service.dispatch(request, uid=42)["result"] == "recorded"
    Path(f"{root / event['run_id'] / '03-electron-exit.json'}.sha256").unlink()
    assert service.dispatch(request, uid=42)["result"] == "recorded"
    assert fresh_receipts == [{}]
    assert broker_calls == [{
        "action": "recover_receipt", "event": event,
        "source_workflow_run_id": 99,
    }]


def test_receiver_recovers_exact_event_through_protected_receipt(monkeypatch, tmp_path):
    root = tmp_path / "events"
    root.mkdir(mode=0o700)
    inbox = tmp_path / "in"
    inbox.mkdir()
    service = RoleService(role="receiver", inbox=inbox, events=root, verifier_uid=42)
    raw = {
        "workflow_run_id": 99, "release_sha": "a" * 40, "store_id": 3,
        "artifact_evidence_sha256": "1" * 64, "artifact_archive_sha256": "2" * 64,
        "artifact_id": 10, "artifact_name": "r297-native-pagehide-test",
    }
    recovered = {**_scope(), "sequence": 1, "event_type": "web_page_close"}
    _write_signed_event(service._output(_scope()["run_id"], "01-pagehide.json"), recovered)
    monkeypatch.setattr("ops.r297_evidence_role_service.load_pagehide_artifact_binding", lambda _env: {})
    monkeypatch.setattr("ops.r297_evidence_role_service.load_native_pagehide_artifact", lambda *_a, **_k: raw)
    recovery_calls = []
    monkeypatch.setattr(
        service, "_recover_event",
        lambda *args, **kwargs: recovery_calls.append((args, kwargs)) or (
            (recovered, _receipt(recovered)) if kwargs.get("return_receipt") else recovered
        ),
    )
    monkeypatch.setattr(
        "ops.r297_evidence_role_service._record_receipt",
        lambda *_a, **_k: pytest.fail("recovery submitted a duplicate receipt"),
    )
    result = service.dispatch({
        "action": "receive", "artifact_directory": "pagehide",
        "artifact_archive": "pagehide.zip", "scope": _scope(),
    }, uid=42)
    assert result["event"] == recovered
    assert recovery_calls[0][1]["source_workflow_run_id"] == 99
    assert recovery_calls[0][1]["expected_payload"]["workflow_run_id"] == 99


@pytest.mark.parametrize("role,event_type,sequence", [
    ("observer", "authenticated_observer", 2),
    ("windows-relay", "electron_exit", 3),
])
def test_existing_role_event_queries_protected_receipt_before_current_freshness(
    monkeypatch, tmp_path, role, event_type, sequence,
):
    root = tmp_path / "events"
    root.mkdir(mode=0o700)
    service = RoleService(role=role, inbox=tmp_path / "in", events=root, verifier_uid=42)
    subject = {**_scope(), "sequence": sequence - 1, "event_type": "web_page_close"}
    recovered = {**_scope(), "sequence": sequence, "event_type": event_type, "issuer": "authenticated_observer"}
    name = f"{sequence:02d}-observer.json" if role == "observer" else "03-electron-exit.json"
    _write_signed_event(service._output(_scope()["run_id"], name), recovered)
    recovery_calls = []
    monkeypatch.setattr(
        service, "_recover_event",
        lambda *args, **kwargs: recovery_calls.append((args, kwargs)) or (
            (recovered, _receipt(recovered)) if kwargs.get("return_receipt") else recovered
        ),
    )
    monkeypatch.setattr(
        "ops.r297_evidence_role_service._validate_subject_event",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("current-time validation ran before receipt recovery")),
    )
    monkeypatch.setattr(
        "ops.r297_evidence_role_service._record_receipt",
        lambda *_a, **_k: pytest.fail("recovery submitted a duplicate receipt"),
    )
    request = (
        {"action": "observe", "subject": subject, "source_workflow_run_id": 99}
        if role == "observer"
        else {"action": "relay", "event": recovered, "source_workflow_run_id": 99}
    )
    assert service.dispatch(request, uid=42)["result"] == "recorded"
    assert recovery_calls[0][1]["source_workflow_run_id"] == 99
