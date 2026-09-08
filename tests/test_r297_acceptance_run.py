from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from ops.r297_acceptance_run import (
    complete_acceptance_run, consume_acceptance_run, issue_acceptance_run, main,
    recover_staged_acceptance_output, reserve_acceptance_run, stage_acceptance_output,
    validate_acceptance_run,
)


def _ledger(tmp_path):
    root = tmp_path / "run-ledger"
    root.mkdir(mode=0o700)
    ledger = root / "runs.json"
    ledger.write_text('{"schema_version":1,"runs":[]}\n', encoding="utf-8")
    ledger.chmod(0o600)
    lock = root / "runs.json.lock"
    lock.write_text("", encoding="utf-8")
    lock.chmod(0o600)
    return ledger


def _scope():
    return {
        "namespace": "r297-controlled-canary", "tenant_id": 1, "company_id": 1,
        "store_id": 3, "platform": "jd", "release_sha": "a" * 40,
    }


def test_protected_orchestrator_issues_and_consumes_one_run(tmp_path):
    ledger = _ledger(tmp_path)
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    record = issue_acceptance_run(
        ledger, scope=_scope(), source_workflow_run_id=34000000001, run_attempt=2,
        now=now,
    )
    expected = {field: record[field] for field in {*_scope(), "run_id", "run_attempt", "challenge"}}

    consume_acceptance_run(
        ledger, expected_scope=expected, source_workflow_run_id=34000000001, now=now,
    )

    stored = json.loads(ledger.read_text())["runs"][0]
    assert stored["state"] == "consumed"
    with pytest.raises(ValueError, match="missing or consumed"):
        consume_acceptance_run(
            ledger, expected_scope=expected, source_workflow_run_id=34000000001, now=now,
        )


def test_source_run_cannot_be_reissued_with_different_scope(tmp_path):
    ledger = _ledger(tmp_path)
    issue_acceptance_run(ledger, scope=_scope(), source_workflow_run_id=34000000001, run_attempt=1)
    changed = {**_scope(), "tenant_id": 9}
    with pytest.raises(ValueError, match="already consumed"):
        issue_acceptance_run(ledger, scope=changed, source_workflow_run_id=34000000001, run_attempt=2)


def test_identical_issue_recovers_same_challenge(tmp_path):
    ledger = _ledger(tmp_path)
    first = issue_acceptance_run(
        ledger, scope=_scope(), source_workflow_run_id=34000000001, run_attempt=1,
    )
    recovered = issue_acceptance_run(
        ledger, scope=_scope(), source_workflow_run_id=34000000001, run_attempt=1,
    )

    assert recovered == first
    assert len(json.loads(ledger.read_text())["runs"]) == 1


def test_concurrent_issue_uses_current_ledger_inode_under_lock(tmp_path):
    ledger = _ledger(tmp_path)

    def issue():
        record = issue_acceptance_run(
            ledger, scope=_scope(), source_workflow_run_id=34000000001,
            run_attempt=1,
        )
        return record["run_id"], record["challenge"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: issue(), range(2)))

    assert results[0] == results[1]
    assert len(json.loads(ledger.read_text())["runs"]) == 1


def test_run_challenge_expires_after_five_minutes(tmp_path):
    ledger = _ledger(tmp_path)
    issued_at = datetime(2026, 9, 7, tzinfo=timezone.utc)
    record = issue_acceptance_run(
        ledger, scope=_scope(), source_workflow_run_id=34000000001,
        run_attempt=1, now=issued_at,
    )
    expected = {field: record[field] for field in {*_scope(), "run_id", "run_attempt", "challenge"}}

    with pytest.raises(ValueError, match="expired"):
        validate_acceptance_run(
            ledger, expected_scope=expected, source_workflow_run_id=34000000001,
            now=issued_at + timedelta(minutes=6),
        )
    with pytest.raises(ValueError, match="expired"):
        consume_acceptance_run(
            ledger, expected_scope=expected, source_workflow_run_id=34000000001,
            now=issued_at + timedelta(minutes=6),
        )


