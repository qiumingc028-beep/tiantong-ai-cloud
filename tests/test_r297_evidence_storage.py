import json

import pytest

from ops.r297_evidence_storage import provision_acceptance_storage


@pytest.mark.parametrize("member,initial", [("runs.json", b'{"schema_version":1,"runs":[]}\n'), ("runs.json.lock", b"")])
def test_first_ledger_hardlink_publication_recovers_without_deleting_commit(tmp_path, member, initial):
    root = tmp_path / "protected"
    root.mkdir(mode=0o700)
    published = root / member
    temporary = root / f".{member}.0123456789abcdef"
    temporary.write_bytes(initial)
    temporary.chmod(0o600)
    published.hardlink_to(temporary)
    inode = published.stat().st_ino
    provision_acceptance_storage(root / "runs.json", root / "nonces.json")
    assert published.stat().st_ino == inode and published.stat().st_nlink == 1
    assert published.read_bytes() == initial and not temporary.exists()


def test_initializer_cannot_remove_committed_or_unknown_hardlinks(tmp_path):
    root = tmp_path / "protected"
    root.mkdir(mode=0o700)
    published = root / "runs.json"
    content = b'{"schema_version":1,"runs":[{"state":"consumed"}]}\n'
    published.write_bytes(content)
    published.chmod(0o600)
    temporary = root / ".runs.json.0123456789abcdef"
    temporary.hardlink_to(published)
    with pytest.raises(FileExistsError):
        provision_acceptance_storage(published, root / "nonces.json")
    assert published.read_bytes() == content and temporary.exists()


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


def test_provision_fsync_failure_cannot_delete_concurrent_committed_ledger(monkeypatch, tmp_path):
    from ops import r297_evidence_storage as storage
    import os
    import stat

    run = tmp_path / "protected" / "runs.json"
    nonce = tmp_path / "protected" / "nonces.json"
    real_fsync = storage.os.fsync
    committed = b'{"schema_version":1,"runs":[{"state":"consumed"}]}\n'

    def concurrent_commit_then_fail(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode) and run.exists():
            replacement = run.with_name("concurrent-commit")
            replacement.write_bytes(committed)
            replacement.chmod(0o600)
            os.replace(replacement, run)
            raise OSError("directory fsync failure after concurrent commit")
        real_fsync(descriptor)

    monkeypatch.setattr(storage.os, "fsync", concurrent_commit_then_fail)
    with pytest.raises(OSError, match="after concurrent commit"):
        provision_acceptance_storage(run, nonce)
    assert run.read_bytes() == committed
