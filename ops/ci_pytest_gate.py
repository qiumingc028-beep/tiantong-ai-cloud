"""Execute every collected test and verify its JUnit result, without a stale total."""
from __future__ import annotations

import base64
import ctypes
import errno
import hashlib
import hmac
import json
import os
from os import fsync as _progress_fsync
from pathlib import Path
import re
import signal
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
_PR_SET_CHILD_SUBREAPER = 36
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
        _validate_publication(output, head=head, run_id=run_id, run_attempt=run_attempt)
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


def _primary_error_matches_exits(primary_error: object, exits: object) -> bool:
    if primary_error is None:
        return True
    if not isinstance(primary_error, str) or not re.fullmatch(r"(?:CI_)?PYTEST_[A-Z_]+", primary_error):
        return False
    if not isinstance(exits, dict):
        return False
    for stage in ("main", "ownership", "aggregate"):
        prefix = f"PYTEST_{stage.upper()}_"
        if primary_error.startswith(prefix):
            value = exits.get(stage)
            if primary_error == prefix + "TIMEOUT":
                return _timeout_exit_valid(value)
            if primary_error == prefix + "FAILED":
                return type(value) is int and value != 0
            return False
    return True


def _timeout_exit_valid(value: object) -> bool:
    return value in {None, -signal.SIGTERM, -signal.SIGKILL}


def _terminal_error_matches_exits(terminal_error: object, exits: object) -> bool:
    if terminal_error is None:
        return True
    if terminal_error == "PYTEST_SUPERVISOR_CANCELLED":
        return True
    match = re.fullmatch(r"PYTEST_(MAIN|OWNERSHIP|AGGREGATE)_TIMEOUT", terminal_error or "")
    return bool(match and isinstance(exits, dict)
                and _timeout_exit_valid(exits.get(match.group(1).lower())))


def _supervision_state_valid(supervision_complete: object, exits: object) -> bool:
    return (
        type(supervision_complete) is bool
        and isinstance(exits, dict)
        and set(exits) == {"main", "ownership", "aggregate"}
        and (not supervision_complete or all(type(value) is int for value in exits.values()))
    )


def _partition_publication_eligible(
    primary_error: object, terminal_error: object, supervision_complete: object, exits: object,
) -> bool:
    return _supervision_state_valid(supervision_complete, exits) and supervision_complete is True and terminal_error is None and primary_error != "PYTEST_SUPERVISOR_CANCELLED" and not (
        isinstance(primary_error, str) and primary_error.endswith("_TIMEOUT")
    )


