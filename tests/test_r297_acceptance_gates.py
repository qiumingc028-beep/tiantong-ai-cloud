"""Blocking acceptance gates for the R297 multi-store sync loop.

These gates intentionally fail when a required cloud or Windows acceptance seam
is absent.  They do not replace missing product behavior with mocks.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from backend.database import Base
from backend.main import app
from backend.models import Store, User, UserStoreMembership


ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop" / "jd-workbench"
FINAL_REVISION = "0050_r297_reliable_sync_queue"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_source_sha() -> str:
    expected = os.getenv("RELEASE_SOURCE_SHA")
    assert expected, "缺少RELEASE_SOURCE_SHA，无法绑定当前验收Checkout"
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    assert expected == actual, "RELEASE_SOURCE_SHA与当前Checkout HEAD不一致"
    return expected


def validate_raw_evidence(evidence: dict, result_sections: tuple[str, ...]) -> None:
    assert evidence["exact_commands"]
    assert all("mock" not in command.lower() for command in evidence["exact_commands"])
    raw_log = Path(evidence["raw_log_path"])
    assert raw_log.is_file()
    assert re.fullmatch(r"[0-9a-f]{64}", evidence["raw_log_sha256"])
    assert sha256(raw_log) == evidence["raw_log_sha256"]
    raw_text = read(raw_log)
    events = [json.loads(line) for line in raw_text.splitlines() if line.strip()]
    commands = [event["command"] for event in events if event.get("event") == "command"]
    assert commands == evidence["exact_commands"]
    raw_results = {
        event["gate"]: event["result"]
        for event in events
        if event.get("event") == "gate_result"
    }
    for section in result_sections:
        assert raw_results[section] == evidence[section]

    fixture = Path(evidence["sensitive_fixture_path"])
    assert fixture.is_file()
    assert sha256(fixture) == evidence["sensitive_fixture_sha256"]
    canaries = json.loads(read(fixture))
    assert set(canaries) == {"buyer_name", "phone", "address", "cookie", "token", "password"}
    injection_events = [
        event for event in events if event.get("event") == "sensitive_fixture_injected"
    ]
    assert injection_events == [{
        "event": "sensitive_fixture_injected",
        "fixture_sha256": evidence["sensitive_fixture_sha256"],
        "fields": sorted(canaries),
    }]
    assert all(value and value not in raw_text for value in canaries.values())
    assert not re.search(
        r"(?i)(?:authorization:\s*(?:bearer|device)\s+\S+|cookie:\s*\S+|"
        r"password\s*[=:]\s*\S+|postgres(?:ql)?://[^/\s]+:[^@\s]+@)",
        raw_text,
    )


def process_acceptance_evidence() -> dict:
    raw_path = os.getenv("R297_PROCESS_ACCEPTANCE_EVIDENCE")
    assert raw_path, "缺少R297_PROCESS_ACCEPTANCE_EVIDENCE真实进程验收证据"
    path = Path(raw_path)
    assert path.is_file()
    evidence = json.loads(read(path))
    assert evidence["commit"] == release_source_sha()
    assert evidence["mode"] == "real_process"
    assert evidence["mock_count"] == 0
    assert evidence["source_code_write_count"] == 0
    validate_raw_evidence(evidence, (
        "web_page_close",
        "electron_exit",
        "worker_restart",
        "multi_worker",
        "retry_schedule",
        "manual_resume",
        "human_action_detection",
        "service_restart",
    ))
    return evidence


def test_r297_operations_and_store_management_return_same_real_store_ids(
    client,
    owner_headers,
    test_db,
):
    db = test_db()
    try:
        owner = db.query(User).filter(User.username == "owner").one()
        stores = [Store(
            tenant_id=owner.tenant_id,
            company_id=owner.company_id,
            platform="jd",
            store_code="R297-SECOND",
            store_name="R297 第二测试店铺",
            active=True,
        ), Store(
            tenant_id=owner.tenant_id,
            company_id=owner.company_id,
            platform="jd",
            store_code="R297-INACTIVE",
            store_name="R297 停用测试店铺",
            active=False,
        ), Store(
            tenant_id=owner.tenant_id,
            company_id=owner.company_id,
            platform="tmall",
            store_code="R297-OTHER",
            store_name="R297 非京东测试店铺",
            active=True,
        )]
        db.add_all(stores)
        db.flush()
        db.add_all([
            UserStoreMembership(
                user_id=owner.id,
                store_id=store.id,
                can_read=True,
                can_write=True,
                active=True,
            )
            for store in stores
        ])
        db.commit()
    finally:
        db.close()

    management = client.get("/api/stores", headers=owner_headers)
    operations = client.get("/api/jd-workbench/dashboard", headers=owner_headers)

    assert management.status_code == 200, management.text
    assert operations.status_code == 200, operations.text
    assert {row["id"] for row in management.json()} == {
        row["store_id"] for row in operations.json()["stores"]
    }


def test_r297_has_one_store_master_no_mock_store_api_or_frontend_store_literals():
    store_master_tables = {
        name
        for name, table in Base.metadata.tables.items()
        if {"tenant_id", "company_id", "platform"}.issubset(table.columns.keys())
        and any(column == "code" or column.endswith("_code") for column in table.columns.keys())
        and any(column == "name" or column.endswith("_name") for column in table.columns.keys())
    }
    assert store_master_tables == {"stores"}

    forbidden_routes = [
        route.path
        for route in app.routes
        if re.search(r"(?:mock|simulate|fake|demo|seed|generate)", route.path, re.IGNORECASE)
        and re.search(r"(?:store|shop)", route.path, re.IGNORECASE)
    ]
    assert forbidden_routes == []

    stores_page = read(ROOT / "frontend" / "stores.html")
    dashboard_page = read(ROOT / "frontend" / "jd-dashboard.html")
    shared_store_view = read(ROOT / "frontend" / "r297-store-view.js")
    assert "/api/stores" in shared_store_view
    for page in (stores_page, dashboard_page):
        assert 'src="/r297-store-view.js"' in page
        assert "R297StoreView." in page
        assert re.search(r"R297StoreView\.loadStoreDirectory\(\s*api\s*\)", page)
        assert "/api/stores" not in page
    assert "function mergeStores(directory, dashboardStores)" in shared_store_view
    assert "id: store.id" in shared_store_view
    assert "store_id: store.id" in shared_store_view
    subprocess.run(
        ["node", "-e", """
