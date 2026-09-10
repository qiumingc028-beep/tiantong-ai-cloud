import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops.ci_pytest_gate import validate_report
from ops.r297_ci_redact import _redact_text


def _ids(nodes):
    from ops import ci_pytest_gate as gate
    return gate._node_identities(nodes)


def _partition_artifacts(root, nodes, *, head="a" * 40, result=0):
    root.mkdir()
    (root / "collected-nodeids.json").write_text(json.dumps(_ids(nodes)))
    (root / "run.json").write_text(json.dumps({"head": head, "run_id": "123", "run_attempt": "1", "exit_code": result}))
    (root / "status.json").write_text(json.dumps({"result": "COMPLETE", "exitstatus": result}))
    (root / "progress.jsonl").write_text("".join(json.dumps({"nodeid_sha256": identity, "phase": "teardown", "outcome": "passed"}) + "\n" for identity in _ids(nodes)))
    (root / "junit.xml").write_text(f'<testsuite tests="{len(nodes)}" failures="0" errors="0" skipped="0"/>')


@pytest.mark.parametrize("defect", [None, "missing", "overlap", "wrong_head", "wrong_attempt", "failed", "cancelled", "missing_report", "wrong_executed"])
def test_split_gate_requires_exact_same_head_union_and_successful_execution(tmp_path, defect):
    from ops import ci_pytest_gate as gate
    full = tmp_path / "full.json"
    full.write_text(json.dumps(_ids(["tests/test_a.py::test_a", "tests/test_b.py::test_b", "tests/test_c.py::test_c"])))
    first, second = tmp_path / "main", tmp_path / "ownership"
    first_nodes = ["tests/test_a.py::test_a", "tests/test_b.py::test_b"]
    second_nodes = ["tests/test_c.py::test_c"]
    if defect == "missing": first_nodes.pop()
    if defect == "overlap": second_nodes.append(first_nodes[0])
    _partition_artifacts(first, first_nodes)
    _partition_artifacts(second, second_nodes, head="b" * 40 if defect == "wrong_head" else "a" * 40, result=1 if defect == "failed" else 0)
    if defect == "wrong_attempt":
        run = json.loads((second / "run.json").read_text()); run["run_attempt"] = "2"
        (second / "run.json").write_text(json.dumps(run))
    if defect == "cancelled": (second / "status.json").write_text('{"result":"INCOMPLETE"}')
    if defect == "missing_report": (second / "junit.xml").unlink()
    if defect == "wrong_executed":
        (second / "progress.jsonl").write_text(json.dumps({"nodeid_sha256": _ids(["tests/test_other.py::test_other"])[0], "phase": "teardown", "outcome": "passed"}) + "\n")
    if defect:
        with pytest.raises((ValueError, OSError)):
            gate.validate_partitions(full, [first, second], head="a" * 40, run_id="123", run_attempt="1")
    else:
        result = gate.validate_partitions(full, [first, second], head="a" * 40, run_id="123", run_attempt="1")
        assert result == {"collected": 3, "executed": 3, "overlap": 0, "missing": 0}