def _validate_publication(output: Path, *, head: str, run_id: str, run_attempt: str) -> None:
    publication = _read_publication(output)
    expected = {"head": head, "run_id": run_id, "run_attempt": run_attempt}
    exits = publication.get("stage_exit_codes")
    digests = publication.get("artifact_sha256")
    partition = publication.get("partition")
    allowed = _AGGREGATE_FILES if partition == "aggregate" else _PARTITION_FILES
    if (any(publication.get(key) != value for key, value in expected.items())
        or "terminal_error" not in publication
        or type(publication.get("supervision_complete")) is not bool
        or partition not in {"main", "ownership", "aggregate"}
        or publication.get("result") != "PASS"
        or publication.get("partition_result") != "PASS"
        or publication.get("artifact_result") != "PASS"
        or publication.get("overall_result") not in {"PASS", "BLOCK"}
        or not isinstance(digests, dict)
        or any(publication.get(key) is not None for key in ("cleanup_error", "publication_error"))
        or not isinstance(exits, dict) or set(exits) != {"main", "ownership", "aggregate"}
        or not _primary_error_matches_exits(publication.get("primary_error"), exits)
        or not _terminal_error_matches_exits(publication.get("terminal_error"), exits)
        or not _supervision_state_valid(publication.get("supervision_complete"), exits)
        or not _partition_publication_eligible(
            publication.get("primary_error"), publication.get("terminal_error"),
            publication.get("supervision_complete"), exits,
        )
        or type(exits.get(partition)) is not int
        or exits.get(partition) != 0
        or not {path.name for path in output.iterdir()}.issubset(allowed | {"publication.json"})
        or any(value is not None and (not isinstance(value, str)
                                      or not re.fullmatch(r"(?:CI_)?PYTEST_[A-Z_]+", value))
               for value in (publication.get("primary_error"), publication.get("cleanup_error"),
                             publication.get("publication_error")))
        or (partition == "aggregate" and (
            publication.get("overall_result") != "PASS"
            or publication.get("primary_error") is not None
            or any(type(value) is not int or value != 0 for value in exits.values())
        ))):
        raise ValueError("PYTEST_PUBLICATION_INVALID")
    files = {path.name: hashlib.sha256(_stable_file_bytes(path)).hexdigest()
             for path in output.iterdir() if path.name != "publication.json"}
    if files != digests:
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
    for partition, (output, allowed) in zip(("main", "ownership", "aggregate"), specs):
        publication = _read_publication(output)
        digests = publication.get("artifact_sha256")
        expected = {"head": head, "run_id": run_id, "run_attempt": run_attempt}
        if (publication.get("partition") != partition
            or "terminal_error" not in publication
            or type(publication.get("supervision_complete")) is not bool
            or publication.get("result") not in {"PASS", "BLOCK"}
            or publication.get("partition_result") != publication.get("result")
            or publication.get("artifact_result") not in {"PASS", "BLOCK"}
            or publication.get("overall_result") not in {"PASS", "BLOCK"}
            or not isinstance(digests, dict)
            or any(publication.get(key) != value for key, value in expected.items())
            or not {path.name for path in output.iterdir()}.issubset(allowed | {"publication.json"})):
            raise ValueError("PYTEST_PUBLICATION_INVALID")
        for key in ("primary_error", "terminal_error", "cleanup_error", "publication_error"):
            value = publication.get(key)
            if value is not None and (not isinstance(value, str)
                                      or not re.fullmatch(r"(?:CI_)?PYTEST_[A-Z_]+", value)):
                raise ValueError("PYTEST_PUBLICATION_INVALID")
        exits = publication.get("stage_exit_codes")
        if (not isinstance(exits, dict) or set(exits) != {"main", "ownership", "aggregate"}
            or any(value is not None and type(value) is not int for value in exits.values())):
            raise ValueError("PYTEST_PUBLICATION_INVALID")
        if not _primary_error_matches_exits(publication.get("primary_error"), exits):
            raise ValueError("PYTEST_PUBLICATION_INVALID")
        if not _terminal_error_matches_exits(publication.get("terminal_error"), exits):
            raise ValueError("PYTEST_PUBLICATION_INVALID")
        if not _supervision_state_valid(publication.get("supervision_complete"), exits):
            raise ValueError("PYTEST_PUBLICATION_INVALID")
        terminal_safe = (
            not publication.get("cleanup_error") and not publication.get("publication_error")
            and _partition_publication_eligible(
                publication.get("primary_error"), publication.get("terminal_error"),
                publication.get("supervision_complete"), exits,
            )
        )
        expected_overall = "PASS" if (
            terminal_safe and publication.get("primary_error") is None
            and all(type(value) is int and value == 0 for value in exits.values())
        ) else "BLOCK"
        expected_partition = "PASS" if (
            publication.get("artifact_result") == "PASS" and terminal_safe
            and ((partition != "aggregate" and exits.get(partition) == 0)
                 or (partition == "aggregate" and expected_overall == "PASS"))
        ) else "BLOCK"
        if (publication.get("overall_result") != expected_overall
            or publication.get("partition_result") != expected_partition):
            raise ValueError("PYTEST_PUBLICATION_INVALID")
        if publication.get("artifact_result") == "BLOCK" and {
            path.name for path in output.iterdir()
        } != {"publication.json"}:
            raise ValueError("PYTEST_PUBLICATION_UNSAFE_BLOCK")
        files = {path.name: hashlib.sha256(_stable_file_bytes(path)).hexdigest()
                 for path in output.iterdir() if path.name != "publication.json"}
        if files != digests:
            raise ValueError("PYTEST_PUBLICATION_INVALID")
        publications.append(publication)
    shared = lambda value: {key: item for key, item in value.items()
                            if key not in {"partition", "result", "partition_result", "artifact_sha256"}}
    if any(shared(publication) != shared(publications[0]) for publication in publications[1:]):
        raise ValueError("PYTEST_PUBLICATION_STATE_MISMATCH")
    _scan_identity_key(outputs)


def _run_identity() -> dict:
    return {"head": os.getenv("RELEASE_SOURCE_SHA", ""),
            "run_id": os.getenv("GITHUB_RUN_ID", "local"),
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "1")}


def _partition_environments(cache_root: Path) -> tuple[dict, dict, dict]:
    base = dict(os.environ)
    # Only the supervisor may declare publication readiness to the workflow.
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


