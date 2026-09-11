"""Execute every collected test and verify its JUnit result, without a stale total."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from os import fsync as _progress_fsync
from pathlib import Path
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from ops.r297_ci_redact import _redact_text, redact

_OUTCOMES: dict[str, str] = {}
_NODE_IDENTITIES: dict[str, str] = {}
_OUTCOME_PRIORITY = {"passed": 0, "skipped": 1, "failed": 2}
_PROGRESS_ROOT: Path | None = None
_LOCAL_IDENTITY_KEY = b"r297-local-pytest-identity-only"
_PROCESS_TERM_GRACE_SECONDS = 5.0
_SUPERVISOR_TIMEOUTS = {"main": 75 * 60.0, "ownership": 75 * 60.0, "aggregate": 10 * 60.0}
_PARTITION_FILES = {
    "collected-nodeids.json", "collected-nodeids.display.json", "junit.xml",
    "progress.jsonl", "pytest.log", "run.json", "status.json",
}
_AGGREGATE_FILES = {
    "aggregate.json", "collection.log", "full-collected-nodeids.json",
    "full-collected-nodeids.display.json", "processes.json",
}


def _progress_path(name: str) -> Path | None:
    return _PROGRESS_ROOT / name if _PROGRESS_ROOT is not None else None


def _node_identities(nodes: list[str]) -> list[str]:
    raw = os.getenv("CI_PYTEST_IDENTITY_KEY")
    if os.getenv("GITHUB_ACTIONS") == "true" and (raw is None or len(raw) < 43):
        raise RuntimeError("CI_PYTEST_IDENTITY_KEY_MISSING")
    key = raw.encode() if raw is not None else _LOCAL_IDENTITY_KEY
    return [hmac.new(key, node.encode(), hashlib.sha256).hexdigest() for node in nodes]


def _write_status(**updates) -> None:
    path = _progress_path("status.json")
    if path is None:
        return
    value = {}
    if path.exists():
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
    value.update(updates, updated_at=datetime.now(timezone.utc).isoformat())
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _append_progress(value: dict) -> None:
    path = _progress_path("progress.jsonl")
    if path is None:
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        with os.fdopen(descriptor, "a", encoding="utf-8", closefd=False) as stream:
            stream.write(json.dumps(value, sort_keys=True) + "\n")
            stream.flush()
            _progress_fsync(stream.fileno())
    finally:
        os.close(descriptor)


def pytest_sessionstart(session):
    global _PROGRESS_ROOT
    root = os.getenv("CI_PYTEST_PROGRESS_DIRECTORY")
    _PROGRESS_ROOT = Path(root) if root else None
    _OUTCOMES.clear()
    _NODE_IDENTITIES.clear()
    _write_status(result="INCOMPLETE", phase="executing", last_completed_test=None)


def pytest_collection_finish(session):
    target = os.getenv("CI_PYTEST_COLLECTION_MANIFEST")
    if target:
        nodes = [item.nodeid for item in session.items]
        identities = _node_identities(nodes)
        _NODE_IDENTITIES.update(zip(nodes, identities))
        Path(target).write_text(json.dumps(identities), encoding="utf-8")
        Path(target).with_suffix(".display.json").write_text(json.dumps([
            {"nodeid_sha256": identity, "nodeid": _redact_text(node)}
            for identity, node in zip(identities, nodes)
        ]), encoding="utf-8")
    _write_status(collected=len(session.items))


def pytest_runtest_logstart(nodeid, location):
    _write_status(current_test=_redact_text(nodeid), current_phase="setup")


def pytest_runtest_call(item):
    _write_status(current_test=_redact_text(item.nodeid), current_phase="call")


def pytest_runtest_teardown(item, nextitem):
    _write_status(current_test=_redact_text(item.nodeid), current_phase="teardown")


def pytest_runtest_logreport(report):
    nodeid = _redact_text(report.nodeid)
    identity = _NODE_IDENTITIES.get(report.nodeid)
    if identity is None:
        identity = _node_identities([report.nodeid])[0]
    previous = _OUTCOMES.get(nodeid, "passed")
    if _OUTCOME_PRIORITY.get(report.outcome, 2) >= _OUTCOME_PRIORITY.get(previous, 0):
        _OUTCOMES[nodeid] = report.outcome
    _append_progress({
        "nodeid": nodeid, "outcome": report.outcome, "phase": report.when,
        "nodeid_sha256": identity,
        "duration_seconds": round(report.duration, 6),
    })
    if report.when == "teardown":
        _write_status(
            last_completed_test=nodeid, last_outcome=_OUTCOMES.pop(nodeid, report.outcome),
            current_test=None, current_phase=None,
        )


def pytest_sessionfinish(session, exitstatus):
    _write_status(result="COMPLETE", phase="finished", exitstatus=int(exitstatus), current_test=None)


def validate_report(report: Path, manifest: Path, *, minimum: int = 1846) -> dict:
    nodes = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(nodes, list) or len(nodes) < minimum or len(set(nodes)) != len(nodes):
        raise ValueError("PYTEST_COLLECTION_INCOMPLETE")
    root = ET.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    totals = {key: sum(int(s.attrib.get(key, "0")) for s in suites)
              for key in ("tests", "failures", "errors", "skipped")}
    if totals["tests"] != len(nodes):
        raise ValueError("PYTEST_EXECUTION_DOES_NOT_MATCH_COLLECTION")
    if any(totals[key] for key in ("failures", "errors", "skipped")):
        raise ValueError("PYTEST_NOT_ALL_PASS")
    return totals


def validate_partition_output(output: Path, *, head: str, run_id: str, run_attempt: str,
                              minimum: int, published: bool = True) -> list[str]:
    if published:
        _validate_publication(
            output, head=head, run_id=run_id, run_attempt=run_attempt,
            qualifying_stage="ownership",
        )
    expected = {"head": head, "run_id": run_id, "run_attempt": run_attempt, "exit_code": 0}
    run = json.loads((output / "run.json").read_text(encoding="utf-8"))
    if not isinstance(run, dict) or any(type(run.get(key)) is not type(value) or run.get(key) != value
                                        for key, value in expected.items()):
        raise ValueError("PYTEST_PARTITION_RUN_MISMATCH_OR_FAILED")
    status = json.loads((output / "status.json").read_text(encoding="utf-8"))
    if not isinstance(status, dict) or status.get("result") != "COMPLETE" or type(status.get("exitstatus")) is not int or status.get("exitstatus") != 0:
        raise ValueError("PYTEST_PARTITION_INCOMPLETE")
    manifest = output / "collected-nodeids.json"
    validate_report(output / "junit.xml", manifest, minimum=minimum)
    nodes = json.loads(manifest.read_text(encoding="utf-8"))
    if any(not isinstance(node, str) or not re.fullmatch(r"[0-9a-f]{64}", node) for node in nodes):
        raise ValueError("PYTEST_PARTITION_COLLECTION_INVALID")
    progress = [json.loads(line) for line in (output / "progress.jsonl").read_text(encoding="utf-8").splitlines()]
    executed = [row.get("nodeid_sha256") for row in progress if row.get("phase") == "teardown"]
    if sorted(executed) != sorted(nodes):
        raise ValueError("PYTEST_EXECUTED_NODEIDS_MISMATCH")
    return nodes


def validate_partitions(full_manifest: Path, outputs: list[Path], *, head: str, run_id: str, run_attempt: str) -> dict:
    """Require two successful, disjoint executions of the independently collected tree."""
    full = json.loads(full_manifest.read_text(encoding="utf-8"))
    if (not re.fullmatch(r"[0-9a-f]{40}", head) or len(outputs) != 2
        or not isinstance(full, list) or not full or any(not isinstance(node, str) or not re.fullmatch(r"[0-9a-f]{64}", node) for node in full)
        or len(full) != len(set(full))):
        raise ValueError("PYTEST_FULL_COLLECTION_INVALID")
    combined = set()
    for output in outputs:
        nodes = validate_partition_output(
            output, head=head, run_id=run_id, run_attempt=run_attempt, minimum=1, published=False,
        )
        if combined.intersection(nodes):
            raise ValueError("PYTEST_PARTITION_OVERLAP")
        combined.update(nodes)
    if combined != set(full):
        raise ValueError("PYTEST_PARTITION_UNION_MISMATCH")
    return {"collected": len(full), "executed": len(combined), "overlap": 0, "missing": 0}


def validate_aggregate_output(output: Path, *, head: str, run_id: str, run_attempt: str,
                              published: bool = True) -> dict:
    if published:
        _validate_publication(output, head=head, run_id=run_id, run_attempt=run_attempt)
    result = json.loads((output / "aggregate.json").read_text(encoding="utf-8"))
    expected = {"head": head, "run_id": run_id, "run_attempt": run_attempt, "result": "PASS"}
    if not isinstance(result, dict) or any(result.get(key) != value for key, value in expected.items()):
        raise ValueError("PYTEST_AGGREGATE_IDENTITY_OR_RESULT_INVALID")
    counts = {key: result.get(key) for key in ("collected", "executed", "overlap", "missing")}
    if (any(type(value) is not int for value in counts.values()) or counts["collected"] < 1
        or counts["collected"] != counts["executed"] or counts["overlap"] != 0 or counts["missing"] != 0):
        raise ValueError("PYTEST_AGGREGATE_COVERAGE_INVALID")
    return result


def _read_publication(output: Path) -> dict:
    try:
        publication = json.loads((output / "publication.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("PYTEST_PUBLICATION_INVALID") from exc
    if not isinstance(publication, dict):
        raise ValueError("PYTEST_PUBLICATION_INVALID")
    return publication


def _validate_publication(output: Path, *, head: str, run_id: str, run_attempt: str,
                          qualifying_stage: str | None = None) -> None:
    publication = _read_publication(output)
    expected = {"head": head, "run_id": run_id, "run_attempt": run_attempt}
    exits = publication.get("stage_exit_codes")
    exits_valid = (
        isinstance(exits, dict) and set(exits) == {"main", "ownership", "aggregate"}
        and all(value is None or type(value) is int for value in exits.values())
    )
    primary_error = publication.get("primary_error")
    stage_error_consistent = True
    if isinstance(primary_error, str):
        for stage in ("main", "ownership", "aggregate"):
            if primary_error.startswith(f"PYTEST_{stage.upper()}_"):
                stage_exit = exits.get(stage) if exits_valid else None
                if primary_error == f"PYTEST_{stage.upper()}_TIMEOUT":
                    stage_error_consistent = exits_valid and stage_exit is None
                elif primary_error == f"PYTEST_{stage.upper()}_FAILED":
                    stage_error_consistent = exits_valid and type(stage_exit) is int and stage_exit != 0
                else:
                    stage_error_consistent = False
    stage_qualified = (
        qualifying_stage is not None
        and publication.get("result") == publication.get("artifact_result") == "BLOCK"
        and exits_valid and exits.get(qualifying_stage) == 0
        and any(value != 0 for name, value in exits.items() if name != qualifying_stage)
        and isinstance(publication.get("primary_error"), str)
        and publication.get("error") == publication.get("primary_error")
        and re.fullmatch(r"(?:CI_)?PYTEST_[A-Z_]+", publication["primary_error"])
        and not publication["primary_error"].startswith(f"PYTEST_{qualifying_stage.upper()}_")
        and stage_error_consistent
        and publication.get("cleanup_error") is None
        and publication.get("publication_error") is None
    )
    if (any(publication.get(key) != value for key, value in expected.items())
        or (publication.get("result") != "PASS" and not stage_qualified)
        or (publication.get("artifact_result") != "PASS" and not stage_qualified)
        or (publication.get("primary_error") is not None and not stage_qualified)
        or any(publication.get(key) is not None for key in ("cleanup_error", "publication_error"))
        or not exits_valid
        or (not stage_qualified and any(type(value) is not int or value != 0 for value in exits.values()))):
        raise ValueError("PYTEST_PUBLICATION_INVALID")


def validate_publication_outputs(outputs: list[Path], *, head: str, run_id: str, run_attempt: str) -> None:
    if len(outputs) != 3:
        raise ValueError("PYTEST_PUBLICATION_INVALID")
    specs = (
        (outputs[0], _PARTITION_FILES),
        (outputs[1], _PARTITION_FILES),
        (outputs[2], _AGGREGATE_FILES),
    )
    publications = []
    for output, allowed in specs:
        publication = _read_publication(output)
        expected = {"head": head, "run_id": run_id, "run_attempt": run_attempt}
        if (publication.get("result") not in {"PASS", "BLOCK"}
            or publication.get("artifact_result") != publication.get("result")
            or any(publication.get(key) != value for key, value in expected.items())
            or not {path.name for path in output.iterdir()}.issubset(allowed | {"publication.json"})):
            raise ValueError("PYTEST_PUBLICATION_INVALID")
        for key in ("primary_error", "cleanup_error", "publication_error"):
            value = publication.get(key)
            if value is not None and not re.fullmatch(r"(?:CI_)?PYTEST_[A-Z_]+", value):
                raise ValueError("PYTEST_PUBLICATION_INVALID")
        exits = publication.get("stage_exit_codes")
        if (not isinstance(exits, dict) or set(exits) != {"main", "ownership", "aggregate"}
            or any(value is not None and type(value) is not int for value in exits.values())):
            raise ValueError("PYTEST_PUBLICATION_INVALID")
        if publication.get("result") == "PASS" and (
            any(publication.get(key) is not None for key in ("primary_error", "cleanup_error", "publication_error"))
            or any(type(value) is not int or value != 0 for value in exits.values())
        ):
            raise ValueError("PYTEST_PUBLICATION_INVALID")
        if (publication.get("cleanup_error") or publication.get("publication_error")) and {
            path.name for path in output.iterdir()
        } != {"publication.json"}:
            raise ValueError("PYTEST_PUBLICATION_UNSAFE_BLOCK")
        publications.append(publication)
    if any(publication != publications[0] for publication in publications[1:]):
        raise ValueError("PYTEST_PUBLICATION_STATE_MISMATCH")
    _scan_identity_key(outputs)


def _run_identity() -> dict:
    return {"head": os.getenv("RELEASE_SOURCE_SHA", ""),
            "run_id": os.getenv("GITHUB_RUN_ID", "local"),
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "1")}


def _partition_environments(cache_root: Path) -> tuple[dict, dict, dict]:
    base = dict(os.environ)
    # Only the supervisor may write step outputs; test subprocesses are untrusted.
    base.pop("GITHUB_OUTPUT", None)
    main = dict(base, V2_ALPHA_POSTGRES_ADMIN_URL="postgresql+psycopg2://ci:ci@127.0.0.1:5432/postgres",
                STORE_AUTHZ_POSTGRES_URL="postgresql+psycopg2://ci:ci@127.0.0.1:5432/postgres",
                REDIS_URL="redis://127.0.0.1:6379/0",
                CI_PYTEST_IGNORE="tests/test_task_center_full_entrypoint_ownership.py",
                CI_PYTEST_MINIMUM="1700", CI_PYTEST_CACHE_DIR=str(cache_root / "main"))
    main.pop("CI_PYTEST_TARGET", None)
    ownership = dict(base, V2_ALPHA_POSTGRES_ADMIN_URL="postgresql+psycopg2://ci:ci@127.0.0.1:5433/postgres",
                     STORE_AUTHZ_POSTGRES_URL="postgresql+psycopg2://ci:ci@127.0.0.1:5433/postgres",
                     REDIS_URL="redis://127.0.0.1:6380/0",
                     CI_PYTEST_TARGET="tests/test_task_center_full_entrypoint_ownership.py",
                     CI_PYTEST_MINIMUM="500", CI_PYTEST_CACHE_DIR=str(cache_root / "ownership"))
    ownership.pop("CI_PYTEST_IGNORE", None)
    aggregate = dict(base, CI_PYTEST_CACHE_DIR=str(cache_root / "aggregate"))
    for name in ("CI_PYTEST_TARGET", "CI_PYTEST_IGNORE", "CI_PYTEST_MINIMUM"):
        aggregate.pop(name, None)
    return main, ownership, aggregate


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _terminate_processes(records: list[dict], *, grace_seconds: float = 5.0) -> None:
    active = [record for record in records if not record.get("reaped")]
    verified = []
    reap_error = None
    for record in active:
        running = record["process"].poll() is None
        expected_identity = record.get("process_identity")
        current_identity = _process_identity(record["pid"])
        same_process = (expected_identity is not None and current_identity is not None
                        and expected_identity == current_identity)
        if running and same_process:
            verified.append(record)
        elif _group_alive(record["pgid"]):
            reap_error = reap_error or RuntimeError("PYTEST_PROCESS_REAP_FAILED")
        else:
            try:
                record["process"].wait(timeout=1)
            except subprocess.TimeoutExpired:
                reap_error = reap_error or RuntimeError("PYTEST_PROCESS_REAP_FAILED")
            record["reaped"] = True
    for record in verified:
        if _group_alive(record["pgid"]):
            try:
                os.killpg(record["pgid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + grace_seconds
    while any(_group_alive(record["pgid"]) for record in verified) and time.monotonic() < deadline:
        for record in verified:
            record["process"].poll()
        time.sleep(0.02)
    for record in verified:
        record["process"].poll()
    for record in verified:
        if _group_alive(record["pgid"]):
            try:
                os.killpg(record["pgid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
    for record in verified:
        try:
            record["process"].wait(timeout=1)
        except subprocess.TimeoutExpired:
            reap_error = reap_error or RuntimeError("PYTEST_PROCESS_REAP_FAILED")
    deadline = time.monotonic() + 1.0
    while any(_group_alive(record["pgid"]) for record in verified) and time.monotonic() < deadline:
        time.sleep(0.02)
    for record in verified:
        if _group_alive(record["pgid"]):
            reap_error = reap_error or RuntimeError("PYTEST_PROCESS_REAP_FAILED")
        else:
            record["reaped"] = True
    if reap_error is not None:
        raise reap_error


class _SupervisorFailure(Exception):
    pass


def _first_stage_failure(records: list[dict]) -> str | None:
    failed = [record for record in records if record["process"].poll() not in (None, 0)]
    if not failed:
        return None
    first = min(failed, key=lambda record: record.get("finished_at", float("inf")))
    return f"PYTEST_{first['name'].upper()}_FAILED"


def _wait_managed(records: list[dict], timeouts: dict[str, float]) -> list[int]:
    while True:
        exits = [record["process"].poll() for record in records]
        now = time.monotonic()
        for record, exit_code in zip(records, exits):
            if exit_code is not None and "finished_at" not in record:
                record["finished_at"] = now
        if all(value is not None for value in exits):
            return [int(value) for value in exits]
        for record, exit_code in zip(records, exits):
            if exit_code is None and now - record["started_at"] >= timeouts[record["name"]]:
                if failure := _first_stage_failure(records):
                    raise _SupervisorFailure(failure)
                raise _SupervisorFailure(f"PYTEST_{record['name'].upper()}_TIMEOUT")
        time.sleep(0.05)


def _write_process_state(path: Path, records: list[dict], phase: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"phase": phase, "processes": [
        {"name": record["name"], "pid": record["pid"], "pgid": record["pgid"],
         "exit_code": record["process"].poll()} for record in records
    ]}
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _scan_identity_key(outputs: list[Path]) -> None:
    value = os.environ.get("CI_PYTEST_IDENTITY_KEY", "")
    if len(value) < 43:
        raise RuntimeError("CI_PYTEST_IDENTITY_KEY_MISSING")
    raw = value.encode()
    hex_value = raw.hex().encode()
    needles = (raw, base64.b64encode(raw), hex_value, hex_value.upper())
    for output in outputs:
        for path in output.rglob("*"):
            if path.is_file() and any(needle in path.read_bytes() for needle in needles):
                raise RuntimeError("CI_PYTEST_IDENTITY_ARTIFACT_LEAK")


def _error_code(exc: BaseException) -> str:
    value = str(exc)
    if re.fullmatch(r"(?:CI_)?PYTEST_[A-Z_]+", value):
        return value
    if isinstance(exc, OSError):
        return "PYTEST_SUPERVISOR_OS_ERROR"
    return "PYTEST_SUPERVISOR_INTERNAL_ERROR"


def _stable_file_bytes(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError("PYTEST_ARTIFACT_NOT_REGULAR")
        chunks = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_size, value.st_mtime_ns)
    if identity(before) != identity(after) or sum(map(len, chunks)) != before.st_size:
        raise RuntimeError("PYTEST_ARTIFACT_UNSTABLE")
    return b"".join(chunks)


def _process_identity(pid: int) -> str | None:
    try:
        value = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return value[value.rfind(")") + 2:].split()[19]
    except (OSError, IndexError):
        return None


def _publication_payload(identity: dict, result: str, primary_error: str | None,
                         cleanup_error: str | None, publication_error: str | None,
                         stage_exit_codes: dict[str, int | None]) -> dict:
    return {
        **identity, "result": result, "artifact_result": result,
        "primary_error": primary_error, "error": primary_error or publication_error,
        "cleanup_error": cleanup_error, "publication_error": publication_error,
        "stage_exit_codes": stage_exit_codes,
    }


def publish_outputs(specs: list[tuple[Path, Path, set[str]]], *, identity: dict, result: str,
                    primary_error: str | None, cleanup_error: str | None,
                    stage_exit_codes: dict[str, int | None], atomic_root: Path | None = None) -> str:
    """Publish only stable, scanned files after all writers have stopped."""
    key = os.environ.get("CI_PYTEST_IDENTITY_KEY", "")
    scan_error = None
    staged: list[tuple[Path, Path]] = []
    targets = [target for _, target, _ in specs]
    shared_target_root = atomic_root
    if shared_target_root is not None and (
        len(targets) < 2 or any(target.parent != shared_target_root for target in targets)
    ):
        raise ValueError("PYTEST_PUBLISH_ATOMIC_ROOT_INVALID")
    shared_stage_root = None
    shared_target_preexisting = False
    try:
        if cleanup_error:
            raise RuntimeError("PYTEST_PUBLICATION_REAP_UNPROVEN")
        if len(key) < 43:
            raise RuntimeError("CI_PYTEST_IDENTITY_KEY_MISSING")
        _scan_identity_key([source for source, _, _ in specs])
        raw = key.encode()
        hex_value = raw.hex().encode()
        needles = (raw, base64.b64encode(raw), hex_value, hex_value.upper())
        if shared_target_root is not None:
            if shared_target_root.exists() or shared_target_root.is_symlink():
                shared_target_preexisting = True
                raise RuntimeError("PYTEST_PUBLISH_TARGET_NOT_FRESH")
            shared_stage_root = Path(tempfile.mkdtemp(
                prefix=f".{shared_target_root.name}.", dir=shared_target_root.parent,
            ))
        for source, target, allowed in specs:
            if target.exists():
                raise RuntimeError("PYTEST_PUBLISH_TARGET_NOT_FRESH")
            source_names = {path.name for path in source.iterdir()}
            if not source_names.issubset(allowed):
                raise RuntimeError("PYTEST_ARTIFACT_FILE_SET_INVALID")
            if shared_stage_root is not None:
                stage = shared_stage_root / target.name
                stage.mkdir()
            else:
                stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
            staged.append((stage, target))
            for name in sorted(source_names):
                payload = _stable_file_bytes(source / name)
                if any(needle in payload for needle in needles):
                    raise RuntimeError("CI_PYTEST_IDENTITY_ARTIFACT_LEAK")
                (stage / name).write_bytes(payload)
        final_result = "PASS" if result == "PASS" and not primary_error and not cleanup_error else "BLOCK"
        payload = _publication_payload(identity, final_result, primary_error, cleanup_error, None, stage_exit_codes)
        for stage, _ in staged:
            (stage / "publication.json").write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        if shared_stage_root is not None:
            os.replace(shared_stage_root, shared_target_root)
        else:
            for stage, target in staged:
                os.replace(stage, target)
    except (OSError, RuntimeError) as exc:
        scan_error = _error_code(exc)
        if shared_stage_root is not None:
            shutil.rmtree(shared_stage_root, ignore_errors=True)
        else:
            for stage, _ in staged:
                shutil.rmtree(stage, ignore_errors=True)
    else:
        return final_result
    payload = _publication_payload(identity, "BLOCK", primary_error or scan_error, cleanup_error,
                                   scan_error, stage_exit_codes)
    if shared_target_preexisting:
        return "UNPUBLISHABLE"
    for _, target, _ in specs:
        try:
            target.mkdir(parents=True, exist_ok=False)
            (target / "publication.json").write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        except OSError:
            pass
    return "UNPUBLISHABLE"


class _SignalExit(Exception):
    def __init__(self, signum: int):
        self.signum = signum


def _terminate_new_process_group(process: subprocess.Popen, *, grace_seconds: float = 1.0) -> None:
    """Reap a just-created session before its leader PID can be reused."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + grace_seconds
    while _group_alive(process.pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    if _group_alive(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        raise _SupervisorFailure("PYTEST_PROCESS_REAP_FAILED")


def _start_managed_process(name: str, command: list[str], environment: dict, records: list[dict]) -> dict:
    deferred: list[int] = []
    previous_handlers = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}

    def defer(signum, _frame):
        deferred.append(signum)

    try:
        for signum in previous_handlers:
            signal.signal(signum, defer)
        process = subprocess.Popen(command, env=environment, start_new_session=True)
        process_identity = _process_identity(process.pid)
        if process_identity is None:
            _terminate_new_process_group(process)
            raise _SupervisorFailure("PYTEST_PROCESS_IDENTITY_UNAVAILABLE")
        record = {"name": name, "process": process, "pid": process.pid, "pgid": process.pid,
                  "process_identity": process_identity, "started_at": time.monotonic()}
        records.append(record)
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    if deferred:
        raise _SignalExit(deferred[0])
    return record


def _partitions_main() -> int:
    main_output, ownership_output, aggregate_output = map(Path, sys.argv[2:5])
    explicit_publish = len(sys.argv) >= 9 and sys.argv[5] == "--publish"
    if explicit_publish:
        publish_main, publish_ownership, publish_aggregate = map(Path, sys.argv[6:9])
    else:
        publish_main, publish_ownership, publish_aggregate = (
            output.with_name(output.name + "-publish")
            for output in (main_output, ownership_output, aggregate_output)
        )
    process_state = aggregate_output / "processes.json"
    records: list[dict] = []
    previous_handlers = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}

    def interrupted(signum, _frame):
        raise _SignalExit(signum)

    for signum in previous_handlers:
        signal.signal(signum, interrupted)
    result = 1
    phase = "failed"
    primary_error = None
    cleanup_error = None
    stage_exits = {"main": None, "ownership": None, "aggregate": None}
    cache_directory = None
    try:
        cache_directory = tempfile.TemporaryDirectory(prefix="r297-pytest-caches-")
        main_env, ownership_env, aggregate_env = _partition_environments(Path(cache_directory.name))
        for name, output, environment in (
            ("main", main_output, main_env), ("ownership", ownership_output, ownership_env),
        ):
            _start_managed_process(
                name,
                [sys.executable, "-m", "ops.ci_pytest_gate", str(output)],
                environment,
                records,
            )
            _write_process_state(process_state, records, "running")
        exits = _wait_managed(records, _SUPERVISOR_TIMEOUTS)
        stage_exits.update(main=exits[0], ownership=exits[1])
        primary_error = _first_stage_failure(records)
        try:
            _terminate_processes(records, grace_seconds=_PROCESS_TERM_GRACE_SECONDS)
        except Exception as exc:
            cleanup_error = cleanup_error or _error_code(exc)
            raise
        aggregate_env.update(
            CI_MAIN_JOB_RESULT="success" if exits[0] == 0 else "failure",
            CI_MATRIX_JOB_RESULT="success" if exits[1] == 0 else "failure",
        )
        aggregate_record = _start_managed_process(
            "aggregate",
            [sys.executable, "-m", "ops.ci_pytest_gate", "--aggregate", str(aggregate_output),
             str(main_output), str(ownership_output)],
            aggregate_env,
            records,
        )
        _write_process_state(process_state, records, "aggregating")
        aggregate_exit = _wait_managed([aggregate_record], _SUPERVISOR_TIMEOUTS)[0]
        stage_exits["aggregate"] = aggregate_exit
        result = 0 if exits == [0, 0] and aggregate_exit == 0 else 1
        if result:
            primary_error = primary_error or _first_stage_failure(records)
        phase = "complete"
    except _SignalExit as exc:
        result = 128 + exc.signum
        primary_error = primary_error or _first_stage_failure(records) or "PYTEST_SUPERVISOR_CANCELLED"
        phase = "cancelled"
    except (OSError, RuntimeError, _SupervisorFailure) as exc:
        primary_error = primary_error or _error_code(exc)
        result = 1
        phase = "failed"
    finally:
        try:
            for signum in previous_handlers:
                signal.signal(signum, signal.SIG_IGN)
            for cleanup in (
                lambda: _terminate_processes(records, grace_seconds=_PROCESS_TERM_GRACE_SECONDS),
                lambda: cache_directory.cleanup() if cache_directory is not None else None,
                lambda: _write_process_state(process_state, records, phase),
            ):
                try:
                    cleanup()
                except Exception as exc:
                    cleanup_error = cleanup_error or _error_code(exc)
                    phase = "cleanup_failed"
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
    for record in records:
        stage_exits[record["name"]] = record["process"].poll()
    if result == 0 and cleanup_error is None:
        try:
            totals = validate_partitions(
                aggregate_output / "full-collected-nodeids.json",
                [main_output, ownership_output], **_run_identity(),
            )
            aggregate = validate_aggregate_output(
                aggregate_output, published=False, **_run_identity(),
            )
            if any(aggregate.get(key) != value for key, value in totals.items()):
                raise ValueError("PYTEST_AGGREGATE_COVERAGE_INVALID")
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
            primary_error = _error_code(exc)
            result = 1
    try:
        final = publish_outputs(
            [
                (main_output, publish_main, _PARTITION_FILES),
                (ownership_output, publish_ownership, _PARTITION_FILES),
                (aggregate_output, publish_aggregate, _AGGREGATE_FILES),
            ],
            identity=_run_identity(), result="PASS" if result == 0 else "BLOCK",
            primary_error=primary_error, cleanup_error=cleanup_error, stage_exit_codes=stage_exits,
            atomic_root=publish_main.parent if explicit_publish else None,
        )
        if final != "UNPUBLISHABLE":
            validate_publication_outputs(
                [publish_main, publish_ownership, publish_aggregate], **_run_identity(),
            )
        output_path = os.getenv("GITHUB_OUTPUT")
        if output_path:
            with open(output_path, "a", encoding="utf-8") as stream:
                stream.write(f"publication_ready={'true' if final != 'UNPUBLISHABLE' else 'false'}\n")
    except Exception:
        print("CI_PYTEST_SUPERVISOR=BLOCK (PYTEST_PUBLICATION_FAILED)")
        return 1
    return 0 if final == "PASS" else result or 1


