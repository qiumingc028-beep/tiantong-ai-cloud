from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest


def _test_key(monkeypatch, tmp_path):
    from tests.test_r297_evidence_event_protocol import _PRIVATE_KEYS

    modulus, private = _PRIVATE_KEYS["windows_runner"]
    path = tmp_path / "windows-runner-test-key.json"
    path.write_text(json.dumps({
        "environment": "test",
        "key_id": "r297-windows_runner-test",
        "n": modulus,
        "d": private,
    }), encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("R297_WINDOWS_RUNNER_TEST_PRIVATE_KEY_PATH", str(path))


def _scope():
    return {
        "namespace": "r297-acceptance-3147ef047f46",
        "tenant_id": 1,
        "company_id": 2,
        "store_id": 7,
        "platform": "jd",
        "release_sha": "3147ef047f4664965905f4127e020f6ce15323f0",
    }


def test_windows_signer_binds_real_exit_scope_and_independent_key(monkeypatch, tmp_path):
    from ops.r297_evidence_events import _verify_signature, load_trust_manifest
    from ops.r297_windows_event_signer import produce_electron_exit_event

    _test_key(monkeypatch, tmp_path)
    started = datetime(2026, 9, 5, 8, 0, tzinfo=timezone.utc)
    exited = started + timedelta(seconds=3)

    event = produce_electron_exit_event(
        scope=_scope(), process_id=4201, process_started_at=started,
        observed_at=exited, process_is_running=lambda _pid: False,
    )

    assert {field: event[field] for field in _scope()} == _scope()
    assert event["event_type"] == "electron_exit"
    assert event["issuer"] == "windows_runner"
    assert event["sequence"] == 3
    assert event["payload"] == {
        "exited": True,
        "process_id": 4201,
        "process_started_at": started.isoformat(),
    }
    manifest, _ = load_trust_manifest(environment="test")
    key = next(key for key in manifest["keys"] if key["issuer"] == "windows_runner")
    _verify_signature(event, key)


def test_windows_signer_rejects_live_process(monkeypatch, tmp_path):
    from ops.r297_windows_event_signer import produce_electron_exit_event

    _test_key(monkeypatch, tmp_path)
    now = datetime.now(timezone.utc)
    with pytest.raises(RuntimeError, match="electron process still running"):
        produce_electron_exit_event(
            scope=_scope(), process_id=4201,
            process_started_at=now - timedelta(seconds=1), observed_at=now,
            process_is_running=lambda _pid: True,
        )


def test_windows_signer_fails_closed_without_real_private_key(monkeypatch):
    from ops.r297_windows_event_signer import produce_electron_exit_event

    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.delenv("R297_WINDOWS_RUNNER_PRIVATE_KEY_PATH", raising=False)
    now = datetime.now(timezone.utc)
    with pytest.raises(RuntimeError, match="windows runner private key missing"):
        produce_electron_exit_event(
            scope=_scope(), process_id=4201,
            process_started_at=now - timedelta(seconds=1), observed_at=now,
            process_is_running=lambda _pid: False,
        )


def test_windows_process_probe_uses_native_wait_not_posix_signal(monkeypatch):
    from ops import r297_windows_event_signer as signer

    calls = []
    monkeypatch.setattr(signer.os, "name", "nt")
    monkeypatch.setattr(signer, "_windows_process_is_running", lambda pid: calls.append(pid) or False)
    monkeypatch.setattr(signer.os, "kill", lambda *_args: pytest.fail("os.kill must not run on Windows"))

    assert signer._process_is_running(4201) is False
    assert calls == [4201]


def test_windows_process_probe_declares_pointer_width_and_last_error_contract():
    from ops import r297_windows_event_signer as signer

    source = __import__("inspect").getsource(signer._windows_process_is_running)
    assert 'ctypes.WinDLL("kernel32", use_last_error=True)' in source
    assert "OpenProcess.restype = ctypes.c_void_p" in source
    assert "WaitForSingleObject.argtypes" in source
    assert "CloseHandle.argtypes" in source
    assert "WAIT_OBJECT_0" in source
    assert "WAIT_TIMEOUT" in source
    assert "raise OSError(ctypes.get_last_error()" in source
