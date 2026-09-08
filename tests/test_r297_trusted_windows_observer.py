from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from ops.r297_trusted_windows_observer import observe_and_sign, recover_trusted_output


def _request(tmp_path):
    executable = tmp_path / "workbench.exe"
    executable.write_bytes(b"candidate-bytes")
    started = datetime(2026, 9, 7, 1, 0, tzinfo=timezone.utc)
    return executable, started, {
        "namespace": "r297-controlled-canary", "tenant_id": 1, "company_id": 1,
        "store_id": 3, "platform": "jd", "release_sha": "a" * 40,
        "run_id": "r297-run-000000000001", "run_attempt": 1,
        "challenge": "challenge-value-00000001", "source_workflow_run_id": 34123456789,
        "process_id": 42,
        "process_started_at": started.isoformat(), "executable_path": str(executable),
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
    }


def _run_binding(request, issued_at):
    return {
        **{key: request[key] for key in (
            "namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha",
            "run_id", "run_attempt", "challenge", "source_workflow_run_id",
        )},
        "issued_at": issued_at.isoformat(),
    }


def test_trusted_observer_checks_real_exit_and_post_exit_cycle(monkeypatch, tmp_path):
    executable, started, request = _request(tmp_path)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("R297_WINDOWS_RUNNER_TEST_PRIVATE_KEY_PATH", str(tmp_path / "key"))
    monkeypatch.setenv("R297_TRUSTED_OBSERVER_BACKEND_HTTPS_URL", "https://controlled.example")
    monkeypatch.setenv("R297_TRUSTED_OBSERVER_BEARER", "not-logged")
    certificate = tmp_path / "ca.pem"
    certificate.write_text("test")
    monkeypatch.setenv("R297_TRUSTED_OBSERVER_CA_PATH", str(certificate))
    running = iter([True, True, False, False])
    exited = started + timedelta(seconds=10)
    status = {
        "release_sha": "a" * 40, "namespace": "r297-controlled-canary",
        "run_id": "r297-run-000000000001", "tenant_id": 1, "company_id": 1,
        "store_id": 3, "platform": "jd", "latest_completed_at": (exited + timedelta(seconds=1)).isoformat(),
    }
    monkeypatch.setattr(
        "ops.r297_trusted_windows_observer.produce_electron_exit_event",
        lambda **kwargs: {"event_type": "electron_exit", "payload": {"exited": True}, **kwargs["scope"]},
    )
    event = observe_and_sign(
        request,
        process_probe=lambda _pid: {"path": str(executable), "started_at": started.isoformat()},
        process_is_running=lambda _pid: next(running),
        backend_reader=lambda *_args: status,
        now=lambda: exited,
        sleep=lambda _seconds: None,
        artifact_manifest={
            "release_sha": "a" * 40,
            "workbench_executable_sha256": request["executable_sha256"],
        },
        run_binding=_run_binding(request, started),
    )
    assert event["release_sha"] == "a" * 40
    assert event["payload"]["exited"] is True


def test_trusted_observer_rejects_substituted_executable(monkeypatch, tmp_path):
    executable, started, request = _request(tmp_path)
    request["executable_sha256"] = "0" * 64
    with pytest.raises(RuntimeError, match="trusted build manifest"):
        observe_and_sign(
            request,
            process_probe=lambda _pid: {"path": str(executable), "started_at": started.isoformat()},
            process_is_running=lambda _pid: True,
            artifact_manifest={
                "release_sha": "a" * 40,
                "workbench_executable_sha256": "f" * 64,
            },
            run_binding=_run_binding(request, datetime.now(timezone.utc)),
        )


def test_trusted_observer_rejects_other_acceptance_run(monkeypatch, tmp_path):
    executable, started, request = _request(tmp_path)
    monkeypatch.setenv("R297_TRUSTED_OBSERVER_BACKEND_HTTPS_URL", "https://controlled.example")
    monkeypatch.setenv("R297_TRUSTED_OBSERVER_BEARER", "not-logged")
    certificate = tmp_path / "ca.pem"
    certificate.write_text("test")
    monkeypatch.setenv("R297_TRUSTED_OBSERVER_CA_PATH", str(certificate))
    running = iter([True, False])
    with pytest.raises(RuntimeError, match="post-exit scheduler observation timed out"):
        observe_and_sign(
            request,
            process_probe=lambda _pid: {"path": str(executable), "started_at": started.isoformat()},
            process_is_running=lambda _pid: next(running),
            backend_reader=lambda *_args: {
                "release_sha": "a" * 40, "namespace": "r297-controlled-canary",
                "run_id": "another-run", "tenant_id": 1, "company_id": 1,
                "store_id": 3, "platform": "jd",
                "latest_completed_at": (started + timedelta(seconds=20)).isoformat(),
            },
            now=lambda: started + timedelta(seconds=10),
            sleep=lambda _seconds: None,
            artifact_manifest={
                "release_sha": "a" * 40,
                "workbench_executable_sha256": request["executable_sha256"],
            },
            run_binding=_run_binding(request, started),
            monotonic=iter([0, 0, 241]).__next__,
        )


def test_trusted_observer_rejects_unapproved_run_binding(tmp_path):
    executable, started, request = _request(tmp_path)
    approved = _run_binding(request, datetime.now(timezone.utc))
    approved["run_attempt"] = 2
    with pytest.raises(RuntimeError, match="run binding mismatch"):
        observe_and_sign(
            request,
            artifact_manifest={
                "release_sha": "a" * 40,
                "workbench_executable_sha256": request["executable_sha256"],
            },
            run_binding=approved,
        )


def test_trusted_observer_recovers_exact_published_output(monkeypatch, tmp_path):
    executable, started, request = _request(tmp_path)
    output = tmp_path / "trusted-event.json"
    event = {
        **{key: request[key] for key in (
            "namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha",
            "run_id", "run_attempt", "challenge",
        )},
        "event_type": "electron_exit", "issuer": "windows_runner",
        "observed_at": (started + timedelta(seconds=10)).isoformat(),
        "sequence": 3, "nonce": "trusted-output-recovery-01", "key_id": "windows-key",
        "payload": {"exited": True, "process_id": 42, "process_started_at": started.isoformat()},
        "signature": "signature",
    }
    content = (json.dumps({"signer_sha": "b" * 40, "event": event}, sort_keys=True) + "\n").encode()
    output.write_bytes(content)
    output.chmod(0o600)
    monkeypatch.setattr("ops.r297_trusted_windows_observer.verify_signed_event", lambda *args, **kwargs: ({}, {}))

    approved = _run_binding(request, started)
    manifest = {"release_sha": "a" * 40, "workbench_executable_sha256": request["executable_sha256"]}
    assert recover_trusted_output(
        output, request=request, signer_sha="b" * 40,
        artifact_manifest=manifest, run_binding=approved, now=started + timedelta(seconds=10),
    ) is True
    assert output.with_name(output.name + ".sha256").is_file()
    assert recover_trusted_output(
        output, request=request, signer_sha="b" * 40,
        artifact_manifest=manifest, run_binding=approved, now=started + timedelta(seconds=10),
    ) is True

    request["run_attempt"] = 2
    with pytest.raises(RuntimeError, match="binding mismatch"):
        recover_trusted_output(
            output, request=request, signer_sha="b" * 40,
            artifact_manifest=manifest, run_binding=approved, now=started + timedelta(seconds=10),
        )
