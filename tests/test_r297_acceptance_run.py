from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json

import pytest

from ops.r297_acceptance_run import consume_acceptance_run, issue_acceptance_run, main, validate_acceptance_run


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
