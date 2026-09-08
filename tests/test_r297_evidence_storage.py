import json

import pytest

from ops.r297_evidence_storage import provision_acceptance_storage


def test_provision_is_idempotent_but_never_clears_ledgers(tmp_path):
    run = tmp_path / "protected" / "runs.json"
    nonce = tmp_path / "protected" / "nonces.json"
    provision_acceptance_storage(run, nonce)
    run_payload = {"schema_version": 1, "runs": [{"state": "reserved"}]}
    nonce_payload = [{"nonce": "already-consumed"}]
    run.write_text(json.dumps(run_payload), encoding="utf-8")
    nonce.write_text(json.dumps(nonce_payload), encoding="utf-8")

    provision_acceptance_storage(run, nonce)

    assert json.loads(run.read_text()) == run_payload
    assert json.loads(nonce.read_text()) == nonce_payload
    assert run.stat().st_mode & 0o777 == 0o600
    assert nonce.stat().st_mode & 0o777 == 0o600


def test_provision_rejects_corrupt_or_writable_existing_ledgers(tmp_path):
    run = tmp_path / "protected" / "runs.json"
    nonce = tmp_path / "protected" / "nonces.json"
    provision_acceptance_storage(run, nonce)
    nonce.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="nonce ledger invalid"):
        provision_acceptance_storage(run, nonce)
    nonce.write_text("[]", encoding="utf-8")
    nonce.chmod(0o644)
    with pytest.raises(RuntimeError, match="permissions"):
        provision_acceptance_storage(run, nonce)


def test_provision_recovers_after_short_write_failure(monkeypatch, tmp_path):
    from ops import r297_evidence_storage as storage

    run = tmp_path / "protected" / "runs.json"
    nonce = tmp_path / "protected" / "nonces.json"
    real_write = storage.os.write
    calls = 0

    def fail_after_partial(descriptor, content):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(descriptor, content[:1])
        raise OSError("injected write failure")

    monkeypatch.setattr(storage.os, "write", fail_after_partial)
    with pytest.raises(OSError, match="injected"):
        provision_acceptance_storage(run, nonce)
    assert not run.exists()

    monkeypatch.setattr(storage.os, "write", real_write)
    provision_acceptance_storage(run, nonce)
    assert json.loads(run.read_text()) == {"schema_version": 1, "runs": []}