def test_run_rejects_different_pagehide_workflow(tmp_path):
    ledger = _ledger(tmp_path)
    record = issue_acceptance_run(
        ledger, scope=_scope(), source_workflow_run_id=34000000001, run_attempt=1,
    )
    expected = {field: record[field] for field in {*_scope(), "run_id", "run_attempt", "challenge"}}

    with pytest.raises(ValueError, match="source workflow"):
        validate_acceptance_run(
            ledger, expected_scope=expected, source_workflow_run_id=34000000002,
        )


def test_protected_cli_publishes_binding_without_printing_challenge(monkeypatch, tmp_path, capsys):
    ledger = _ledger(tmp_path)
    output_root = tmp_path / "binding"
    output_root.mkdir(mode=0o700)
    output = output_root / "run.json"
    monkeypatch.setattr("sys.argv", [
        "r297_acceptance_run.py", str(ledger), str(output),
        "--source-workflow-run-id", "34000000001", "--run-attempt", "1",
        "--namespace", "r297-controlled-canary", "--tenant-id", "1",
        "--company-id", "1", "--store-id", "3", "--platform", "jd",
        "--release-sha", "a" * 40,
    ])

    assert main() == 0

    record = json.loads(output.read_text())
    captured = capsys.readouterr().out
    assert record["challenge"] not in captured
    assert output.stat().st_mode & 0o777 == 0o600
    assert output.with_name("run.json.sha256").is_file()


def test_acceptance_transaction_recovers_each_publish_boundary(tmp_path):
    from ops.r297_evidence_events import write_sha256_bound_file

    ledger = _ledger(tmp_path)
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    record = issue_acceptance_run(
        ledger, scope=_scope(), source_workflow_run_id=34000000001,
        run_attempt=1, now=now,
    )
    expected = {field: record[field] for field in {*_scope(), "run_id", "run_attempt", "challenge"}}
    transaction = "1" * 64

    assert reserve_acceptance_run(
        ledger, expected_scope=expected, source_workflow_run_id=34000000001,
        transaction_sha256=transaction, now=now,
    ) == "reserved"
    validate_acceptance_run(
        ledger, expected_scope=expected, source_workflow_run_id=34000000001,
        transaction_sha256=transaction, now=now,
    )
    with pytest.raises(ValueError, match="transaction binding"):
        validate_acceptance_run(
            ledger, expected_scope=expected, source_workflow_run_id=34000000001,
            transaction_sha256="2" * 64, now=now,
        )
    assert reserve_acceptance_run(
        ledger, expected_scope=expected, source_workflow_run_id=34000000001,
        transaction_sha256=transaction, now=now,
    ) == "recovering"

    assert stage_acceptance_output(
        ledger, expected_scope=expected, source_workflow_run_id=34000000001,
        transaction_sha256=transaction, content=b'{"result":"PASS"}\n', now=now,
    ) == hashlib.sha256(b'{"result":"PASS"}\n').hexdigest()
    assert recover_staged_acceptance_output(
        ledger, expected_scope=expected, source_workflow_run_id=34000000001,
        transaction_sha256=transaction, now=now,
    ) == b'{"result":"PASS"}\n'
    with pytest.raises(ValueError, match="output changed"):
        stage_acceptance_output(
            ledger, expected_scope=expected, source_workflow_run_id=34000000001,
            transaction_sha256=transaction, content=b'{"result":"BLOCK"}\n', now=now,
        )

    mismatched = tmp_path / "mismatched.json"
    write_sha256_bound_file(mismatched, b'{"result":"BLOCK"}\n')
    with pytest.raises(ValueError, match="differs from staged"):
        complete_acceptance_run(
            ledger, expected_scope=expected, source_workflow_run_id=34000000001,
            transaction_sha256=transaction, published_path=mismatched, now=now,
        )

    output_root = tmp_path / "formal-output"
    output_root.mkdir(mode=0o700)
    output = output_root / "evidence.json"
    content = b'{"result":"PASS"}\n'
    write_sha256_bound_file(output, content)
    assert complete_acceptance_run(
        ledger, expected_scope=expected, source_workflow_run_id=34000000001,
        transaction_sha256=transaction, published_path=output, now=now,
    ) == "consumed"
    assert complete_acceptance_run(
        ledger, expected_scope=expected, source_workflow_run_id=34000000001,
        transaction_sha256=transaction, published_path=output, now=now,
    ) == "recovered"