(async () => {
const assert = require('node:assert/strict');
const view = require('./frontend/r297-store-view.js');
assert.equal(typeof view.loadStoreDirectory, 'function');
const calls = [];
const directory = await view.loadStoreDirectory(async endpoint => {
  calls.push(endpoint);
  return [{id: 101, store_code: 'REAL-101', platform: 'jd', active: true}];
});
assert.deepEqual(calls, ['/api/stores']);
const merged = view.mergeStores(
  directory,
  [{id: 999, store_id: 101, summary: {}}, {id: 202, store_id: 202, summary: {}}]
);
assert.deepEqual(merged.map(store => [store.id, store.store_id]), [[101, 101]]);
})().catch(error => { console.error(error); process.exit(1); });
"""],
        cwd=ROOT,
        check=True,
    )
    assert "/api/jd-workbench/dashboard?" in dashboard_page
    for page in (stores_page, dashboard_page, shared_store_view):
        assert not re.search(r"(?:store_id|storeId)\s*:\s*[1-9]\d*", page)
        assert not re.search(
            r"(?:stores|allStores|shops|storeRows|STORE_LIST)\s*=\s*\[\s*{",
            page,
        )
        assert not re.search(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            page,
            re.IGNORECASE,
        )


def test_r297_default_sync_interval_is_exactly_300_seconds():
    from backend.routers.jd_workbench import DEFAULT_SYNC_INTERVAL_SECONDS

    scheduler = read(DESKTOP / "auto-sync.js")
    assert DEFAULT_SYNC_INTERVAL_SECONDS == 300
    assert "const DEFAULT_INTERVAL_MS = 5 * 60 * 1000" in scheduler


def test_r297_web_page_close_does_not_own_or_stop_cloud_scheduling():
    result = process_acceptance_evidence()["web_page_close"]
    assert result["closed"] is True
    assert result["cloud_cycles_after"] > result["cloud_cycles_before"]
    assert set(result["collected_store_ids_after"]) == set(result["eligible_store_ids"])


def test_r297_electron_exit_does_not_own_or_stop_cloud_scheduling():
    result = process_acceptance_evidence()["electron_exit"]
    assert result["exited"] is True
    assert result["cloud_cycles_after"] > result["cloud_cycles_before"]
    assert set(result["collected_store_ids_after"]) == set(result["eligible_store_ids"])


def test_r297_cloud_worker_restart_recovers_persisted_due_tasks():
    result = process_acceptance_evidence()["worker_restart"]
    assert result["worker_pid_before"] != result["worker_pid_after"]
    assert result["persisted_due_count_before"] >= 1
    assert result["recovered_due_count"] == result["persisted_due_count_before"]


def test_r297_multiple_workers_claim_each_store_once_atomically():
    result = process_acceptance_evidence()["multi_worker"]
    assert len(set(result["worker_pids"])) >= 2
    assert result["eligible_store_ids"]
    assert sorted(result["collected_store_ids"]) == sorted(result["eligible_store_ids"])
    assert len(result["collected_store_ids"]) == len(set(result["collected_store_ids"]))
    assert result["collection_write_count"] == len(result["eligible_store_ids"])
    assert result["duplicate_collection_count"] == 0


def test_r297_cloud_retry_schedule_is_exact_contract():
    result = process_acceptance_evidence()["retry_schedule"]
    assert result["scheduler"] == "cloud_worker"
    assert result["observed_delays_seconds"] == [30, 120, 300, 900, 1800]
    assert result["attempt_count"] == 5


def test_r297_manual_handling_success_resumes_collection_without_second_trigger():
    result = process_acceptance_evidence()["manual_resume"]
    assert result["human_action_state_observed"] is True
    assert result["manual_handling_completed"] is True
    assert result["completion_signal_source"] == "jd_authenticated_page_observer"
    assert result["resume_trigger"] == "automatic"
    assert result["resume_parent_event_id"]
    assert result["human_completion_event_id"]
    assert result["resume_parent_event_id"] == result["human_completion_event_id"]
    assert result["extra_manual_sync_trigger_count"] == 0
    assert result["collection_count_after"] > result["collection_count_before"]


def test_r297_electron_detects_login_captcha_and_risk_as_human_action_required():
    detections = process_acceptance_evidence()["human_action_detection"]
    assert detections == {
        "LOGIN_EXPIRED": "HUMAN_ACTION_REQUIRED",
        "CAPTCHA_REQUIRED": "HUMAN_ACTION_REQUIRED",
        "RISK_CONTROL": "HUMAN_ACTION_REQUIRED",
    }


def test_r297_real_service_restart_preserves_session_policy_and_status():
    result = process_acceptance_evidence()["service_restart"]
    assert result["service_pid_before"] != result["service_pid_after"]
    assert result["session_fingerprint_before"]
    assert result["policy_fingerprint_before"]
    assert result["status_fingerprint_before"]
    assert result["session_fingerprint_before"] == result["session_fingerprint_after"]
    assert result["policy_fingerprint_before"] == result["policy_fingerprint_after"]
    assert result["status_fingerprint_before"] == result["status_fingerprint_after"]


def test_r297_retry_schedule_is_exact_contract():
    scheduler = read(DESKTOP / "auto-sync.js")
    assert (
        "const RETRY_DELAYS_MS = Object.freeze(["
        "30 * 1000, 2 * 60 * 1000, 5 * 60 * 1000, "
        "15 * 60 * 1000, 30 * 60 * 1000]);"
    ) in scheduler


def _run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env.pop("ALEMBIC_SKIP_SQLITE_DRIFT", None)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_r297_postgresql_upgrade_check_and_downgrade_reupgrade(
    postgres_database_factory,
):
    database_url = postgres_database_factory("r297_replay")
    for args in (
        ("upgrade", "0048_r291_jd_workbench_hybrid_cloud"),
        ("upgrade", "head"),
        ("heads",),
        ("current",),
        ("check",),
        ("downgrade", "0048_r291_jd_workbench_hybrid_cloud"),
        ("upgrade", "head"),
        ("current",),
    ):
        result = _run_alembic(database_url, *args)
        assert result.returncode == 0, f"alembic {' '.join(args)} failed: {result.stderr[-1200:]}"
        if args in {("heads",), ("current",)}:
            assert FINAL_REVISION in result.stdout
        if args == ("heads",):
            head_lines = [line for line in result.stdout.splitlines() if line.strip()]
            assert head_lines == [f"{FINAL_REVISION} (head)"]


def test_r297_windows_installer_and_portable_have_runtime_acceptance_evidence():
    evidence_path = os.getenv("R297_WINDOWS_ACCEPTANCE_EVIDENCE")
    assert evidence_path, (
        "缺少R297_WINDOWS_ACCEPTANCE_EVIDENCE；尚无Windows installer/portable启动、配对、诊断及零写入证据"
    )
    path = Path(evidence_path)
    assert path.is_file()
    evidence = json.loads(read(path))
    assert evidence["commit"] == release_source_sha()
    assert evidence["mode"] == "real_windows_process"
    assert evidence["mock_count"] == 0
    validate_raw_evidence(evidence, ("installer", "portable_zip"))
    for artifact in ("installer", "portable_zip"):
        result = evidence[artifact]
        artifact_path = Path(result["artifact_path"])
        assert artifact_path.is_file()
        assert re.fullmatch(r"[0-9a-f]{64}", result["artifact_sha256"])
        assert sha256(artifact_path) == result["artifact_sha256"]
        assert result["started"] is True
        assert result["paired"] is True
        assert result["diagnostics_visible"] is True
        assert result["jd_write_blocked_count"] >= 1
        assert result["jd_write_success_count"] == 0
        isolation = result["session_isolation"]
        assert isolation["store_ids"][0] != isolation["store_ids"][1]
        assert isolation["cross_read_count"] == 0
        for storage in ("cookie", "local_storage", "indexed_db", "cache"):
            fingerprints = isolation[f"{storage}_fingerprints"]
            assert len(fingerprints) == 2
            assert fingerprints[0] != fingerprints[1]
