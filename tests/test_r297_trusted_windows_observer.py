from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from ops.r297_trusted_windows_observer import (
    _fixed_signer_checkout,
    observe_and_sign,
    recover_trusted_output,
)


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
        "state": "issued", "consumed_at": None, "event_receipts": [],
    }


def test_fixed_signer_identity_uses_protected_manifest_without_git(monkeypatch, tmp_path):
    install = tmp_path / ("b" * 40)
    code = install / "code"
    module = code / "ops" / "trusted.py"
    module.parent.mkdir(parents=True)
    module.write_bytes(b"trusted bytes\n")
    (install / "SIGNER_SHA").write_text("b" * 40 + "\n", encoding="ascii")
    manifest = [{"path": "ops/trusted.py", "sha256": hashlib.sha256(module.read_bytes()).hexdigest()}]
    (install / "CODE_MANIFEST.json").write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("R297_TRUSTED_SIGNER_SHA", "b" * 40)
    monkeypatch.setenv("R297_TEST_TRUSTED_CODE_ROOT", str(code))
    monkeypatch.setattr("ops.r297_trusted_windows_observer.subprocess.run", lambda *_a, **_k: pytest.fail("git must not run"))
    assert _fixed_signer_checkout() == "b" * 40

    module.write_bytes(b"changed\n")
    with pytest.raises(RuntimeError, match="manifest mismatch"):
        _fixed_signer_checkout()


def test_windows_accepts_original_complete_broker_snapshot_and_rejects_extra_fields(tmp_path):
    from ops.r297_trusted_windows_observer import _validate_request_approvals
    _, started, request = _request(tmp_path)
    binding = {**_run_binding(request, started), "state": "issued", "consumed_at": None, "event_receipts": []}
    manifest = {"release_sha": request["release_sha"], "workbench_executable_sha256": request["executable_sha256"]}
    assert _validate_request_approvals(request, current=started, artifact_manifest=manifest, run_binding=binding)["run_id"] == request["run_id"]
    with pytest.raises(RuntimeError):
        _validate_request_approvals(request, current=started, artifact_manifest=manifest, run_binding={**binding, "extra": True})


def test_windows_acl_probe_checks_only_write_capabilities():
    source = (__import__("pathlib").Path(__file__).parents[1] / "ops" / "r297_trusted_windows_observer.py").read_text()
    assert "FileSystemRights]::Modify" not in source
    assert "FileSystemRights]::FullControl" not in source
    assert "FileSystemRights]::ReadAndExecute" not in source
    for right in ("WriteData", "AppendData", "Delete", "ChangePermissions", "TakeOwnership"):
        assert f"FileSystemRights]::{right}" in source


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
    snapshots = iter([{**status, "latest_completed_at": None}, status])
    event = observe_and_sign(
        request,
        process_probe=lambda _pid: {"path": str(executable), "started_at": started.isoformat()},
        process_is_running=lambda _pid: next(running),
        backend_reader=lambda *_args: next(snapshots),
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


def test_trusted_observer_long_cycle_requires_exact_protected_page_ack(monkeypatch, tmp_path):
    executable, started, request = _request(tmp_path)
    current = started + timedelta(minutes=20)
    binding = _run_binding(request, started)
    monkeypatch.setenv("R297_TRUSTED_ACCEPTANCE_RUN_BINDING_SHA256", "c" * 64)
    manifest = {"release_sha": "a" * 40, "workbench_executable_sha256": request["executable_sha256"]}
    with pytest.raises(RuntimeError, match="page Observer ACK"):
        observe_and_sign(request, artifact_manifest=manifest, run_binding=binding, now=lambda: current)
    ack = {
        "schema_version": 1, "verifier_id": "tiantong-r297-ack-broker-v1", "result": "VERIFIED",
        "verified_at": (started + timedelta(seconds=30)).isoformat(), "binding_file_sha256": "c" * 64,
        "receiver_ack_file_sha256": "1" * 64, "observer_ack_file_sha256": "2" * 64,
        "raw_event_sha256": "3" * 64, "receiver_event_sha256": "4" * 64,
        "observer_event_sha256": "5" * 64,
    }
    # Approval passes; the next independent requirement is a live Electron process.
    with pytest.raises(RuntimeError, match="was not live"):
        observe_and_sign(
            request, artifact_manifest=manifest, run_binding=binding,
            page_observer_ack=ack, now=lambda: current, process_is_running=lambda _pid: False,
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


def test_backend_observer_never_forwards_bearer_on_redirect(monkeypatch, tmp_path):
    from email.message import Message
    from io import BytesIO
    from urllib.error import HTTPError
    from urllib.request import HTTPSHandler, build_opener
    from urllib.response import addinfourl
    from ops import r297_trusted_windows_observer as observer

    calls = []

    class Transport(HTTPSHandler):
        def https_open(self, request):
            calls.append((request.full_url, request.get_header("Authorization")))
            headers = Message()
            headers["Location"] = "https://untrusted.example/stolen"
            response = addinfourl(BytesIO(b"{}"), headers, request.full_url,
                                 302 if len(calls) == 1 else 200)
            response.msg = "Found" if len(calls) == 1 else "OK"
            return response

    monkeypatch.setenv("no_proxy", "*")
    monkeypatch.setattr(observer.ssl, "create_default_context", lambda **_kwargs: None)
    original_transport = build_opener(Transport())
    monkeypatch.setattr(observer, "urlopen", lambda request, **kwargs: original_transport.open(
        request, timeout=kwargs["timeout"]), raising=False)
    monkeypatch.setattr(observer, "HTTPSHandler", Transport, raising=False)
    with pytest.raises(HTTPError) as rejected:
        observer._backend_reader("https://trusted.example", "fixture-bearer", tmp_path / "ca", 3)
    assert rejected.value.code == 302
    assert calls == [("https://trusted.example/api/jd-workbench/stores/3/acceptance-status",
                      "Bearer fixture-bearer")]
@pytest.mark.parametrize("url", [
    "http://trusted.example", "https://user:pass@trusted.example",
    "https://trusted.example/base", "https://trusted.example?next=evil",
])
def test_backend_observer_rejects_noncanonical_destination(url, tmp_path):
    with pytest.raises(RuntimeError, match="destination invalid"):
        __import__("ops.r297_trusted_windows_observer", fromlist=["_backend_reader"])._backend_reader(
            url, "fixture-bearer", tmp_path / "ca", 3,
        )