def test_staged_output_is_bounded_and_expired_bytes_are_compacted(tmp_path):
    ledger = _ledger(tmp_path)
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    record = issue_acceptance_run(
        ledger, scope=_scope(), source_workflow_run_id=34000000001,
        run_attempt=1, now=now,
    )
    expected = {field: record[field] for field in {*_scope(), "run_id", "run_attempt", "challenge"}}
    transaction = "1" * 64
    reserve_acceptance_run(
        ledger, expected_scope=expected, source_workflow_run_id=34000000001,
        transaction_sha256=transaction, now=now,
    )
    with pytest.raises(ValueError, match="size invalid"):
        stage_acceptance_output(
            ledger, expected_scope=expected, source_workflow_run_id=34000000001,
            transaction_sha256=transaction, content=b"x" * (2 * 1024 * 1024 + 1),
            now=now,
        )
    digest = stage_acceptance_output(
        ledger, expected_scope=expected, source_workflow_run_id=34000000001,
        transaction_sha256=transaction, content=b'{"bounded":true}\n', now=now,
    )

    issue_acceptance_run(
        ledger, scope=_scope(), source_workflow_run_id=34000000002,
        run_attempt=2, now=now + timedelta(minutes=6),
    )
    expired = json.loads(ledger.read_text())["runs"][0]
    assert expired["pending_output_sha256"] == digest
    assert "pending_output_base64" not in expired
    with pytest.raises(ValueError, match="expired"):
        recover_staged_acceptance_output(
            ledger, expected_scope=expected, source_workflow_run_id=34000000001,
            transaction_sha256=transaction, now=now + timedelta(minutes=6),
        )


def test_acceptance_transaction_rejects_other_bundle_and_missing_output(tmp_path):
    ledger = _ledger(tmp_path)
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    record = issue_acceptance_run(
        ledger, scope=_scope(), source_workflow_run_id=34000000001,
        run_attempt=1, now=now,
    )
    expected = {field: record[field] for field in {*_scope(), "run_id", "run_attempt", "challenge"}}
    reserve_acceptance_run(
        ledger, expected_scope=expected, source_workflow_run_id=34000000001,
        transaction_sha256="1" * 64, now=now,
    )
    with pytest.raises(ValueError, match="different transaction"):
        reserve_acceptance_run(
            ledger, expected_scope=expected, source_workflow_run_id=34000000001,
            transaction_sha256="2" * 64, now=now,
        )
    with pytest.raises(RuntimeError, match="published evidence missing"):
        complete_acceptance_run(
            ledger, expected_scope=expected, source_workflow_run_id=34000000001,
            transaction_sha256="1" * 64, published_path=tmp_path / "missing.json", now=now,
        )


def test_process_evidence_orders_reserve_nonce_publish_and_complete():
    from pathlib import Path

    source = Path("ops/r297_process_acceptance.py").read_text(encoding="utf-8")
    assert source.index("prepare_acceptance_transaction(") < source.index("docker run isolated postgres:16")
    assert source.index("reserve_acceptance_run(") < source.index("verify_acceptance_event_bundle(")
    assert source.index("verify_acceptance_event_bundle(") < source.index("write_sha256_bound_file(evidence")
    assert source.index("write_sha256_bound_file(evidence") < source.rindex("complete_acceptance_run(")
    assert "allow_nonce_recovery=reservation == \"recovering\"" in source


def test_process_evidence_recovery_decision_precedes_runtime_setup():
    from pathlib import Path

    source = Path("ops/r297_process_acceptance.py").read_text(encoding="utf-8")
    recovery = source.index("if acceptance[\"published_digest\"]:")
    assert recovery < source.index("postgres_password = secrets.token_urlsafe")
    assert recovery < source.index("temporary = Path(tempfile.mkdtemp")


def test_process_manual_resume_runs_real_probe_before_idle_report():
    from pathlib import Path

    source = Path("ops/r297_process_acceptance.py").read_text(encoding="utf-8")
    rejected = source.index("HUMAN_ACTION_PRE_PROBE_IDLE_ACCEPTED")
    probe = source.index("recovery_probe_result = wait_sync_log")
    idle = source.index('"client_version": "2.97.0", "status": "IDLE"', probe)
    assert rejected < probe < idle
    assert '"recovery_probe_status": recovery_probe_result["status"]' in source