def _validation_main(kind: str) -> int:
    identity = _run_identity()
    try:
        if kind == "--validate-publication":
            validate_publication_outputs([Path(path) for path in sys.argv[2:5]], **identity)
        elif kind == "--validate-partition":
            validate_partition_output(Path(sys.argv[2]), minimum=int(sys.argv[3]), **identity)
        else:
            validate_aggregate_output(Path(sys.argv[2]), **identity)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        code = str(exc) if re.fullmatch(r"PYTEST_[A-Z_]+", str(exc)) else type(exc).__name__
        print(f"CI_PYTEST_VALIDATION=BLOCK ({code})")
        return 1
    print("CI_PYTEST_VALIDATION=PASS")
    return 0


def _aggregate_main() -> int:
    # Checkout is pinned by the workflow; collect all tests again, without either
    # partition's selection. Failed/cancelled dependencies can never yield PASS.
    output = Path(sys.argv[2])
    output.mkdir(parents=True, exist_ok=True)
    identity = _run_identity()
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        if head != identity["head"]:
            raise ValueError("PYTEST_CHECKOUT_HEAD_MISMATCH")
        manifest = output / "full-collected-nodeids.json"
        env = dict(os.environ, CI_PYTEST_COLLECTION_MANIFEST=str(manifest))
        env.pop("CI_PYTEST_PROGRESS_DIRECTORY", None)
        command = [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q",
                   "-p", "ops.ci_pytest_gate"]
        if cache_directory := os.getenv("CI_PYTEST_CACHE_DIR"):
            command.extend(["-o", f"cache_dir={cache_directory}"])
        result = subprocess.run(command, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (output / "collection.log").write_text(_redact_text(result.stdout), encoding="utf-8")
        if result.returncode != 0:
            raise ValueError("PYTEST_FULL_COLLECTION_FAILED")
        totals = validate_partitions(manifest, [Path(path) for path in sys.argv[3:]], **identity)
        if os.getenv("CI_MAIN_JOB_RESULT") != "success" or os.getenv("CI_MATRIX_JOB_RESULT") != "success":
            raise ValueError("PYTEST_DEPENDENCY_NOT_SUCCESS")
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, subprocess.SubprocessError) as exc:
        code = str(exc) if re.fullmatch(r"PYTEST_[A-Z_]+", str(exc)) else type(exc).__name__
        (output / "aggregate.json").write_text(json.dumps({**identity, "result": "BLOCK", "error": code}) + "\n")
        print("CI_PYTEST_AGGREGATE=BLOCK (" + code + ")")
        return 1
    (output / "aggregate.json").write_text(json.dumps({**identity, "result": "PASS", **totals}) + "\n")
    print("CI_PYTEST_AGGREGATE=" + json.dumps(totals, sort_keys=True))
    return 0


