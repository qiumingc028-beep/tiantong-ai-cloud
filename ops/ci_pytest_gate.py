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


def validate_partition_output(output: Path, *, head: str, run_id: str, run_attempt: str, minimum: int) -> list[str]:
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
            output, head=head, run_id=run_id, run_attempt=run_attempt, minimum=1,
        )
        if combined.intersection(nodes):
            raise ValueError("PYTEST_PARTITION_OVERLAP")
        combined.update(nodes)
    if combined != set(full):
        raise ValueError("PYTEST_PARTITION_UNION_MISMATCH")
    return {"collected": len(full), "executed": len(combined), "overlap": 0, "missing": 0}


def validate_aggregate_output(output: Path, *, head: str, run_id: str, run_attempt: str) -> dict:
    result = json.loads((output / "aggregate.json").read_text(encoding="utf-8"))
    expected = {"head": head, "run_id": run_id, "run_attempt": run_attempt, "result": "PASS"}
    if not isinstance(result, dict) or any(result.get(key) != value for key, value in expected.items()):
        raise ValueError("PYTEST_AGGREGATE_IDENTITY_OR_RESULT_INVALID")
    counts = {key: result.get(key) for key in ("collected", "executed", "overlap", "missing")}
    if (any(type(value) is not int for value in counts.values()) or counts["collected"] < 1
        or counts["collected"] != counts["executed"] or counts["overlap"] != 0 or counts["missing"] != 0):
        raise ValueError("PYTEST_AGGREGATE_COVERAGE_INVALID")
    return result


def _run_identity() -> dict:
    return {"head": os.getenv("RELEASE_SOURCE_SHA", ""),
            "run_id": os.getenv("GITHUB_RUN_ID", "local"),
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT", "1")}


def _partition_environments(cache_root: Path) -> tuple[dict, dict, dict]:
    base = dict(os.environ)
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
    for record in records:
        record["process"].poll()
    for record in records:
        if _group_alive(record["pgid"]):
            try:
                os.killpg(record["pgid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + grace_seconds
    while any(_group_alive(record["pgid"]) for record in records) and time.monotonic() < deadline:
        for record in records:
            record["process"].poll()
        time.sleep(0.02)
    for record in records:
        record["process"].poll()
    for record in records:
        if _group_alive(record["pgid"]):
            try:
                os.killpg(record["pgid"], signal.SIGKILL)
            except ProcessLookupError:
                pass
    for record in records:
        try:
            record["process"].wait(timeout=1)
        except subprocess.TimeoutExpired:
            raise RuntimeError("PYTEST_PROCESS_REAP_FAILED") from None


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
    needles = (raw, base64.b64encode(raw), raw.hex().encode())
    for output in outputs:
        for path in output.rglob("*"):
            if path.is_file() and any(needle in path.read_bytes() for needle in needles):
                raise RuntimeError("CI_PYTEST_IDENTITY_ARTIFACT_LEAK")


class _SignalExit(Exception):
    def __init__(self, signum: int):
        self.signum = signum


def _start_managed_process(name: str, command: list[str], environment: dict, records: list[dict]) -> dict:
    deferred: list[int] = []
    previous_handlers = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}

    def defer(signum, _frame):
        deferred.append(signum)

    try:
        for signum in previous_handlers:
            signal.signal(signum, defer)
        process = subprocess.Popen(command, env=environment, start_new_session=True)
        record = {"name": name, "process": process, "pid": process.pid, "pgid": process.pid}
        records.append(record)
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    if deferred:
        raise _SignalExit(deferred[0])
    return record


def _partitions_main() -> int:
    main_output, ownership_output, aggregate_output = map(Path, sys.argv[2:5])
    process_state = aggregate_output / "processes.json"
    records: list[dict] = []
    previous_handlers = {signum: signal.getsignal(signum) for signum in (signal.SIGINT, signal.SIGTERM)}

    def interrupted(signum, _frame):
        raise _SignalExit(signum)

    for signum in previous_handlers:
        signal.signal(signum, interrupted)
    result = 1
    phase = "failed"
    cache_directory = tempfile.TemporaryDirectory(prefix="r297-pytest-caches-")
    try:
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
        exits = [record["process"].wait() for record in records]
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
        aggregate_exit = aggregate_record["process"].wait()
        _scan_identity_key([main_output, ownership_output, aggregate_output])
        result = 0 if exits == [0, 0] and aggregate_exit == 0 else 1
        phase = "complete"
    except _SignalExit as exc:
        result = 128 + exc.signum
        phase = "cancelled"
    finally:
        cleanup_error = None
        try:
            for signum in previous_handlers:
                signal.signal(signum, signal.SIG_IGN)
            try:
                _terminate_processes(records, grace_seconds=_PROCESS_TERM_GRACE_SECONDS)
            except Exception as exc:
                cleanup_error = exc
                phase = "cleanup_failed"
            finally:
                cache_directory.cleanup()
            _write_process_state(process_state, records, phase)
            if cleanup_error is not None:
                raise cleanup_error
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
    return result


def _validation_main(kind: str) -> int:
    identity = _run_identity()
    try:
        if kind == "--validate-partition":
            validate_partition_output(Path(sys.argv[2]), minimum=int(sys.argv[3]), **identity)
        else:
            validate_aggregate_output(Path(sys.argv[2]), **identity)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
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
    if sys.argv[1] in {"--validate-partition", "--validate-aggregate"}:
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