def test_formal_entry_recovers_output_before_starting_processes(monkeypatch, tmp_path):
    from ops import r297_process_acceptance as process

    bundle = {"events": [{
        "event_type": "web_page_close", "payload": {"workflow_run_id": 34000000001},
    }]}
    signed = tmp_path / "bundle.json"
    signed.write_text(json.dumps(bundle), encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir(mode=0o700)
    nonce = tmp_path / "nonces.json"
    run_ledger = tmp_path / "runs.json"
    monkeypatch.setenv("R297_EVIDENCE_NAMESPACE", "r297-acceptance-" + "a" * 12)
    monkeypatch.setenv("R297_EVIDENCE_TENANT_ID", "1")
    monkeypatch.setenv("R297_EVIDENCE_COMPANY_ID", "2")
    monkeypatch.setenv("R297_EVIDENCE_STORE_ID", "3")
    monkeypatch.setenv("R297_ACCEPTANCE_RUN_ID", "run-1")
    monkeypatch.setenv("R297_ACCEPTANCE_RUN_ATTEMPT", "1")
    monkeypatch.setenv("R297_ACCEPTANCE_CHALLENGE", "challenge-00000001")
    monkeypatch.setenv("R297_ACCEPTANCE_RUN_LEDGER", str(run_ledger))
    calls = []
    monkeypatch.setattr(process, "reserve_acceptance_run", lambda *a, **k: calls.append("reserve") or "recovering")
    monkeypatch.setattr(process, "verify_acceptance_event_bundle", lambda *a, **k: calls.append("nonce") or {"verified": True})
    monkeypatch.setattr(process, "recover_staged_acceptance_output", lambda *a, **k: calls.append("staged") or b'{}')
    monkeypatch.setattr(process, "_validate_process_evidence", lambda *a, **k: calls.append("validate"))
    monkeypatch.setattr(process, "write_sha256_bound_file", lambda *a, **k: calls.append("output") or "f" * 64)
    monkeypatch.setattr(process, "complete_acceptance_run", lambda *a, **k: calls.append("complete") or "consumed")

    result = process.prepare_acceptance_transaction(
        signed_event_bundle=signed, output=output, head="a" * 40, nonce_ledger=nonce,
    )

    assert result["published_digest"] == "f" * 64
    assert calls == ["reserve", "nonce", "staged", "validate", "output", "complete"]


def test_process_evidence_recovers_body_only_and_completed_publication(tmp_path):
    from ops.r297_process_acceptance import recover_published_process_evidence

    root = tmp_path / "output"
    root.mkdir(mode=0o700)
    evidence = root / "R297_PROCESS_ACCEPTANCE_EVIDENCE.json"
    transaction = "1" * 64
    raw = root / "raw.jsonl"
    fixture = root / "fixture.json"
    canaries = {key: f"canary-{key}" for key in ("buyer_name", "phone", "address", "cookie", "token", "password")}
    fixture.write_text(json.dumps(canaries), encoding="utf-8")
    verified = {
        "web_page_close": {"closed": True},
        "electron_exit": {"exited": True},
        "authenticated_observer": {"verified_subject_count": 2},
    }
    sections = {
        "worker_restart": {"pid_before": 1, "pid_after": 2, "recovered": True},
        "multi_worker": {"worker_pids": [2, 3], "distinct_worker_pids": True, "status": "success", "claim_log_count": 1, "database_log_count": 1, "postgresql_store_claim_count": 1, "same_store_claim_count": 1},
        "retry_schedule": {"expected_seconds": [30, 120, 300, 900, 1800], "observed_seconds": [30, 120, 300, 900, 1800]},
        "manual_resume": {"before_status": "HUMAN_ACTION_REQUIRED", "recovery_probe_status": "success", "automatic_enqueue_count": 1, "task_status": "success", "recovery_probe_task_id": "probe-1", "task_id": "task-1"},
        "human_action_detection": {"detected_status": "HUMAN_ACTION_REQUIRED", "automatic_resume_status": "success"},
        "service_restart": {"runtime_pid_before": 3, "runtime_pid_after": 4, "runtime_session_restored": True, "backend_pid_before": 5, "backend_pid_after": 6},
        "two_cycle": [{"task_id": "cycle-1", "status": "success", "database_log_count": 1}, {"task_id": "cycle-2", "status": "success", "database_log_count": 1}],
        "idempotent_write": {"metric_row_count": 1, "rows": [{"id": 1}]},
        "orphan_recovery": {"task_id": "orphan-1", "processing_observed": True, "killed_worker_pid": 7, "final_status": "success", "database_log_count": 1},
        "runtime_restart": {"pid_before": 3, "pid_after": 4, "session_restored": True},
        "explicit_ack": {"ready_count": 0, "processing_count": 0, "metadata_count": 0},
    }
    gate_sections = {**verified, **sections}
    raw_events = [{"event": "command", "command": "run real acceptance"}, {
        "event": "sensitive_fixture_injected",
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "fields": sorted(canaries),
    }] + [{"event": "gate_result", "gate": key, "result": value} for key, value in gate_sections.items()]
    raw.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in raw_events), encoding="utf-8")
    content = (json.dumps({
        "commit": "a" * 40,
        "acceptance_transaction_sha256": transaction,
        "mode": "real_process", "mock_count": 0, "controlled_canary": True,
        "data_source": "CONTROLLED_CANARY", "real_jd_acceptance": False,
        "source_code_write_count": 0, "production_connection_count": 0,
        "secret_exposure_count": 0,
        **sections,
        "exact_commands": ["run real acceptance"],
        "raw_log_path": str(raw), "raw_log_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
        "sensitive_fixture_path": str(fixture),
        "sensitive_fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        **verified,
    }, sort_keys=True) + "\n").encode()
    evidence.write_bytes(content)
    evidence.chmod(0o600)

    digest = recover_published_process_evidence(
        evidence, head="a" * 40, transaction_sha256=transaction, verified_events=verified,
    )
    assert digest == hashlib.sha256(content).hexdigest()
    assert evidence.with_name(f"{evidence.name}.sha256").is_file()
    assert recover_published_process_evidence(
        evidence, head="a" * 40, transaction_sha256=transaction, verified_events=verified,
    ) == digest
    with pytest.raises(RuntimeError, match="BINDING_MISMATCH"):
        recover_published_process_evidence(
            evidence, head="b" * 40, transaction_sha256=transaction, verified_events=verified,
        )


