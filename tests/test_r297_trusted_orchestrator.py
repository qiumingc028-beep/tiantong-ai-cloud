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