def _linux_group_members(pgid: int) -> set[tuple[int, str]]:
    members = set()
    for status_path in Path("/proc").glob("[0-9]*/stat"):
        value = None
        last_error = None
        for _ in range(3):
            try:
                value = status_path.read_text(encoding="utf-8")
                break
            except FileNotFoundError:
                if not status_path.exists():
                    break
            except OSError as exc:
                if not status_path.exists():
                    break
                last_error = exc
            time.sleep(0.005)
        if value is None:
            if status_path.exists():
                raise RuntimeError("PYTEST_PROCESS_OWNERSHIP_UNPROVEN") from last_error
            continue
        try:
            fields = value[value.rfind(")") + 2:].split()
            if int(fields[2]) == pgid and fields[0] != "Z":
                members.add((int(status_path.parent.name), fields[19]))
        except (ValueError, IndexError) as exc:
            raise RuntimeError("PYTEST_PROCESS_OWNERSHIP_UNPROVEN") from exc
    return members


def _group_alive(pgid: int) -> bool:
    if sys.platform.startswith("linux"):
        return bool(_linux_group_members(pgid))
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _enable_child_subreaper() -> bool:
    """Keep orphaned managed descendants waitable by this supervisor on Linux."""
    if not sys.platform.startswith("linux"):
        return False
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        raise _SupervisorFailure("PYTEST_PROCESS_OWNERSHIP_UNPROVEN")
    return True


def _linux_child_pids(parent_pid: int) -> set[int]:
    try:
        value = Path(f"/proc/{parent_pid}/task/{parent_pid}/children").read_text(encoding="ascii")
        return {int(pid) for pid in value.split()}
    except (OSError, ValueError) as exc:
        raise RuntimeError("PYTEST_PROCESS_OWNERSHIP_UNPROVEN") from exc


def _process_parent_identity(pid: int) -> tuple[int, str] | None:
    try:
        value = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RuntimeError("PYTEST_PROCESS_OWNERSHIP_UNPROVEN") from exc
    try:
        fields = value[value.rfind(")") + 2:].split()
        return int(fields[1]), fields[19]
    except (IndexError, ValueError) as exc:
        raise RuntimeError("PYTEST_PROCESS_OWNERSHIP_UNPROVEN") from exc


def _direct_child_identities(parent_pid: int) -> dict[int, str]:
    children = {}
    for pid in _linux_child_pids(parent_pid):
        info = None
        for _ in range(3):
            info = _process_parent_identity(pid)
            if info is not None:
                break
            if pid not in _linux_child_pids(parent_pid):
                break
            time.sleep(0.005)
        if info is None:
            if pid in _linux_child_pids(parent_pid):
                raise RuntimeError("PYTEST_PROCESS_OWNERSHIP_UNPROVEN")
            continue
        actual_parent, identity = info
        if actual_parent != parent_pid:
            if pid in _linux_child_pids(parent_pid):
                raise RuntimeError("PYTEST_PROCESS_OWNERSHIP_UNPROVEN")
            continue
        children[pid] = identity
    return children


def _adopted_managed_children(records: list[dict]) -> dict[int, str]:
    baseline = records[0].get("subreaper_baseline", {}) if records else {}
    managed = {(record["pid"], record.get("process_identity")) for record in records}
    return {
        pid: identity for pid, identity in _direct_child_identities(os.getpid()).items()
        if baseline.get(pid) != identity and (pid, identity) not in managed
    }


def _signal_owned_pid(pid: int, identity: str, signum: int) -> None:
    if _process_identity(pid) != identity:
        return
    try:
        os.kill(pid, signum)
    except ProcessLookupError:
        pass


def _reap_adopted_child(pid: int, identity: str) -> None:
    if _process_identity(pid) != identity:
        return
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError as exc:
        if _process_identity(pid) == identity:
            raise RuntimeError("PYTEST_PROCESS_OWNERSHIP_UNPROVEN") from exc


def _terminate_adopted_children(records: list[dict], *, grace_seconds: float) -> None:
    deadline = time.monotonic() + grace_seconds
    signalled = set()
    while True:
        children = _adopted_managed_children(records)
        for pid, identity in children.items():
            if (pid, identity) not in signalled:
                _signal_owned_pid(pid, identity, signal.SIGTERM)
                signalled.add((pid, identity))
            _reap_adopted_child(pid, identity)
        if not _adopted_managed_children(records):
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(0.02)
    deadline = time.monotonic() + 1.0
    while True:
        children = _adopted_managed_children(records)
        for pid, identity in children.items():
            _signal_owned_pid(pid, identity, signal.SIGKILL)
            _reap_adopted_child(pid, identity)
        if not _adopted_managed_children(records):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("PYTEST_PROCESS_REAP_FAILED")
        time.sleep(0.02)