def main() -> int:
    if sys.argv[1] == "--partitions":
        return _partitions_main()
    if sys.argv[1] in {"--validate-publication", "--validate-partition", "--validate-aggregate"}:
        return _validation_main(sys.argv[1])
    if sys.argv[1] == "--aggregate":
        return _aggregate_main()
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("PYTEST_OUTPUT_MUST_BE_FRESH")
    identity = _run_identity()
    (output / "run.json").write_text(json.dumps({**identity, "exit_code": None}) + "\n")
    manifest = output / "collected-nodeids.json"
    report = output / "junit.xml"
    env = dict(
        os.environ,
        CI_PYTEST_COLLECTION_MANIFEST=str(manifest),
        CI_PYTEST_PROGRESS_DIRECTORY=str(output),
    )
    target = os.getenv("CI_PYTEST_TARGET", "tests/")
    ignored = os.getenv("CI_PYTEST_IGNORE", "")
    allowed_matrix = "tests/test_task_center_full_entrypoint_ownership.py"
    if target not in {"tests/", allowed_matrix} or ignored not in {"", allowed_matrix}:
        raise RuntimeError("CI_PYTEST_SELECTION_INVALID")
    print("CI_PYTEST_STARTED=ALL_COLLECTED_TESTS", flush=True)
    # Failure tracebacks can include credentials. Do not send raw subprocess
    # output to Actions; sanitize it before either logging or artifact upload.
    # The raw JUnit file is outside the upload directory, including if a job is
    # cancelled before pytest finishes. Only a sanitized copy may be published.
    with tempfile.TemporaryDirectory(prefix="r297-ci-pytest-") as raw_directory:
        raw_report = Path(raw_directory) / "junit.xml"
        command = [
            sys.executable, "-m", "pytest", "-v", target, "--tb=short", "--show-capture=no",
            "-p", "ops.ci_pytest_gate", f"--junitxml={raw_report}",
        ]
        if cache_directory := os.getenv("CI_PYTEST_CACHE_DIR"):
            command.extend(["-o", f"cache_dir={cache_directory}"])
        if ignored:
            command.append(f"--ignore={ignored}")
        result = subprocess.run(command, env=env, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
           text=True, encoding="utf-8", errors="replace")
        (output / "run.json").write_text(json.dumps({**identity, "exit_code": result.returncode}) + "\n")
        try:
            safe_output = _redact_text(result.stdout or "")
            (output / "pytest.log").write_text(safe_output, encoding="utf-8")
            if raw_report.exists():
                redact(raw_report)
                report.write_text(raw_report.read_text(encoding="utf-8"), encoding="utf-8")
        except Exception:
            report.unlink(missing_ok=True)
            (output / "pytest.log").unlink(missing_ok=True)
            print("CI_PYTEST_RESULT=BLOCK (REPORT_SANITIZATION_FAILED)")
            return 1
    print(safe_output, end="", flush=True)
    try:
        totals = validate_report(report, manifest, minimum=int(os.getenv("CI_PYTEST_MINIMUM", "1846")))
    except (OSError, ValueError, ET.ParseError) as exc:
        print(f"CI_PYTEST_RESULT=BLOCK ({type(exc).__name__})")
        return result.returncode or 1
    print("CI_PYTEST_RESULT=" + json.dumps(totals, sort_keys=True))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
