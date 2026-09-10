"""Recovery ordering on a filesystem adapter; NOT native Windows ACL evidence."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
from datetime import timedelta
from types import SimpleNamespace

import pytest

from ops import r297_windows_file_security as security


class FilesystemChecks:
    """Real temporary hardlinks, with explicit simulated native flush failures."""
    def __init__(self):
        self.events = []
        self.fail_flush = False

    @contextmanager
    def lock(self, parent):
        yield parent

    @contextmanager
    def open(self, path, *, delete=False):
        descriptor = os.open(path, os.O_RDONLY)
        try:
            yield descriptor
        finally:
            os.close(descriptor)

    def identity(self, descriptor):
        value = os.fstat(descriptor)
        return (value.st_dev, value.st_ino, 0, value.st_nlink)

    def read(self, descriptor):
        os.lseek(descriptor, 0, os.SEEK_SET)
        return os.read(descriptor, 2 * 1024 * 1024 + 1)

    def remove(self, descriptor, path):
        assert os.fstat(descriptor).st_ino == path.stat().st_ino
        self.events.append("remove")
        path.unlink()

    def flush(self, descriptor):
        self.events.append("file_flush")

    def flush_directory(self, parent):
        self.events.append("directory_flush")
        if self.fail_flush:
            raise OSError("simulated native directory flush failure")


def _pair(tmp_path, phase):
    body = tmp_path / "event.json"
    content = b'{"original":"signed-event-bytes"}\n'
    sidecar = Path(str(body) + ".sha256")
    body.write_bytes(content)
    sidecar.write_bytes(f"{hashlib.sha256(content).hexdigest()}  event.json\n".encode())
    target = body if phase == "body" else sidecar
    temporary = target.with_name(f".{target.name}.0123456789abcdef")
    os.link(target, temporary)
    return body, sidecar, temporary, content


@pytest.mark.parametrize("phase", ["body", "sidecar"])
def test_recovery_validates_original_before_unlink_and_flushes_after(tmp_path, monkeypatch, phase):
    body, sidecar, temporary, original = _pair(tmp_path, phase)
    io = FilesystemChecks()
    monkeypatch.setattr(security, "_RecoveryIO", lambda: io, raising=False)
    def validate(content):
        assert content == original and temporary.exists()
        io.events.append("verified")
    assert security.recover_bound_file(body, validate=validate) == original
    assert body.read_bytes() == original and not temporary.exists()
    assert body.stat().st_nlink == sidecar.stat().st_nlink == 1
    assert io.events.index("verified") < io.events.index("remove")
    assert io.events[-1] == "directory_flush"


@pytest.mark.parametrize("defect", ["third_link", "foreign_name", "wrong_inode", "wrong_sidecar", "unverified"])
def test_invalid_recovery_never_deletes_or_rewrites(tmp_path, monkeypatch, defect):
    body, sidecar, temporary, original = _pair(tmp_path, "body")
    io = FilesystemChecks()
    monkeypatch.setattr(security, "_RecoveryIO", lambda: io)
    if defect == "third_link": os.link(body, tmp_path / "extra")
    if defect == "foreign_name": temporary = temporary.rename(tmp_path / "foreign")
    if defect == "wrong_inode":
        temporary.rename(tmp_path / "foreign")
        temporary.write_bytes(original)
    if defect == "wrong_sidecar": sidecar.write_bytes(b"wrong digest")
    def validate(content):
        if defect == "unverified": raise ValueError("receipt not verified")
    with pytest.raises((RuntimeError, ValueError)):
        security.recover_bound_file(body, validate=validate)
    assert temporary.exists() and body.read_bytes() == original
    assert "remove" not in io.events


@pytest.mark.parametrize("after_remove", [False, True])
def test_flush_failure_is_not_success_and_retry_reflushes_original(tmp_path, monkeypatch, after_remove):
    body, sidecar, temporary, original = _pair(tmp_path, "sidecar")
    io = FilesystemChecks()
    initial_flush = io.flush_directory
    def flush(parent):
        io.fail_flush = not after_remove or "remove" in io.events
        initial_flush(parent)
    io.flush_directory = flush
    monkeypatch.setattr(security, "_RecoveryIO", lambda: io)
    with pytest.raises(OSError, match="flush failure"):
        security.recover_bound_file(body, validate=lambda value: None)
    assert temporary.exists() is not after_remove
    fresh = FilesystemChecks()
    monkeypatch.setattr(security, "_RecoveryIO", lambda: fresh)
    assert security.recover_bound_file(body, validate=lambda value: None) == original
    assert fresh.events[-1] == "directory_flush"
    assert not temporary.exists()


def test_public_reader_never_selects_recovery_mode(monkeypatch):
    @contextmanager
    def open_native(path, **options):
        assert not options.get("recovery")
        raise RuntimeError("R297_WINDOWS_HARDLINK_REJECTED")
        yield
    monkeypatch.setattr(security, "_protected_open", open_native)
    with pytest.raises(RuntimeError, match="HARDLINK_REJECTED"):
        with security.protected_open("C:/protected/event.json", output=True):
            pytest.fail("public read accepted a hardlink")


@pytest.mark.parametrize("failure", ["second_spawn", "first_timeout", "both_busy"])
def test_native_probe_reaps_all_children_and_requires_success(monkeypatch, tmp_path, failure):
    from ops import r297_windows_recovery_probe as probe
    children = []
    class Child:
        returncode = None
        reaped = False
        killed = False
        def communicate(self, timeout):
            if failure == "first_timeout" and timeout == 30:
                raise probe.subprocess.TimeoutExpired("native-test-child", timeout)
            self.returncode = 1
            self.reaped = True
            return b"", b"R297_WINDOWS_PUBLICATION_BUSY_OR_UNSAFE"
        def poll(self): return self.returncode
        def kill(self): self.killed = True; self.returncode = -9
    def spawn(*args, **kwargs):
        if failure == "second_spawn" and children:
            raise OSError("spawn failed")
        child = Child(); children.append(child); return child
    monkeypatch.setattr(probe.subprocess, "Popen", spawn)
    with pytest.raises((RuntimeError, OSError)):
        probe._recover_concurrently(tmp_path)
    assert all(child.reaped and child.returncode is not None for child in children)
    if failure != "both_busy": assert all(child.killed for child in children)


@pytest.mark.parametrize("receipt_state", ["original", "missing", "rewritten"])
def test_windows_dispatch_verifies_signed_receipt_before_cleanup_and_finishes_sidecar(tmp_path, monkeypatch, receipt_state):
    from ops import r297_trusted_windows_observer as observer
    from ops.r297_evidence_events import signed_event_sha256
    from tests.test_r297_evidence_event_protocol import _sign
    from tests.test_r297_trusted_windows_observer import _request, _run_binding
    _, started, request = _request(tmp_path)
    scope = {key: request[key] for key in observer._SCOPE_FIELDS}
    event = _sign({**scope, "event_type": "electron_exit", "issuer": "windows_runner",
                   "nonce": "original-recovery-event-0001", "sequence": 3,
                   "observed_at": started.isoformat(), "payload": {
                       "exited": True, "process_id": request["process_id"],
                       "process_started_at": started.isoformat()}})
    original = (json.dumps({"signer_sha": "b" * 40, "event": event}, indent=2) + "\n").encode()
    body = tmp_path / "event.json"
    body.write_bytes(original); body.chmod(0o600)
    temporary = body.with_name(f".{body.name}.0123456789abcdef")
    os.link(body, temporary)
    receipt = {**scope, "schema_version": 1, "verifier_id": "tiantong-r297-receipt-broker-v1",
               "sequence": 3, "source_workflow_run_id": request["source_workflow_run_id"],
               "event_sha256": signed_event_sha256(event), "received_at": started.isoformat()}
    ack = {"schema_version": 1, "verifier_id": "tiantong-r297-ack-broker-v1", "result": "VERIFIED",
           "verified_at": started.isoformat(), "binding_file_sha256": "c" * 64,
           **{key: "d" * 64 for key in ("receiver_ack_file_sha256", "observer_ack_file_sha256",
                                       "raw_event_sha256", "receiver_event_sha256", "observer_event_sha256")}}
    if receipt_state == "missing": receipt = None
    if receipt_state == "rewritten": receipt["event_sha256"] = "e" * 64
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("R297_TRUSTED_ACCEPTANCE_RUN_BINDING_SHA256", "c" * 64)
    # Exercise the Windows caller with a filesystem adapter, not a native claim.
    monkeypatch.setattr(observer, "os", SimpleNamespace(name="nt", getenv=os.getenv, environ=os.environ))
    io = FilesystemChecks()
    monkeypatch.setattr(security, "_RecoveryIO", lambda: io)
    kwargs = dict(request=request, signer_sha="b" * 40, run_binding=_run_binding(request, started),
                  artifact_manifest={"release_sha": request["release_sha"],
                                     "workbench_executable_sha256": request["executable_sha256"]},
                  page_observer_ack=ack, relay_receipt=receipt, now=started + timedelta(minutes=6))
    if receipt_state == "original":
        assert observer.recover_trusted_output(body, **kwargs) is True
        assert not temporary.exists()
        assert Path(str(body) + ".sha256").read_text().split() == [hashlib.sha256(original).hexdigest(), body.name]
    else:
        with pytest.raises(RuntimeError, match="relay receipt"):
            observer.recover_trusted_output(body, **kwargs)
        assert temporary.exists() and "remove" not in io.events
        assert not Path(str(body) + ".sha256").exists()
    assert body.read_bytes() == original