def _observe_process_exit(record: dict) -> int | None:
    if "exit_code" in record:
        return record["exit_code"]
    if not record.get("owns_group"):
        value = record["process"].poll()
        if value is not None:
            record.update(exit_code=int(value), reaped=True)
        return value
    waitid = getattr(os, "waitid", None)
    if waitid is None:
        value = record["process"].poll()
        if value is not None:
            record.update(exit_code=int(value), reaped=True)
        return value
    try:
        status = waitid(os.P_PID, record["pid"], os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except ChildProcessError as exc:
        raise _SupervisorFailure("PYTEST_PROCESS_OWNERSHIP_UNPROVEN") from exc
    if status is None:
        return None
    exit_code = status.si_status if status.si_code == os.CLD_EXITED else -status.si_status
    record["exit_code"] = int(exit_code)
    return int(exit_code)


def _owned_process_group(record: dict) -> bool:
    if record.get("reaped") or not record.get("owns_group") or record["pid"] != record["pgid"]:
        return False
    expected_identity = record.get("process_identity")
    if expected_identity is None or _process_identity(record["pid"]) != expected_identity:
        return False
    try:
        return os.getpgid(record["pid"]) == record["pgid"]
    except ProcessLookupError:
        return False


def _terminate_processes(records: list[dict], *, grace_seconds: float = 5.0) -> None:
    active = [record for record in records if not record.get("reaped")]
    unowned = [record for record in active if not _owned_process_group(record)]
    if unowned:
        raise RuntimeError("PYTEST_PROCESS_REAP_FAILED")
    owned_groups = {record["pgid"] for record in active}
    original_members = (
        {pgid: _linux_group_members(pgid) for pgid in owned_groups}
        if sys.platform.startswith("linux") else {}
    )
    for record in active:
        try:
            os.killpg(record["pgid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + grace_seconds
    while active and time.monotonic() < deadline:
        time.sleep(0.02)
    for record in active:
        if (_owned_process_group(record)
            or (sys.platform.startswith("linux") and original_members[record["pgid"]]
                & _linux_group_members(record["pgid"]))):
            try:
                os.killpg(record["pgid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
    reap_error = None
    for record in active:
        try:
            record["exit_code"] = int(record["process"].wait(timeout=1))
            record["reaped"] = True
        except subprocess.TimeoutExpired:
            reap_error = reap_error or RuntimeError("PYTEST_PROCESS_REAP_FAILED")
    if sys.platform.startswith("linux"):
        deadline = time.monotonic() + 1
        while any(_group_alive(pgid) for pgid in owned_groups) and time.monotonic() < deadline:
            time.sleep(0.02)
        if any(_group_alive(pgid) for pgid in owned_groups):
            reap_error = reap_error or RuntimeError("PYTEST_PROCESS_REAP_FAILED")
    if records and records[0].get("subreaper"):
        try:
            _terminate_adopted_children(records, grace_seconds=grace_seconds)
        except RuntimeError as exc:
            reap_error = reap_error or exc
    if reap_error is not None:
        raise reap_error


class _SupervisorFailure(Exception):
    def __init__(self, primary_error: str, *, terminal_error: str | None = None):
        super().__init__(primary_error)
        self.terminal_error = terminal_error


class _CleanupFailure(Exception):
    pass


def _first_stage_failure(records: list[dict]) -> str | None:
    failed = [record for record in records if _observe_process_exit(record) not in (None, 0)]
    if not failed:
        return None
    first = min(failed, key=lambda record: record.get("finished_at", float("inf")))
    return f"PYTEST_{first['name'].upper()}_FAILED"


def _wait_managed(records: list[dict], timeouts: dict[str, float]) -> list[int]:
    while True:
        exits = [_observe_process_exit(record) for record in records]
        now = time.monotonic()
        for record, exit_code in zip(records, exits):
            if exit_code is not None and "finished_at" not in record:
                record["finished_at"] = now
        if all(value is not None for value in exits):
            return [int(value) for value in exits]
        for record, exit_code in zip(records, exits):
            if exit_code is None and now - record["started_at"] >= timeouts[record["name"]]:
                timeout_error = f"PYTEST_{record['name'].upper()}_TIMEOUT"
                raise _SupervisorFailure(
                    _first_stage_failure(records) or timeout_error,
                    terminal_error=timeout_error,
                )
        time.sleep(0.05)


def _write_process_state(path: Path, records: list[dict], phase: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"phase": phase, "processes": [
        {"name": record["name"], "pid": record["pid"], "pgid": record["pgid"],
         "exit_code": record.get("exit_code")} for record in records
    ]}
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _identity_key_parts() -> tuple[bytes, bytes, bytes]:
    value = os.environ.get("CI_PYTEST_IDENTITY_KEY", "")
    if len(value) < 43:
        raise RuntimeError("CI_PYTEST_IDENTITY_KEY_MISSING")
    raw = value.encode()
    return raw, base64.b64encode(raw), raw.hex().encode()


def _contains_identity_key(payload: bytes) -> bool:
    raw, encoded, hexadecimal = _identity_key_parts()
    return raw in payload or encoded in payload or hexadecimal in payload.lower()


def _scan_identity_key(outputs: list[Path]) -> None:
    for output in outputs:
        for path in output.rglob("*"):
            if path.is_file() and _contains_identity_key(_stable_file_bytes(path)):
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
    """Read Linux start time so a recycled PID can never prove ownership."""
    try:
        value = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        return value[value.rfind(")") + 2:].split()[19]
    except (OSError, IndexError):
        return None


def _publication_payload(identity: dict, partition: str, partition_result: str,
                         overall_result: str, artifact_result: str, primary_error: str | None,
                         terminal_error: str | None,
                         cleanup_error: str | None, publication_error: str | None,
                         stage_exit_codes: dict[str, int | None], artifact_sha256: dict[str, str],
                         supervision_complete: bool) -> dict:
    return {
        **identity, "partition": partition, "result": partition_result,
        "partition_result": partition_result, "overall_result": overall_result,
        "artifact_result": artifact_result, "primary_error": primary_error,
        "terminal_error": terminal_error,
        "supervision_complete": supervision_complete,
        "cleanup_error": cleanup_error, "publication_error": publication_error,
        "stage_exit_codes": stage_exit_codes, "artifact_sha256": artifact_sha256,
    }


def _path_identity(path: Path) -> tuple[int, int, int]:
    value = os.lstat(path)
    return value.st_dev, value.st_ino, value.st_mode


def _open_owned_directory(path: Path) -> dict:
    descriptor = os.open(
        path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    value = os.fstat(descriptor)
    if not stat.S_ISDIR(value.st_mode):
        os.close(descriptor)
        raise RuntimeError("PYTEST_PUBLISH_TARGET_OWNERSHIP_LOST")
    return {
        "path": path, "fd": descriptor,
        "identity": (value.st_dev, value.st_ino, value.st_mode),
        "files": {}, "unverified_files": set(), "digests": {},
    }


def _new_owned_directory(path: Path) -> dict:
    path.mkdir(mode=0o700)
    return _open_owned_directory(path)


def _write_owned_file(owned: dict, name: str, payload: bytes) -> None:
    if _path_identity(owned["path"]) != owned["identity"]:
        raise RuntimeError("PYTEST_PUBLISH_TARGET_OWNERSHIP_LOST")
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600, dir_fd=owned["fd"],
    )
    owned["unverified_files"].add(name)
    stream = None
    try:
        value = os.fstat(descriptor)
        owned["files"][name] = (value.st_dev, value.st_ino, value.st_mode)
        owned["unverified_files"].discard(name)
        stream = os.fdopen(descriptor, "wb")
        descriptor = -1
        with stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _cleanup_owned_directory(owned: dict) -> None:
    path = owned["path"]
    descriptor = owned.get("fd")
    if descriptor is None:
        if owned.get("cleanup_failed"):
            raise RuntimeError("PYTEST_PUBLICATION_CLEANUP_FAILED")
        return
    failed = bool(owned.get("unverified_files"))
    try:
        try:
            if not os.path.lexists(path) or _path_identity(path) != owned["identity"]:
                failed = True
        except OSError:
            failed = True
        for name, identity in reversed(tuple(owned["files"].items())):
            try:
                value = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if (value.st_dev, value.st_ino, value.st_mode) == identity:
                    os.unlink(name, dir_fd=descriptor)
                else:
                    failed = True
            except OSError:
                failed = True
    finally:
        owned.pop("fd", None)
        try:
            os.close(descriptor)
        except OSError:
            failed = True
        owned["cleanup_failed"] = failed
    if failed:
        raise RuntimeError("PYTEST_PUBLICATION_CLEANUP_FAILED")


def _close_owned_directory(owned: dict) -> None:
    descriptor = owned.pop("fd", None)
    if descriptor is not None:
        try:
            os.close(descriptor)
        except OSError as exc:
            raise RuntimeError("PYTEST_PUBLICATION_CLEANUP_FAILED") from exc


def _rename_directory_noreplace(source: Path, target: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux"):
        result = libc.renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1)
    elif sys.platform == "darwin":
        result = libc.renamex_np(os.fsencode(source), os.fsencode(target), 4)
    else:
        if os.path.lexists(target):
            raise RuntimeError("PYTEST_PUBLISH_TARGET_NOT_FRESH")
        os.rename(source, target)
        return
    if result == 0:
        return
    code = ctypes.get_errno()
    if code in {errno.EEXIST, errno.ENOTEMPTY}:
        raise RuntimeError("PYTEST_PUBLISH_TARGET_NOT_FRESH")
    raise OSError(code, os.strerror(code), str(target))


def _receipt_results(partition: str, artifact_result: str, overall_result: str,
                     cleanup_error: str | None, publication_error: str | None,
                     stage_exit_codes: dict[str, int | None], primary_error: str | None,
                     terminal_error: str | None, supervision_complete: bool) -> str:
    if artifact_result != "PASS" or cleanup_error or publication_error:
        return "BLOCK"
    if not _partition_publication_eligible(
        primary_error, terminal_error, supervision_complete, stage_exit_codes,
    ):
        return "BLOCK"
    if partition == "aggregate":
        return overall_result
    return "PASS" if stage_exit_codes.get(partition) == 0 else "BLOCK"


def publish_outputs(specs: list[tuple[Path, Path, set[str]]], *, identity: dict, result: str,
                    primary_error: str | None, cleanup_error: str | None,
                    stage_exit_codes: dict[str, int | None], supervision_complete: bool,
                    atomic_root: Path | None = None,
                    terminal_error: str | None = None) -> str:
    """Publish only stable, scanned files after all writers have stopped."""
    partitions = ("main", "ownership", "aggregate") if len(specs) == 3 else ("aggregate",)
    targets = [target for _, target, _ in specs]
    if atomic_root is not None and (
        len(targets) < 2 or any(target.parent != atomic_root for target in targets)
    ):
        raise ValueError("PYTEST_PUBLISH_ATOMIC_ROOT_INVALID")
    if (len(partitions) != len(specs)
        or (atomic_root is not None and os.path.lexists(atomic_root))
        or any(os.path.lexists(target) for target in targets)):
        print("CI_PYTEST_PUBLICATION=BLOCK (PYTEST_PUBLISH_TARGET_NOT_FRESH)")
        return "UNPUBLISHABLE"
    publication_error = None
    owned: list[dict] = []
    bundle = None
    try:
        if cleanup_error:
            raise RuntimeError(cleanup_error)
        _scan_identity_key([source for source, _, _ in specs])
        staged: list[tuple[dict, Path, set[str]]] = []
        if atomic_root is not None:
            bundle_path = Path(tempfile.mkdtemp(prefix=f".{atomic_root.name}.", dir=atomic_root.parent))
            bundle = _open_owned_directory(bundle_path)
            owned.append(bundle)
        for source, target, allowed in specs:
            source_names = {path.name for path in source.iterdir()}
            if not source_names.issubset(allowed):
                raise RuntimeError("PYTEST_ARTIFACT_FILE_SET_INVALID")
            if bundle is not None:
                stage = bundle["path"] / target.name
                stage_owned = _new_owned_directory(stage)
            else:
                stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.", dir=target.parent))
                stage_owned = _open_owned_directory(stage)
            owned.append(stage_owned)
            for name in sorted(source_names):
                payload = _stable_file_bytes(source / name)
                if _contains_identity_key(payload):
                    raise RuntimeError("CI_PYTEST_IDENTITY_ARTIFACT_LEAK")
                _write_owned_file(stage_owned, name, payload)
                stage_owned["digests"][name] = hashlib.sha256(payload).hexdigest()
            staged.append((stage_owned, target, allowed))
        overall_result = "PASS" if (
            _supervision_state_valid(supervision_complete, stage_exit_codes)
            and supervision_complete and result == "PASS" and primary_error is None
            and terminal_error is None and cleanup_error is None
            and all(type(value) is int and value == 0 for value in stage_exit_codes.values())
        ) else "BLOCK"
        for partition, (stage_owned, target, _allowed) in zip(partitions, staged):
            partition_result = _receipt_results(
                partition, "PASS", overall_result, None, None, stage_exit_codes, primary_error,
                terminal_error, supervision_complete,
            )
            payload = _publication_payload(
                identity, partition, partition_result, overall_result, "PASS",
                primary_error, terminal_error, None, None, stage_exit_codes, stage_owned["digests"],
                supervision_complete,
            )
            _write_owned_file(stage_owned, "publication.json", json.dumps(payload, sort_keys=True).encode() + b"\n")
        _scan_identity_key([stage_owned["path"] for stage_owned, _, _ in staged])
        for stage_owned, _, allowed in staged:
            if (_path_identity(stage_owned["path"]) != stage_owned["identity"]
                or {path.name for path in stage_owned["path"].iterdir()} != allowed.intersection(
                    stage_owned["files"]
                ) | {"publication.json"}):
                raise RuntimeError("PYTEST_ARTIFACT_FILE_SET_INVALID")
        if bundle is not None:
            _rename_directory_noreplace(bundle["path"], atomic_root)
            bundle["path"] = atomic_root
            for stage_owned, target, _ in staged:
                stage_owned["path"] = target
        else:
            for stage_owned, target, _ in staged:
                _rename_directory_noreplace(stage_owned["path"], target)
                stage_owned["path"] = target
        _scan_identity_key([target for _, target, _ in specs])
        for stage_owned, (_, target, allowed) in zip((item[0] for item in staged), specs):
            if (_path_identity(target) != stage_owned["identity"]
                or {path.name for path in target.iterdir()} != allowed.intersection(
                    stage_owned["files"]
                ) | {"publication.json"}):
                raise RuntimeError("PYTEST_ARTIFACT_FILE_SET_INVALID")
            if any(_path_identity(target / name) != file_identity
                   for name, file_identity in stage_owned["files"].items()):
                raise RuntimeError("PYTEST_PUBLISH_TARGET_OWNERSHIP_LOST")
            actual = {name: hashlib.sha256(_stable_file_bytes(target / name)).hexdigest()
                      for name in stage_owned["digests"]}
            if actual != stage_owned["digests"]:
                raise RuntimeError("PYTEST_ARTIFACT_UNSTABLE")
        if bundle is not None and _path_identity(atomic_root) != bundle["identity"]:
            raise RuntimeError("PYTEST_PUBLISH_TARGET_OWNERSHIP_LOST")
        for item in reversed(owned):
            _close_owned_directory(item)
        owned.clear()
    except (OSError, RuntimeError) as exc:
        failure_code = _error_code(exc)
        if failure_code == "PYTEST_PUBLICATION_CLEANUP_FAILED":
            cleanup_error = cleanup_error or failure_code
        elif not cleanup_error or str(exc) != cleanup_error:
            publication_error = failure_code
        cleanup_fail = None
        for item in reversed(owned):
            try:
                _cleanup_owned_directory(item)
            except RuntimeError as cleanup_exc:
                cleanup_fail = cleanup_fail or _error_code(cleanup_exc)
        cleanup_error = cleanup_error or cleanup_fail
        if str(exc) == "PYTEST_PUBLISH_TARGET_NOT_FRESH":
            print("CI_PYTEST_PUBLICATION=BLOCK (PYTEST_PUBLISH_TARGET_NOT_FRESH)")
            return "UNPUBLISHABLE"
    else:
        return overall_result
    receipt_owned: list[dict] = []
    receipt_bundle = None
    try:
        if atomic_root is not None:
            receipt_root = Path(tempfile.mkdtemp(prefix=f".{atomic_root.name}.receipt.", dir=atomic_root.parent))
            receipt_bundle = _open_owned_directory(receipt_root)
            receipt_owned.append(receipt_bundle)
        for partition, (_, target, _) in zip(partitions, specs):
            if receipt_bundle is not None:
                receipt = _new_owned_directory(receipt_bundle["path"] / target.name)
            else:
                receipt_path = Path(tempfile.mkdtemp(prefix=f".{target.name}.receipt.", dir=target.parent))
                receipt = _open_owned_directory(receipt_path)
            receipt_owned.append(receipt)
            payload = _publication_payload(
                identity, partition, "BLOCK", "BLOCK", "BLOCK", primary_error,
                terminal_error, cleanup_error, publication_error, stage_exit_codes, {},
                supervision_complete,
            )
            _write_owned_file(receipt, "publication.json", json.dumps(payload, sort_keys=True).encode() + b"\n")
        if receipt_bundle is not None:
            _rename_directory_noreplace(receipt_bundle["path"], atomic_root)
            receipt_bundle["path"] = atomic_root
        else:
            for receipt, (_, target, _) in zip(receipt_owned, specs):
                _rename_directory_noreplace(receipt["path"], target)
                receipt["path"] = target
        for item in reversed(receipt_owned):
            _close_owned_directory(item)
    except (OSError, RuntimeError):
        for item in reversed(receipt_owned):
            try:
                _cleanup_owned_directory(item)
            except RuntimeError:
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
    except subprocess.TimeoutExpired as exc:
        raise _SupervisorFailure("PYTEST_PROCESS_REAP_FAILED") from exc


def _start_managed_process(name: str, command: list[str], environment: dict, records: list[dict]) -> dict:
    deferred: list[int] = []
    previous_handlers = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}

    def defer(signum, _frame):
        deferred.append(signum)

    try:
        for signum in previous_handlers:
            signal.signal(signum, defer)
        if records:
            subreaper = records[0].get("subreaper", False)
            subreaper_baseline = records[0].get("subreaper_baseline", {})
        else:
            subreaper = _enable_child_subreaper()
            subreaper_baseline = _direct_child_identities(os.getpid()) if subreaper else {}
        process = subprocess.Popen(command, env=environment, start_new_session=True)
        process_identity = _process_identity(process.pid)
        if process_identity is None:
            _terminate_new_process_group(process)
            raise _SupervisorFailure("PYTEST_PROCESS_IDENTITY_UNAVAILABLE")
        record = {"name": name, "process": process, "pid": process.pid, "pgid": process.pid,
                  "process_identity": process_identity, "started_at": time.monotonic(),
                  "owns_group": True, "subreaper": subreaper,
                  "subreaper_baseline": subreaper_baseline}
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
    terminal_error = None
    supervision_complete = False
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
        except _SignalExit:
            raise
        except Exception as exc:
            cleanup_error = cleanup_error or _error_code(exc)
            raise _CleanupFailure from None
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
        supervision_complete = True
        phase = "complete"
    except _SignalExit as exc:
        result = 128 + exc.signum
        primary_error = primary_error or _first_stage_failure(records) or "PYTEST_SUPERVISOR_CANCELLED"
        terminal_error = "PYTEST_SUPERVISOR_CANCELLED"
        phase = "cancelled"
    except _CleanupFailure:
        result = 1
        phase = "cleanup_failed"
    except (OSError, RuntimeError, _SupervisorFailure) as exc:
        failure_code = _error_code(exc)
        primary_error = primary_error or failure_code
        terminal_error = terminal_error or getattr(exc, "terminal_error", None)
        if terminal_error is None and failure_code.endswith("_TIMEOUT"):
            terminal_error = failure_code
        result = 1
        phase = "failed"
    finally:
        deferred_cleanup_signals = []

        def defer_cleanup_signal(signum, _frame):
            deferred_cleanup_signals.append(signum)

        try:
            for signum in previous_handlers:
                signal.signal(signum, defer_cleanup_signal)
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
    if deferred_cleanup_signals:
        result = 128 + deferred_cleanup_signals[0]
        primary_error = primary_error or "PYTEST_SUPERVISOR_CANCELLED"
        terminal_error = "PYTEST_SUPERVISOR_CANCELLED"
        supervision_complete = False
        phase = "cancelled"
    for record in records:
        stage_exits[record["name"]] = record.get("exit_code")
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
            supervision_complete=supervision_complete,
            atomic_root=publish_main.parent if explicit_publish else None,
            terminal_error=terminal_error,
        )
        if final == "UNPUBLISHABLE":
            raise RuntimeError("PYTEST_PUBLICATION_UNPUBLISHABLE")
        validate_publication_outputs(
            [publish_main, publish_ownership, publish_aggregate], **_run_identity(),
        )
        output_path = os.getenv("GITHUB_OUTPUT")
        if output_path:
            with open(output_path, "a", encoding="utf-8") as stream:
                stream.write("publication_ready=true\n")
    except Exception:
        output_path = os.getenv("GITHUB_OUTPUT")
        if output_path:
            with open(output_path, "a", encoding="utf-8") as stream:
                stream.write("publication_ready=false\n")
        print("CI_PYTEST_SUPERVISOR=BLOCK (PYTEST_PUBLICATION_FAILED)")
        return result or 1
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
