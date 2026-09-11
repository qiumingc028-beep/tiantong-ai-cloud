from pathlib import Path

import pytest

from ops.r297_authenticated_observer import _record_receipt, _recover_signed_event, _write_signed_event


def _recover(path):
    return _recover_signed_event(path, environment="acceptance", event_type="electron_exit",
                                 issuer="windows_runner", expected_scope={}, source_workflow_run_id=99)


def _published(path, event):
    _write_signed_event(path, event)
    return path


def test_recovery_queries_broker_before_fresh_receipt_fallback(monkeypatch, tmp_path):
    path = tmp_path / "event.json"
    event = {"machine_generated": True}
    _published(path, event)
    calls = []
    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.setattr(
        "ops.r297_broker_client.broker_request",
        lambda request: calls.append(request) or {"result": "recovered"},
    )
    monkeypatch.setattr(
        "ops.r297_event_receipt.record_event",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("fresh receipt path used")),
    )
    _record_receipt(path, event, 99, recover=True)
    assert calls == [{
        "action": "recover_receipt", "event": event,
        "source_workflow_run_id": 99,
    }]


def test_unverified_recovery_can_only_fall_back_to_normal_freshness_gate(monkeypatch, tmp_path):
    path = tmp_path / "event.json"
    event = {"machine_generated": True}
    _published(path, event)
    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.setattr(
        "ops.r297_broker_client.broker_request",
        lambda _request: (_ for _ in ()).throw(RuntimeError("R297_BROKER_RECEIPT_NOT_VERIFIED")),
    )
    calls = []
    def request(value):
        if value["action"] == "recover_receipt":
            raise RuntimeError("R297_BROKER_RECEIPT_NOT_VERIFIED")
        calls.append(value["event"])
        return {"result": "recorded"}
    monkeypatch.setattr("ops.r297_broker_client.broker_request", request)
    _record_receipt(path, event, 99, recover=True)
    assert calls == [event]


def test_recovery_does_not_downgrade_other_broker_failures(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "acceptance")
    path = Path(tmp_path / "event.json")
    _published(path, {})
    monkeypatch.setattr(
        "ops.r297_broker_client.broker_request",
        lambda _request: (_ for _ in ()).throw(RuntimeError("R297_BROKER_TRANSACTION_CONFLICT")),
    )
    with pytest.raises(RuntimeError, match="TRANSACTION_CONFLICT"):
        _record_receipt(path, {}, 99, recover=True)


def test_recover_signed_event_uses_the_protected_receipt(monkeypatch, tmp_path):
    path = tmp_path / "event.json"
    event = {"event_type": "electron_exit", "issuer": "windows_runner"}
    _published(path, event)
    calls = []
    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.setattr(
        "ops.r297_broker_client.broker_request",
        lambda request: calls.append(request) or {"result": "recovered"},
    )
    assert _recover(path)["result"] == "recovered"
    assert calls == [{"action": "recover_receipt", "event": event, "source_workflow_run_id": 99}]


def test_recover_signed_event_falls_back_only_for_unverified_receipt(monkeypatch, tmp_path):
    path = tmp_path / "event.json"
    event = {"event_type": "electron_exit", "issuer": "windows_runner"}
    _published(path, event)
    calls = []
    monkeypatch.setenv("APP_ENV", "acceptance")

    def request(value):
        calls.append(value["action"])
        if value["action"] == "recover_receipt":
            raise RuntimeError("R297_BROKER_RECEIPT_NOT_VERIFIED")
        return {"result": "recorded"}

    monkeypatch.setattr("ops.r297_broker_client.broker_request", request)
    assert _recover(path)["result"] == "recorded"
    assert calls == ["recover_receipt", "receipt"]


def test_recover_signed_event_preserves_other_broker_failures(monkeypatch, tmp_path):
    path = tmp_path / "event.json"
    _published(path, {"event_type": "electron_exit", "issuer": "windows_runner"})
    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.setattr(
        "ops.r297_broker_client.broker_request",
        lambda _request: (_ for _ in ()).throw(RuntimeError("R297_BROKER_TRANSACTION_CONFLICT")),
    )
    with pytest.raises(RuntimeError, match="TRANSACTION_CONFLICT"):
        _recover(path)
