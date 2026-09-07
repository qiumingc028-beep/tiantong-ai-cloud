"""Execute every collected test and verify its JUnit result, without a stale total."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from ops.r297_ci_redact import _redact_text, redact


def pytest_collection_finish(session):
    target = os.getenv("CI_PYTEST_COLLECTION_MANIFEST")
    if target:
        Path(target).write_text(json.dumps([item.nodeid for item in session.items]), encoding="utf-8")


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
    env = dict(os.environ, CI_PYTEST_COLLECTION_MANIFEST=str(manifest))
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
