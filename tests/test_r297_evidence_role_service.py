from pathlib import Path

import pytest

from ops.r297_evidence_role_service import RoleService
from ops.r297_authenticated_observer import _write_signed_event


def _scope():
    return {
        "namespace": "r297-controlled-canary", "tenant_id": 1, "company_id": 2,
        "store_id": 3, "platform": "jd", "release_sha": "a" * 40,
        "run_id": "r297-run-1234567890", "run_attempt": 1,
        "challenge": "challenge-value-12345678",
    }


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
    monkeypatch.setattr("ops.r297_evidence_role_service._write_signed_event", lambda path, event: calls.append(("write", path, event)))
    monkeypatch.setattr("ops.r297_evidence_role_service._record_receipt", lambda path, event, source, **kwargs: calls.append(("receipt", path, event, source, kwargs)))
    with pytest.raises(PermissionError):
        service.dispatch({"action": "receive"}, uid=41)
    result = service.dispatch({
        "action": "receive", "artifact_directory": "pagehide", "artifact_archive": "pagehide.zip", "scope": _scope(),
    }, uid=42)
    assert result["result"] == "recorded"
    assert calls[0][0] == "write" and calls[1][0] == "receipt"
    assert calls[1][3] == 99 and calls[1][4] == {"recover": False}


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
    monkeypatch.setattr("ops.r297_evidence_role_service._write_signed_event", lambda path, event: calls.append("write"))
    monkeypatch.setattr("ops.r297_evidence_role_service._record_receipt", lambda path, event, source, **kwargs: calls.append(("receipt", kwargs)))
    monkeypatch.setenv("R297_OBSERVER_DATABASE_URL", "postgresql://read-only")
    result = service.dispatch({
        "action": "observe", "subject": subject,
        "source_workflow_run_id": 99,
    }, uid=42)
    assert result["result"] == "recorded"
    assert calls == ["write", ("receipt", {"recover": False})]


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
    calls = []
    monkeypatch.setattr("ops.r297_evidence_role_service._record_receipt", lambda *_a, **kwargs: calls.append(kwargs))
    request = {"action": "relay", "event": event, "source_workflow_run_id": 99}
    assert service.dispatch(request, uid=42)["result"] == "recorded"
    Path(f"{root / event['run_id'] / '03-electron-exit.json'}.sha256").unlink()
    assert service.dispatch(request, uid=42)["result"] == "recorded"
    assert calls == [{"recover": False}, {"recover": True}]


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
    service._output(_scope()["run_id"], "01-pagehide.json").write_text("existing")
    monkeypatch.setattr("ops.r297_evidence_role_service.load_pagehide_artifact_binding", lambda _env: {})
    monkeypatch.setattr("ops.r297_evidence_role_service.load_native_pagehide_artifact", lambda *_a, **_k: raw)
    monkeypatch.setattr(service, "_recover_event", lambda *_a, **_k: recovered)
    calls = []
    monkeypatch.setattr("ops.r297_evidence_role_service._record_receipt", lambda *_a, **kwargs: calls.append(kwargs))
    result = service.dispatch({
        "action": "receive", "artifact_directory": "pagehide",
        "artifact_archive": "pagehide.zip", "scope": _scope(),
    }, uid=42)
    assert result["event"] == recovered
    assert calls == [{"recover": True}]


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
    service._output(_scope()["run_id"], name).write_text("existing")
    monkeypatch.setattr(service, "_recover_event", lambda *_a, **_k: recovered)
    monkeypatch.setattr(
        "ops.r297_evidence_role_service._validate_subject_event",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("current-time validation ran before receipt recovery")),
    )
    calls = []
    monkeypatch.setattr("ops.r297_evidence_role_service._record_receipt", lambda *_a, **kwargs: calls.append(kwargs))
    request = (
        {"action": "observe", "subject": subject, "source_workflow_run_id": 99}
        if role == "observer"
        else {"action": "relay", "event": recovered, "source_workflow_run_id": 99}
    )
    assert service.dispatch(request, uid=42)["result"] == "recorded"
    assert calls == [{"recover": True}]
