from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from ops.r297_acceptance_run import (
    complete_acceptance_run, consume_acceptance_run, issue_acceptance_run, main,
    reserve_acceptance_run, validate_acceptance_run,
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
    assert source.index("reserve_acceptance_run(") < source.index("verify_acceptance_event_bundle(")
    assert source.index("verify_acceptance_event_bundle(") < source.index("write_sha256_bound_file(evidence")
    assert source.index("write_sha256_bound_file(evidence") < source.rindex("complete_acceptance_run(")
    assert "allow_nonce_recovery=reservation == \"recovering\"" in source


def test_process_evidence_recovers_body_only_and_completed_publication(tmp_path):
    from ops.r297_process_acceptance import recover_published_process_evidence

    root = tmp_path / "output"
    root.mkdir(mode=0o700)
    evidence = root / "R297_PROCESS_ACCEPTANCE_EVIDENCE.json"
    transaction = "1" * 64
    content = (json.dumps({
        "commit": "a" * 40,
        "acceptance_transaction_sha256": transaction,
    }, sort_keys=True) + "\n").encode()
    evidence.write_bytes(content)
    evidence.chmod(0o600)

    digest = recover_published_process_evidence(
        evidence, head="a" * 40, transaction_sha256=transaction,
    )
    assert digest == hashlib.sha256(content).hexdigest()
    assert evidence.with_name(f"{evidence.name}.sha256").is_file()
    assert recover_published_process_evidence(
        evidence, head="a" * 40, transaction_sha256=transaction,
    ) == digest
    with pytest.raises(RuntimeError, match="BINDING_MISMATCH"):
        recover_published_process_evidence(
            evidence, head="b" * 40, transaction_sha256=transaction,
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