def _start_progress(gate, tmp_path, monkeypatch):
    # Restore the live plugin's session root after this unit test's teardown.
    monkeypatch.setattr(gate, "_PROGRESS_ROOT", gate._PROGRESS_ROOT)
    monkeypatch.setenv("CI_PYTEST_PROGRESS_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("CI_PYTEST_COLLECTION_MANIFEST", str(tmp_path / "nodes.json"))
    gate.pytest_sessionstart(None)


@pytest.mark.parametrize("job_result", ["success", "failure", "cancelled", "skipped", ""])
def test_aggregate_cli_requires_both_job_results_even_when_reports_pass(tmp_path, monkeypatch, job_result):
    from ops import ci_pytest_gate as gate
    first, second = tmp_path / "main", tmp_path / "matrix"
    _partition_artifacts(first, ["test_a"])
    _partition_artifacts(second, ["test_b"])
    monkeypatch.setattr(gate.sys, "argv", ["gate", "--aggregate", str(tmp_path / "aggregate"), str(first), str(second)])
    monkeypatch.setenv("RELEASE_SOURCE_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("CI_MAIN_JOB_RESULT", job_result)
    monkeypatch.setenv("CI_MATRIX_JOB_RESULT", "success")
    monkeypatch.setattr(gate.subprocess, "check_output", lambda *a, **k: "a" * 40)
    def collect(command, **kwargs):
        assert "--collect-only" in command and "tests/" in command
        assert not any(arg.startswith(("--ignore", "-k")) for arg in command)
        Path(kwargs["env"]["CI_PYTEST_COLLECTION_MANIFEST"]).write_text(json.dumps(_ids(["test_a", "test_b"])))
        return SimpleNamespace(returncode=0, stdout="collected")
    monkeypatch.setattr(gate.subprocess, "run", collect)
    assert gate.main() == (0 if job_result == "success" else 1)


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


def test_expensive_postgresql_matrix_can_run_in_parallel_without_omission(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    output = tmp_path / "upload"
    monkeypatch.setattr(gate.sys, "argv", ["ci_pytest_gate", str(output)])
    monkeypatch.setenv("CI_PYTEST_TARGET", "tests/test_task_center_full_entrypoint_ownership.py")
    monkeypatch.delenv("CI_PYTEST_IGNORE", raising=False)
    monkeypatch.setenv("CI_PYTEST_MINIMUM", "1")

    def execute(command, **kwargs):
        assert "tests/test_task_center_full_entrypoint_ownership.py" in command
        assert not any(part.startswith("--ignore=") for part in command)
        raw = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        raw.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0"/>')
        Path(kwargs["env"]["CI_PYTEST_COLLECTION_MANIFEST"]).write_text(json.dumps(["matrix-test"]))
        return SimpleNamespace(returncode=0, stdout="matrix pass\n")

    monkeypatch.setattr(gate.subprocess, "run", execute)
    assert gate.main() == 0


def test_main_suite_ignores_only_the_parallelized_matrix(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    output = tmp_path / "upload"
    monkeypatch.setattr(gate.sys, "argv", ["ci_pytest_gate", str(output)])
    monkeypatch.setenv("CI_PYTEST_IGNORE", "tests/test_task_center_full_entrypoint_ownership.py")
    monkeypatch.setenv("CI_PYTEST_MINIMUM", "1")

    def execute(command, **kwargs):
        assert "tests/" in command
        assert "--ignore=tests/test_task_center_full_entrypoint_ownership.py" in command
        raw = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))
        raw.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0"/>')
        Path(kwargs["env"]["CI_PYTEST_COLLECTION_MANIFEST"]).write_text(json.dumps(["main-test"]))
        return SimpleNamespace(returncode=0, stdout="main pass\n")

    monkeypatch.setattr(gate.subprocess, "run", execute)
    assert gate.main() == 0


def test_progress_survives_an_incomplete_run_and_identifies_last_test(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    _start_progress(gate, tmp_path, monkeypatch)
    gate.pytest_collection_finish(SimpleNamespace(items=[
        SimpleNamespace(nodeid="tests/test_one.py::test_one"),
        SimpleNamespace(nodeid="tests/test_two.py::test_two"),
    ]))
    gate.pytest_runtest_logstart("tests/test_one.py::test_one", None)
    gate.pytest_runtest_logreport(SimpleNamespace(
        when="call", failed=False, skipped=False, nodeid="tests/test_one.py::test_one",
        outcome="passed", duration=1.25,
    ))
    gate.pytest_runtest_teardown(SimpleNamespace(nodeid="tests/test_one.py::test_one"), None)
    gate.pytest_runtest_logreport(SimpleNamespace(
        when="teardown", failed=False, skipped=False, nodeid="tests/test_one.py::test_one",
        outcome="passed", duration=0.25,
    ))
    gate.pytest_runtest_logstart("tests/test_two.py::test_two", None)
    gate.pytest_runtest_teardown(SimpleNamespace(nodeid="tests/test_two.py::test_two"), None)

    status = json.loads((tmp_path / "status.json").read_text())
    assert status["result"] == "INCOMPLETE"
    assert status["last_completed_test"] == "tests/test_one.py::test_one"
    assert status["current_test"] == "tests/test_two.py::test_two"
    assert status["current_phase"] == "teardown"
    assert json.loads((tmp_path / "progress.jsonl").read_text().splitlines()[-1])["phase"] == "teardown"


def test_session_finish_marks_progress_complete(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    _start_progress(gate, tmp_path, monkeypatch)
    gate.pytest_sessionfinish(None, 1)
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["result"] == "COMPLETE" and status["exitstatus"] == 1


def test_passing_teardown_does_not_relabel_failed_test(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    _start_progress(gate, tmp_path, monkeypatch)
    for phase, outcome in (("setup", "passed"), ("call", "failed"), ("teardown", "passed")):
        gate.pytest_runtest_logreport(SimpleNamespace(
            when=phase, failed=outcome == "failed", skipped=False,
            nodeid="tests/test_failure.py::test_failure", outcome=outcome, duration=0.1,
        ))
    assert json.loads((tmp_path / "status.json").read_text())["last_outcome"] == "failed"


def test_progress_path_is_fixed_before_a_test_changes_os_name(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    _start_progress(gate, tmp_path, monkeypatch)
    monkeypatch.setattr(gate.os, "name", "nt")
    gate.pytest_runtest_logreport(SimpleNamespace(
        when="call", failed=False, skipped=False,
        nodeid="tests/test_windows.py::test_windows", outcome="passed", duration=0.1,
    ))
    assert (tmp_path / "progress.jsonl").is_file()
def test_collection_and_execution_keep_exact_identity_without_publishing_secret_nodeids(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate
    _start_progress(gate, tmp_path, monkeypatch)
    nodes = ["tests/test_one.py::test_one[password=FIRSTVALUE]", "tests/test_one.py::test_one[password=SECONDVALUE]"]
    gate.pytest_collection_finish(SimpleNamespace(items=[SimpleNamespace(nodeid=node) for node in nodes]))
    for node in nodes:
        gate.pytest_runtest_logreport(SimpleNamespace(nodeid=node, when="teardown", outcome="passed", duration=0.1))
    content = "".join(path.read_text() for path in tmp_path.iterdir())
    assert "FIRSTVALUE" not in content and "SECONDVALUE" not in content
    assert json.loads((tmp_path / "nodes.json").read_text()) == _ids(nodes)
    assert not set(_ids(nodes)).intersection(hashlib.sha256(node.encode()).hexdigest() for node in nodes)
    rows = [json.loads(line) for line in (tmp_path / "progress.jsonl").read_text().splitlines()]
    assert [row["nodeid_sha256"] for row in rows] == _ids(nodes)
    assert rows[0]["nodeid"] == rows[1]["nodeid"]  # display redaction may collide; identity must not.


def test_anonymous_identity_detects_same_count_replacement_after_redaction():
    from ops import ci_pytest_gate as gate

    original = [
        "tests/test_secret.py::test_case[token=FIRSTVALUE]",
        "tests/test_secret.py::test_case[token=SECONDVALUE]",
    ]
    replaced = [
        original[0],
        "tests/test_secret.py::test_case[token=THIRDVALUE]",
    ]
    assert [_redact_text(node) for node in original] == [
        _redact_text(node) for node in replaced
    ]
    assert gate._node_identities(original) != gate._node_identities(replaced)


def test_actions_requires_ephemeral_identity_key(monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("CI_PYTEST_IDENTITY_KEY", raising=False)
    with pytest.raises(RuntimeError, match="CI_PYTEST_IDENTITY_KEY_MISSING"):
        gate._node_identities(["tests/test_one.py::test_one"])


def test_real_plugin_execution_manifest_survives_nested_progress_tests(tmp_path):
    import os
    import subprocess
    import sys
    env = dict(os.environ, CI_PYTEST_COLLECTION_MANIFEST=str(tmp_path / "nodes.json"),
               CI_PYTEST_PROGRESS_DIRECTORY=str(tmp_path))
    targets = ["test_progress_survives_an_incomplete_run_and_identifies_last_test",
               "test_passing_teardown_does_not_relabel_failed_test",
               "test_progress_path_is_fixed_before_a_test_changes_os_name"]
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "ops.ci_pytest_gate",
                             *["tests/test_ci_pytest_gate.py::" + name for name in targets]],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, "nested plugin run failed; inspect private test report"
    nodes = json.loads((tmp_path / "nodes.json").read_text())
    rows = [json.loads(line) for line in (tmp_path / "progress.jsonl").read_text().splitlines()]
    assert sorted(row["nodeid_sha256"] for row in rows if row["phase"] == "teardown") == sorted(nodes)
    assert len(nodes) == 3
    assert json.loads((tmp_path / "status.json").read_text())["exitstatus"] == 0


def test_progress_does_not_use_product_fault_injected_fsync(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate
    _start_progress(gate, tmp_path, monkeypatch)
    def fail(_fd):
        raise OSError("injected product fsync failure")
    monkeypatch.setattr(gate.os, "fsync", fail)
    gate.pytest_runtest_logreport(SimpleNamespace(nodeid="test_failure", when="teardown", outcome="passed", duration=0.1))
    assert (tmp_path / "progress.jsonl").is_file()
