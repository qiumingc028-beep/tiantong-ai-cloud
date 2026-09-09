"""Execute every collected test and verify its JUnit result, without a stale total."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from ops.r297_ci_redact import _redact_text, redact

_OUTCOMES: dict[str, str] = {}
_OUTCOME_PRIORITY = {"passed": 0, "skipped": 1, "failed": 2}


def _progress_path(name: str) -> Path | None:
    root = os.getenv("CI_PYTEST_PROGRESS_DIRECTORY")
    return Path(root) / name if root else None


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
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def pytest_sessionstart(session):
    _OUTCOMES.clear()
    _write_status(result="INCOMPLETE", phase="executing", last_completed_test=None)


def pytest_collection_finish(session):
    target = os.getenv("CI_PYTEST_COLLECTION_MANIFEST")
    if target:
        Path(target).write_text(json.dumps([item.nodeid for item in session.items]), encoding="utf-8")
    _write_status(collected=len(session.items))


def pytest_runtest_logstart(nodeid, location):
    _write_status(current_test=_redact_text(nodeid), current_phase="setup")


def pytest_runtest_call(item):
    _write_status(current_test=_redact_text(item.nodeid), current_phase="call")


def pytest_runtest_teardown(item, nextitem):
    _write_status(current_test=_redact_text(item.nodeid), current_phase="teardown")


def pytest_runtest_logreport(report):
    nodeid = _redact_text(report.nodeid)
    previous = _OUTCOMES.get(nodeid, "passed")
    if _OUTCOME_PRIORITY.get(report.outcome, 2) >= _OUTCOME_PRIORITY.get(previous, 0):
        _OUTCOMES[nodeid] = report.outcome
    _append_progress({
        "nodeid": nodeid, "outcome": report.outcome, "phase": report.when,
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


def main() -> int:
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "collected-nodeids.json"
    report = output / "junit.xml"
    env = dict(
        os.environ,
        CI_PYTEST_COLLECTION_MANIFEST=str(manifest),
        CI_PYTEST_PROGRESS_DIRECTORY=str(output),
    )
    print("CI_PYTEST_STARTED=ALL_COLLECTED_TESTS", flush=True)
    # Failure tracebacks can include credentials. Do not send raw subprocess
    # output to Actions; sanitize it before either logging or artifact upload.
    # The raw JUnit file is outside the upload directory, including if a job is
    # cancelled before pytest finishes. Only a sanitized copy may be published.
    with tempfile.TemporaryDirectory(prefix="r297-ci-pytest-") as raw_directory:
        raw_report = Path(raw_directory) / "junit.xml"
        result = subprocess.run([
            sys.executable, "-m", "pytest", "-v", "tests/", "--tb=short", "--show-capture=no",
            "-p", "ops.ci_pytest_gate", f"--junitxml={raw_report}",
        ], env=env, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
           text=True, encoding="utf-8", errors="replace")
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
        totals = validate_report(report, manifest)
    except (OSError, ValueError, ET.ParseError) as exc:
        print(f"CI_PYTEST_RESULT=BLOCK ({type(exc).__name__})")
        return result.returncode or 1
    print("CI_PYTEST_RESULT=" + json.dumps(totals, sort_keys=True))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
