import json

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