def test_process_recovery_rejects_two_field_fake_pass(tmp_path):
    from ops.r297_process_acceptance import recover_published_process_evidence

    root = tmp_path / "output"
    root.mkdir(mode=0o700)
    evidence = root / "R297_PROCESS_ACCEPTANCE_EVIDENCE.json"
    evidence.write_text(json.dumps({
        "commit": "a" * 40, "acceptance_transaction_sha256": "1" * 64,
    }), encoding="utf-8")
    evidence.chmod(0o600)
    with pytest.raises(RuntimeError, match="BINDING_MISMATCH"):
        recover_published_process_evidence(
            evidence, head="a" * 40, transaction_sha256="1" * 64,
            verified_events={},
        )


def test_process_reentry_does_not_overwrite_existing_evidence_before_verified_resume(monkeypatch, tmp_path):
    import subprocess
    import sys
    from ops import r297_process_acceptance as process

    output = tmp_path / "output"
    output.mkdir(mode=0o700)
    fixture = output / "R297_SENSITIVE_FIXTURE.json"
    fixture.write_bytes(b'{"fixture":"previous-run"}\n')
    evidence = output / "R297_PROCESS_ACCEPTANCE_EVIDENCE.json"
    evidence.write_bytes(b'{"commit":"previous-run"}\n')
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    monkeypatch.setenv("APP_ENV", "acceptance")
    monkeypatch.setenv("RELEASE_SOURCE_SHA", subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip())
    monkeypatch.setenv("R297_EVIDENCE_NONCE_LEDGER", str(tmp_path / "nonces.json"))
    monkeypatch.setattr(sys, "argv", ["process", str(output), "--runtime-image", "unused", "--signed-event-bundle", str(tmp_path / "bundle")])
    monkeypatch.setattr(process, "free_port", lambda: pytest.fail("reentry reached new canary startup"))
    with pytest.raises(RuntimeError, match="R297_PROCESS_RECOVERY_REQUIRES_VERIFIED_RESUME"):
        process.main()
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before
