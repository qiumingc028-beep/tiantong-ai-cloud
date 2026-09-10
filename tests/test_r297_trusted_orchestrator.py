import json
from pathlib import Path

from ops.r297_evidence_events import write_sha256_bound_file


def test_orchestrator_machine_chain_contains_no_signer_key_or_manual_bundle():
    source = (Path(__file__).parents[1] / "ops" / "r297_trusted_orchestrator.py").read_text()
    assert '"action": "issue"' in source
    assert '"action": "ack"' in source
    assert '"action": "receive"' in source
    assert '"action": "observe"' in source
    assert '"action": "relay"' in source
    assert "build_bundle" in source
    assert "PRIVATE_KEY" not in source
    assert "/tmp/r297-signed-event-bundle.json" not in source


def test_orchestrator_bound_input_rejects_changed_sidecar(tmp_path):
    from ops.r297_trusted_orchestrator import _bound, _publish
    path = tmp_path / "machine.json"
    _publish(path, {"machine": True})
    Path(f"{path}.sha256").unlink()
    _publish(path, {"machine": True})  # response loss / process restart
    assert _bound(path) == {"machine": True}
    path.write_text(json.dumps({"machine": False}))
    try:
        _bound(path)
    except RuntimeError as error:
        assert "sidecar mismatch" in str(error)
    else:
        raise AssertionError("changed machine output accepted")
def test_orchestrator_passes_original_role_file_bytes_to_broker(monkeypatch, tmp_path):
    import base64
    import hashlib
    from ops import r297_trusted_orchestrator as orchestrator
    from tests.test_r297_evidence_event_protocol import _bundle, _scope
    from datetime import datetime, timezone
    bundle = _bundle(datetime.now(timezone.utc))
    contents = [json.dumps(event, indent=3).encode() + b"\n\n" for event in bundle["events"][:2]]
    binding = tmp_path / "binding.json"
    write_sha256_bound_file(binding, json.dumps({**_scope(), "source_workflow_run_id": 33949515935}).encode())
    calls = []
    def role_call(path, request, **kwargs):
        index = 0 if request["action"] == "receive" else 1
        return {"event": bundle["events"][index], "content_base64": base64.b64encode(contents[index]).decode(), "content_sha256": hashlib.sha256(contents[index]).hexdigest()}
    monkeypatch.setattr(orchestrator, "role_request", role_call)
    monkeypatch.setattr(orchestrator, "broker_request", lambda request: calls.append(request) or {"path": "/root-published/ack.json"})
    monkeypatch.setattr("sys.argv", ["orchestrator", "first-pair", str(binding), "raw", "raw.zip", str(tmp_path / "result.json")])
    assert orchestrator.main() == 0
    assert base64.b64decode(calls[0]["receiver_content_base64"]) == contents[0]
    assert base64.b64decode(calls[0]["observer_content_base64"]) == contents[1]


def test_orchestrator_publishes_exact_windows_relay_receipt(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from ops import r297_trusted_orchestrator as orchestrator
    from ops.r297_evidence_events import signed_event_sha256
    from tests.test_r297_evidence_event_protocol import _bundle, _scope
    bundle = _bundle(datetime.now(timezone.utc))
    scope, source = _scope(), bundle["events"][0]["payload"]["workflow_run_id"]
    binding = tmp_path / "binding.json"
    first = tmp_path / "first.json"
    electron = tmp_path / "electron.json"
    receipt_output = tmp_path / "relay-receipt.json"
    output = tmp_path / "bundle.json"
    for path, value in (
        (binding, {**scope, "source_workflow_run_id": source}),
        (first, {"events": bundle["events"][:2], "ack": {"result": "verified"}}),
        (electron, {"signer_sha": "b" * 40, "event": bundle["events"][2]}),
    ):
        write_sha256_bound_file(path, (json.dumps(value, sort_keys=True) + "\n").encode())
    receipt = {
        "schema_version": 1, "verifier_id": "tiantong-r297-receipt-broker-v1",
        "source_workflow_run_id": source,
        "event_sha256": signed_event_sha256(bundle["events"][2]), "sequence": 3,
        "received_at": datetime.now(timezone.utc).isoformat(), **scope,
    }
    calls = iter([
        {"event": bundle["events"][2], "receipt": receipt},
        {"event": bundle["events"][3]},
    ])
    monkeypatch.setattr(orchestrator, "role_request", lambda *_a, **_k: next(calls))
    monkeypatch.setattr(orchestrator, "build_bundle", lambda events, **_k: {"events": events})
    monkeypatch.setenv("R297_TRUSTED_SIGNER_SHA", "b" * 40)
    monkeypatch.setattr("sys.argv", [
        "orchestrator", "finish", str(binding), str(first), str(electron),
        str(receipt_output), str(output),
    ])
    assert orchestrator.main() == 0
    assert orchestrator._bound(receipt_output) == receipt
    assert orchestrator._bound(output) == bundle
