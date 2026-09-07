import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops.ci_pytest_gate import validate_report


@pytest.mark.parametrize("tests,failures,errors,skipped", [
    (2, 1, 0, 0), (2, 0, 1, 0), (2, 0, 0, 1), (1, 0, 0, 0),
])
def test_incomplete_or_nonpassing_execution_cannot_pass(tmp_path, tests, failures, errors, skipped):
    manifest = tmp_path / "nodes.json"
    manifest.write_text(json.dumps(["test_one", "test_two"]))
    report = tmp_path / "junit.xml"
    report.write_text(f'<testsuites><testsuite tests="{tests}" failures="{failures}" errors="{errors}" skipped="{skipped}"/></testsuites>')
    with pytest.raises(ValueError):
        validate_report(report, manifest, minimum=2)


def test_new_tests_are_required_without_changing_a_hardcoded_total(tmp_path):
    manifest = tmp_path / "nodes.json"
    manifest.write_text(json.dumps(["test_one", "test_two", "test_new_security_case"]))
    report = tmp_path / "junit.xml"
    report.write_text('<testsuite tests="3" failures="0" errors="0" skipped="0"/>')
    assert validate_report(report, manifest, minimum=2)["tests"] == 3


@pytest.mark.parametrize("sanitizer_fails", [False, True])
def test_cli_never_publishes_raw_failures_or_relabels_failure_as_pass(tmp_path, monkeypatch, capsys, sanitizer_fails):
    from ops import ci_pytest_gate as gate

    output = tmp_path / "upload"
    monkeypatch.setattr(gate.sys, "argv", ["ci_pytest_gate", str(output)])

    def execute(command, **kwargs):
        assert "-m" in command and "tests/" in command
        assert "-k" not in command and "-x" not in command
        assert kwargs["stdout"] == gate.subprocess.PIPE
        raw = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        assert output not in raw.parents
        raw.write_text('<testsuite tests="1846" failures="1" errors="0" skipped="0">'
                       '<testcase name="security"><failure message="password=ARTIFACTVALUE"/></testcase>'
                       '</testsuite>')
        Path(kwargs["env"]["CI_PYTEST_COLLECTION_MANIFEST"]).write_text(
            json.dumps([f"test_{i}" for i in range(1846)]))
        return SimpleNamespace(returncode=1, stdout="FAILED security: password=LOGVALUE\n")

    monkeypatch.setattr(gate.subprocess, "run", execute)
    if sanitizer_fails:
        def fail(_):
            raise RuntimeError("SANITIZER_FAILURE")
        monkeypatch.setattr(gate, "redact", fail)
    assert gate.main() == 1
    assert "LOGVALUE" not in capsys.readouterr().out
    files = "".join(path.read_text() for path in output.iterdir())
    assert "ARTIFACTVALUE" not in files and "LOGVALUE" not in files
    if not sanitizer_fails:
        import xml.etree.ElementTree as ET
        root = ET.parse(output / "junit.xml").getroot()
        assert root.attrib["failures"] == "1"
