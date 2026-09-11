import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
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
    digests = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in root.iterdir()}
    (root / "publication.json").write_text(json.dumps({
        "head": head, "run_id": "123", "run_attempt": "1", "partition": "main",
        "result": "PASS", "partition_result": "PASS", "overall_result": "PASS",
        "artifact_result": "PASS", "primary_error": None, "cleanup_error": None,
        "terminal_error": None, "publication_error": None,
        "stage_exit_codes": {"main": 0, "ownership": 0, "aggregate": 0},
        "artifact_sha256": digests,
    }))


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


def _start_progress(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "_r297_isolated_ci_pytest_gate", Path(__file__).parents[1] / "ops" / "ci_pytest_gate.py"
    )
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    monkeypatch.setenv("CI_PYTEST_PROGRESS_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("CI_PYTEST_COLLECTION_MANIFEST", str(tmp_path / "nodes.json"))
    gate.pytest_sessionstart(None)
    return gate


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
    monkeypatch.setenv("CI_PYTEST_CACHE_DIR", str(tmp_path / "aggregate-cache"))
    monkeypatch.setattr(gate.subprocess, "check_output", lambda *a, **k: "a" * 40)
    def collect(command, **kwargs):
        assert "--collect-only" in command and "tests/" in command
        assert not any(arg.startswith(("--ignore", "-k")) for arg in command)
        assert ["-o", f"cache_dir={tmp_path / 'aggregate-cache'}"] == command[-2:]
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
    monkeypatch.setenv("CI_PYTEST_CACHE_DIR", str(tmp_path / "matrix-cache"))

    def execute(command, **kwargs):
        assert "tests/test_task_center_full_entrypoint_ownership.py" in command
        assert not any(part.startswith("--ignore=") for part in command)
        assert ["-o", f"cache_dir={tmp_path / 'matrix-cache'}"] == command[-2:]
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
    gate = _start_progress(tmp_path, monkeypatch)
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
    gate = _start_progress(tmp_path, monkeypatch)
    gate.pytest_sessionfinish(None, 1)
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["result"] == "COMPLETE" and status["exitstatus"] == 1


def test_passing_teardown_does_not_relabel_failed_test(tmp_path, monkeypatch):
    gate = _start_progress(tmp_path, monkeypatch)
    for phase, outcome in (("setup", "passed"), ("call", "failed"), ("teardown", "passed")):
        gate.pytest_runtest_logreport(SimpleNamespace(
            when=phase, failed=outcome == "failed", skipped=False,
            nodeid="tests/test_failure.py::test_failure", outcome=outcome, duration=0.1,
        ))
    assert json.loads((tmp_path / "status.json").read_text())["last_outcome"] == "failed"


def test_progress_path_is_fixed_before_a_test_changes_os_name(tmp_path, monkeypatch):
    gate = _start_progress(tmp_path, monkeypatch)
    monkeypatch.setattr(gate.os, "name", "nt")
    gate.pytest_runtest_logreport(SimpleNamespace(
        when="call", failed=False, skipped=False,
        nodeid="tests/test_windows.py::test_windows", outcome="passed", duration=0.1,
    ))
    assert (tmp_path / "progress.jsonl").is_file()
def test_collection_and_execution_keep_exact_identity_without_publishing_secret_nodeids(tmp_path, monkeypatch):
    gate = _start_progress(tmp_path, monkeypatch)
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


def test_cached_collection_identity_does_not_re_read_removed_key(tmp_path, monkeypatch):
    node = "tests/test_one.py::test_one"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "x" * 43)
    gate = _start_progress(tmp_path, monkeypatch)
    gate.pytest_collection_finish(SimpleNamespace(items=[SimpleNamespace(nodeid=node)]))
    expected = json.loads((tmp_path / "nodes.json").read_text())[0]
    monkeypatch.setattr(
        gate, "_node_identities",
        lambda _nodes: (_ for _ in ()).throw(RuntimeError("CI_PYTEST_IDENTITY_KEY_MISSING")),
    )

    gate.pytest_runtest_logreport(SimpleNamespace(
        nodeid=node, when="teardown", outcome="passed", duration=0.1,
    ))

    row = json.loads((tmp_path / "progress.jsonl").read_text().splitlines()[-1])
    assert row["nodeid_sha256"] == expected


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


def test_actions_requires_ephemeral_identity_key():
    env = dict(os.environ, GITHUB_ACTIONS="true")
    env.pop("CI_PYTEST_IDENTITY_KEY", None)
    result = subprocess.run(
        [sys.executable, "-c", (
            "from ops import ci_pytest_gate as gate\n"
            "try: gate._node_identities(['tests/test_one.py::test_one'])\n"
            "except RuntimeError as exc: raise SystemExit(0 if str(exc) == "
            "'CI_PYTEST_IDENTITY_KEY_MISSING' else 2)\n"
            "raise SystemExit(1)\n"
        )],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_real_plugin_execution_manifest_survives_nested_progress_tests(tmp_path):
    import os
    import subprocess
    import sys
    env = dict(
        os.environ,
        CI_PYTEST_COLLECTION_MANIFEST=str(tmp_path / "nodes.json"),
        CI_PYTEST_PROGRESS_DIRECTORY=str(tmp_path),
        CI_PYTEST_IDENTITY_KEY="x" * 43,
        GITHUB_ACTIONS="true",
    )
    targets = ["test_progress_survives_an_incomplete_run_and_identifies_last_test",
               "test_passing_teardown_does_not_relabel_failed_test",
               "test_progress_path_is_fixed_before_a_test_changes_os_name",
               "test_cached_collection_identity_does_not_re_read_removed_key",
               "test_actions_requires_ephemeral_identity_key"]
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "--noconftest", "-p", "ops.ci_pytest_gate",
                             *["tests/test_ci_pytest_gate.py::" + name for name in targets]],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, "nested plugin run failed; inspect private test report"
    nodes = json.loads((tmp_path / "nodes.json").read_text())
    rows = [json.loads(line) for line in (tmp_path / "progress.jsonl").read_text().splitlines()]
    assert sorted(row["nodeid_sha256"] for row in rows if row["phase"] == "teardown") == sorted(nodes)
    assert len(nodes) == 5
    assert json.loads((tmp_path / "status.json").read_text())["exitstatus"] == 0


def test_actions_keeps_partition_identity_inside_one_runner():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml").read_text()
    assert "pytest-identity:" not in workflow
    assert "needs.pytest-identity.outputs.key" not in workflow
    assert "R297_CI_PYTEST_IDENTITY_ROOT_KEY" not in workflow
    assert workflow.count('CI_PYTEST_IDENTITY_KEY="$(python -c \'import secrets; print(secrets.token_urlsafe(48))\')"') == 1
    assert workflow.count('echo "::add-mask::$CI_PYTEST_IDENTITY_KEY"') == 1
    assert "if [[ ${#CI_PYTEST_IDENTITY_KEY} -lt 64 ]]" in workflow
    assert "export R297_REDACT_EXACT_ENV_NAMES=CI_PYTEST_IDENTITY_KEY" in workflow
    assert "trap 'unset CI_PYTEST_IDENTITY_KEY R297_REDACT_EXACT_ENV_NAMES' EXIT" in workflow
    assert "python -m ops.ci_pytest_gate --partitions" in workflow
    assert "python -m ops.ci_pytest_gate --validate-partition /tmp/r297-ownership-matrix 500" in workflow
    assert "python -m ops.ci_pytest_gate --validate-aggregate /tmp/r297-full-coverage" in workflow
    assert "unset CI_PYTEST_IDENTITY_KEY" in workflow
    assert "name: PostgreSQL ownership matrix" in workflow
    assert "name: Exact full-repository pytest coverage gate" in workflow
    assert "assert run ==" not in workflow
    assert workflow.count("-${{ github.run_attempt }}") >= 5


@pytest.mark.parametrize("mode", ["partition", "aggregate"])
def test_optimized_validator_rejects_invalid_artifact(tmp_path, mode):
    env = dict(os.environ, RELEASE_SOURCE_SHA="a" * 40, GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="2")
    if mode == "partition":
        output = tmp_path / "partition"
        _partition_artifacts(output, ["tests/test_one.py::test_one"])
        command = [sys.executable, "-O", "-m", "ops.ci_pytest_gate", "--validate-partition", str(output), "1"]
    else:
        output = tmp_path / "aggregate"
        output.mkdir()
        (output / "aggregate.json").write_text(json.dumps({
            "head": "a" * 40, "run_id": "123", "run_attempt": "1", "result": "PASS",
            "collected": 1, "executed": 1, "overlap": 0, "missing": 0,
        }))
        (output / "publication.json").write_text(json.dumps({
            "head": "a" * 40, "run_id": "123", "run_attempt": "1", "partition": "aggregate",
            "result": "PASS", "partition_result": "PASS", "overall_result": "PASS",
            "artifact_result": "PASS", "primary_error": None, "cleanup_error": None,
            "terminal_error": None, "publication_error": None,
            "stage_exit_codes": {"main": 0, "ownership": 0, "aggregate": 0},
            "artifact_sha256": {
                "aggregate.json": hashlib.sha256((output / "aggregate.json").read_bytes()).hexdigest(),
            },
        }))
        command = [sys.executable, "-O", "-m", "ops.ci_pytest_gate", "--validate-aggregate", str(output)]
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "CI_PYTEST_VALIDATION=BLOCK" in result.stdout


def test_optimized_validators_accept_same_attempt_valid_artifacts(tmp_path):
    env = dict(os.environ, RELEASE_SOURCE_SHA="a" * 40, GITHUB_RUN_ID="123", GITHUB_RUN_ATTEMPT="2")
    partition = tmp_path / "partition"
    _partition_artifacts(partition, ["tests/test_one.py::test_one"])
    run = json.loads((partition / "run.json").read_text())
    run["run_attempt"] = "2"
    (partition / "run.json").write_text(json.dumps(run))
    publication = json.loads((partition / "publication.json").read_text())
    publication["run_attempt"] = "2"
    publication["artifact_sha256"]["run.json"] = hashlib.sha256((partition / "run.json").read_bytes()).hexdigest()
    (partition / "publication.json").write_text(json.dumps(publication))
    aggregate = tmp_path / "aggregate"
    aggregate.mkdir()
    (aggregate / "aggregate.json").write_text(json.dumps({
        "head": "a" * 40, "run_id": "123", "run_attempt": "2", "result": "PASS",
        "collected": 1, "executed": 1, "overlap": 0, "missing": 0,
    }))
    (aggregate / "publication.json").write_text(json.dumps({
        "head": "a" * 40, "run_id": "123", "run_attempt": "2", "partition": "aggregate",
        "result": "PASS", "partition_result": "PASS", "overall_result": "PASS",
        "artifact_result": "PASS", "primary_error": None, "cleanup_error": None,
        "terminal_error": None, "publication_error": None,
        "stage_exit_codes": {"main": 0, "ownership": 0, "aggregate": 0},
        "artifact_sha256": {
            "aggregate.json": hashlib.sha256((aggregate / "aggregate.json").read_bytes()).hexdigest(),
        },
    }))
    for command in (
        [sys.executable, "-O", "-m", "ops.ci_pytest_gate", "--validate-partition", str(partition), "1"],
        [sys.executable, "-O", "-m", "ops.ci_pytest_gate", "--validate-aggregate", str(aggregate)],
    ):
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        assert result.returncode == 0 and "CI_PYTEST_VALIDATION=PASS" in result.stdout


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="CI partition supervisor runs on ubuntu")
def test_partition_cleanup_terminates_and_reaps_its_process_group(tmp_path):
    from ops import ci_pytest_gate as gate

    child_pid = tmp_path / "child.pid"
    script = (
        "import pathlib,signal,subprocess,sys,time;"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "child=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)']);"
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid));"
        "time.sleep(60)"
    )
    process = subprocess.Popen([sys.executable, "-c", script], start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not child_pid.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        descendant = int(child_pid.read_text())
        records = [{
            "name": "partition", "process": process, "pid": process.pid,
            "pgid": os.getpgid(process.pid), "owns_group": True,
            "process_identity": gate._process_identity(process.pid),
        }]
        gate._terminate_processes(records, grace_seconds=0.05)
        assert process.returncode == -signal.SIGKILL
        assert descendant != process.pid
        assert not gate._group_alive(records[0]["pgid"])
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="CI partition supervisor runs on ubuntu")
def test_partition_cleanup_allows_graceful_term_before_kill(tmp_path):
    from ops import ci_pytest_gate as gate

    ready = tmp_path / "ready"
    script = (
        "import pathlib,signal,sys,time;"
        "signal.signal(signal.SIGTERM,lambda *_:sys.exit(0));"
        "blocked=signal.pthread_sigmask(signal.SIG_BLOCK,[]);"
        f"pathlib.Path({str(ready)!r}).write_text(','.join(str(item.value) for item in blocked));"
        "time.sleep(60)"
    )
    records = []
    record = gate._start_managed_process(
        "partition", [sys.executable, "-c", script], dict(os.environ), records,
    )
    process = record["process"]
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.read_text() == ""
        gate._terminate_processes(records, grace_seconds=0.5)
        assert process.returncode == 0
        assert not gate._group_alive(record["pgid"])
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def test_partition_environments_isolate_databases_redis_caches_and_outputs(tmp_path):
    from ops import ci_pytest_gate as gate

    main, ownership, aggregate = gate._partition_environments(tmp_path)
    assert main["V2_ALPHA_POSTGRES_ADMIN_URL"].endswith(":5432/postgres")
    assert ownership["V2_ALPHA_POSTGRES_ADMIN_URL"].endswith(":5433/postgres")
    assert main["REDIS_URL"].endswith(":6379/0")
    assert ownership["REDIS_URL"].endswith(":6380/0")
    caches = {main["CI_PYTEST_CACHE_DIR"], ownership["CI_PYTEST_CACHE_DIR"], aggregate["CI_PYTEST_CACHE_DIR"]}
    assert len(caches) == 3
    assert all(Path(path).parent == tmp_path for path in caches)


@pytest.mark.parametrize("encoding", ["raw", "base64", "hex", "mixed_hex"])
def test_partition_artifact_scan_rejects_identity_key_encodings(tmp_path, monkeypatch, encoding):
    from ops import ci_pytest_gate as gate

    key = "identity-key-" + "x" * 52
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", key)
    hex_value = key.encode().hex()
    value = {
        "raw": key,
        "base64": base64.b64encode(key.encode()).decode(),
        "hex": hex_value,
        "mixed_hex": "".join(char.upper() if index % 2 else char for index, char in enumerate(hex_value)),
    }[encoding]
    output = tmp_path / "output"
    output.mkdir()
    (output / "artifact.txt").write_text(value)
    with pytest.raises(RuntimeError, match="CI_PYTEST_IDENTITY_ARTIFACT_LEAK"):
        gate._scan_identity_key([output])


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="CI partition supervisor runs on ubuntu")
def test_partition_start_failure_reaps_already_started_group(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    real_popen = subprocess.Popen
    started = []

    def start(command, **kwargs):
        if started:
            raise OSError("injected second partition start failure")
        process = real_popen(
            [sys.executable, "-c", "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"],
            start_new_session=kwargs["start_new_session"],
        )
        started.append(process)
        return process

    monkeypatch.setattr(gate.subprocess, "Popen", start)
    monkeypatch.setattr(gate.sys, "argv", [
        "gate", "--partitions", str(tmp_path / "main"), str(tmp_path / "ownership"), str(tmp_path / "aggregate"),
    ])
    assert gate._partitions_main() == 1
    assert started[0].poll() is not None
    state = json.loads((tmp_path / "aggregate" / "processes.json").read_text())
    assert state["phase"] == "failed" and state["processes"][0]["exit_code"] is not None
    receipt = json.loads((tmp_path / "aggregate-publish" / "publication.json").read_text())
    assert receipt["primary_error"] == "PYTEST_SUPERVISOR_OS_ERROR"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="CI partition supervisor runs on ubuntu")
def test_partition_supervisor_handles_term_and_reaps_both_groups(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "k" * 64)
    real_popen = subprocess.Popen
    started = []
    both_started = threading.Event()

    def start(command, **kwargs):
        ready = tmp_path / f"ready-{len(started)}"
        process = real_popen(
            [sys.executable, "-c", (
                "import pathlib,signal,time;"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                f"pathlib.Path({str(ready)!r}).write_text('ready');"
                "time.sleep(60)"
            )],
            start_new_session=kwargs["start_new_session"],
        )
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.is_file()
        started.append(process)
        if len(started) == 2:
            both_started.set()
        return process

    def cancel():
        assert both_started.wait(5)
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(gate.subprocess, "Popen", start)
    monkeypatch.setattr(gate, "_PROCESS_TERM_GRACE_SECONDS", 0.05)
    monkeypatch.setattr(gate.sys, "argv", [
        "gate", "--partitions", str(tmp_path / "main"), str(tmp_path / "ownership"), str(tmp_path / "aggregate"),
    ])
    thread = threading.Thread(target=cancel)
    thread.start()
    assert gate._partitions_main() == 128 + signal.SIGTERM
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert all(process.returncode in {-signal.SIGTERM, -signal.SIGKILL} for process in started)
    state = json.loads((tmp_path / "aggregate" / "processes.json").read_text())
    assert state["phase"] == "cancelled"


def test_progress_does_not_use_product_fault_injected_fsync(tmp_path, monkeypatch):
    gate = _start_progress(tmp_path, monkeypatch)
    def fail(_fd):
        raise OSError("injected product fsync failure")
    monkeypatch.setattr(gate.os, "fsync", fail)
    gate.pytest_runtest_logreport(SimpleNamespace(nodeid="test_failure", when="teardown", outcome="passed", duration=0.1))
    assert (tmp_path / "progress.jsonl").is_file()


def test_workflow_uploads_only_supervisor_published_artifacts():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml").read_text()
    assert "/tmp/r297-publish-bundle/main/" in workflow
    assert "/tmp/r297-publish-bundle/ownership/" in workflow
    assert "/tmp/r297-publish-bundle/aggregate/" in workflow
    for unsafe in (
        "path: /tmp/r297-pytest/",
        "path: /tmp/r297-ownership-matrix/",
        "path: /tmp/r297-full-coverage/",
    ):
        assert unsafe not in workflow
    assert "id: pytest_gate" in workflow
    assert "--validate-publication" not in workflow
    assert workflow.count("steps.pytest_gate.outputs.publication_ready == 'true'") == 3
    assert "base.pop(\"GITHUB_OUTPUT\", None)" in Path("ops/ci_pytest_gate.py").read_text()


def test_polluted_work_output_can_only_publish_fixed_block_receipt(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    key = "identity-key-" + "x" * 52
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", key)
    source = tmp_path / "work"
    source.mkdir()
    (source / "pytest.log").write_text(key)
    published = tmp_path / "published"

    result = gate.publish_outputs(
        [(source, published, {"pytest.log"})],
        identity={"head": "a" * 40, "run_id": "123", "run_attempt": "2"},
        result="PASS",
        primary_error=None,
        cleanup_error=None,
        stage_exit_codes={"main": 0, "ownership": 0, "aggregate": 0},
    )

    assert result == "UNPUBLISHABLE"
    assert {path.name for path in published.iterdir()} == {"publication.json"}
    receipt = json.loads((published / "publication.json").read_text())
    assert receipt["result"] == "BLOCK"
    assert receipt["primary_error"] is None
    assert receipt["publication_error"] == "CI_PYTEST_IDENTITY_ARTIFACT_LEAK"
    assert key not in (published / "publication.json").read_text()


def test_copy_stage_rejects_mixed_case_hex_even_if_initial_scan_is_bypassed(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    key = "identity-key-" + "x" * 52
    mixed_hex = "".join(
        char.upper() if index % 2 else char
        for index, char in enumerate(key.encode().hex())
    )
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", key)
    monkeypatch.setattr(gate, "_scan_identity_key", lambda _outputs: None)
    source = tmp_path / "work"
    source.mkdir()
    (source / "pytest.log").write_text(mixed_hex)
    published = tmp_path / "published"

    assert gate.publish_outputs(
        [(source, published, {"pytest.log"})],
        identity={"head": "a" * 40, "run_id": "123", "run_attempt": "2"},
        result="PASS", primary_error=None, cleanup_error=None,
        stage_exit_codes={"main": 0, "ownership": 0, "aggregate": 0},
    ) == "UNPUBLISHABLE"
    assert {path.name for path in published.iterdir()} == {"publication.json"}


def test_nonfresh_publish_target_fails_without_mutating_existing_content(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "identity-key-" + "x" * 52)
    source = tmp_path / "work"
    source.mkdir()
    (source / "pytest.log").write_text("safe")
    published = tmp_path / "published"
    published.mkdir()
    sentinel = published / "preexisting.txt"
    sentinel.write_text("must remain byte-for-byte")

    assert gate.publish_outputs(
        [(source, published, {"pytest.log"})],
        identity={"head": "a" * 40, "run_id": "123", "run_attempt": "2"},
        result="PASS", primary_error=None, cleanup_error=None,
        stage_exit_codes={"main": 0, "ownership": 0, "aggregate": 0},
    ) == "UNPUBLISHABLE"
    assert sentinel.read_text() == "must remain byte-for-byte"
    assert {path.name for path in published.iterdir()} == {"preexisting.txt"}


def test_concurrent_publish_target_is_preserved_without_partial_siblings(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "identity-key-" + "x" * 52)
    source = tmp_path / "work"
    source.mkdir()
    (source / "pytest.log").write_text("safe")
    published = tmp_path / "published"
    real_contains = gate._contains_identity_key
    calls = 0

    def create_competing_target(payload):
        nonlocal calls
        calls += 1
        if calls == 2:
            published.mkdir()
            (published / "concurrent.txt").write_text("belongs to another writer")
        return real_contains(payload)

    monkeypatch.setattr(gate, "_contains_identity_key", create_competing_target)
    assert gate.publish_outputs(
        [(source, published, {"pytest.log"})],
        identity={"head": "a" * 40, "run_id": "123", "run_attempt": "2"},
        result="PASS", primary_error=None, cleanup_error=None,
        stage_exit_codes={"main": 0, "ownership": 0, "aggregate": 0},
    ) == "UNPUBLISHABLE"
    assert (published / "concurrent.txt").read_text() == "belongs to another writer"
    assert {path.name for path in published.iterdir()} == {"concurrent.txt"}


def test_cleanup_refuses_replaced_directory_identity(tmp_path):
    from ops import ci_pytest_gate as gate

    target = tmp_path / "owned"
    owned = gate._new_owned_directory(target)
    gate._write_owned_file(owned, "ours.txt", b"ours")
    target.rename(tmp_path / "moved-owned")
    target.mkdir()
    (target / "concurrent.txt").write_text("must remain")

    with pytest.raises(RuntimeError, match="PYTEST_PUBLICATION_CLEANUP_FAILED"):
        gate._cleanup_owned_directory(owned)
    assert (target / "concurrent.txt").read_text() == "must remain"


def test_write_failure_registers_created_file_for_fd_bound_cleanup(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    target = tmp_path / "owned"
    owned = gate._new_owned_directory(target)
    monkeypatch.setattr(gate.os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("injected")))

    with pytest.raises(OSError, match="injected"):
        gate._write_owned_file(owned, "partial.txt", b"partial")
    assert "partial.txt" in owned["files"]
    gate._cleanup_owned_directory(owned)
    assert not (target / "partial.txt").exists()


def test_cleanup_closes_directory_fd_when_path_identity_check_fails(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    owned = gate._new_owned_directory(tmp_path / "owned")
    monkeypatch.setattr(gate, "_path_identity", lambda _path: (_ for _ in ()).throw(OSError("injected")))

    with pytest.raises(RuntimeError, match="PYTEST_PUBLICATION_CLEANUP_FAILED"):
        gate._cleanup_owned_directory(owned)
    assert "fd" not in owned


def test_normal_failure_publishes_scanned_fixed_reports_without_pass(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "identity-key-" + "x" * 52)
    source = tmp_path / "work"
    source.mkdir()
    (source / "pytest.log").write_text("safe failure summary")
    (source / "junit.xml").write_text('<testsuite tests="1" failures="1"/>')
    published = tmp_path / "published"
    assert gate.publish_outputs(
        [(source, published, {"pytest.log", "junit.xml"})],
        identity={"head": "a" * 40, "run_id": "123", "run_attempt": "2"},
        result="BLOCK", primary_error="PYTEST_MAIN_FAILED", cleanup_error=None,
        stage_exit_codes={"main": 1, "ownership": 0, "aggregate": 1},
    ) == "BLOCK"
    assert {path.name for path in published.iterdir()} == {"pytest.log", "junit.xml", "publication.json"}
    assert json.loads((published / "publication.json").read_text())["result"] == "BLOCK"


def test_safe_ownership_partition_can_pass_while_overall_result_blocks(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "identity-key-" + "x" * 52)
    specs = []
    for index, allowed in enumerate((gate._PARTITION_FILES, gate._PARTITION_FILES, gate._AGGREGATE_FILES)):
        source = tmp_path / f"work-{index}"
        target = tmp_path / f"publish-{index}"
        source.mkdir()
        name = next(iter(allowed))
        (source / name).write_text("safe failure evidence")
        specs.append((source, target, allowed))

    assert gate.publish_outputs(
        specs,
        identity={"head": "a" * 40, "run_id": "123", "run_attempt": "2"},
        result="BLOCK", primary_error="PYTEST_MAIN_FAILED", cleanup_error=None,
        stage_exit_codes={"main": 1, "ownership": 0, "aggregate": 1},
    ) == "BLOCK"
    main, ownership, aggregate = [target for _, target, _ in specs]
    gate.validate_publication_outputs(
        [main, ownership, aggregate], head="a" * 40, run_id="123", run_attempt="2",
    )
    gate._validate_publication(ownership, head="a" * 40, run_id="123", run_attempt="2")
    for blocked in (main, aggregate):
        with pytest.raises(ValueError, match="PYTEST_PUBLICATION_INVALID"):
            gate._validate_publication(blocked, head="a" * 40, run_id="123", run_attempt="2")
    receipts = [json.loads((target / "publication.json").read_text()) for target in (main, ownership, aggregate)]
    assert [receipt["partition_result"] for receipt in receipts] == ["BLOCK", "PASS", "BLOCK"]
    assert {receipt["artifact_result"] for receipt in receipts} == {"PASS"}
    assert {receipt["overall_result"] for receipt in receipts} == {"BLOCK"}


def test_final_publication_validation_rejects_mixed_case_hex(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    key = "identity-key-" + "x" * 52
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", key)
    specs = []
    for index, (allowed, name) in enumerate((
        (gate._PARTITION_FILES, "pytest.log"),
        (gate._PARTITION_FILES, "pytest.log"),
        (gate._AGGREGATE_FILES, "aggregate.json"),
    )):
        source = tmp_path / f"work-{index}"
        target = tmp_path / f"publish-{index}"
        source.mkdir()
        (source / name).write_text("safe")
        specs.append((source, target, allowed))
    assert gate.publish_outputs(
        specs,
        identity={"head": "a" * 40, "run_id": "123", "run_attempt": "2"},
        result="PASS", primary_error=None, cleanup_error=None,
        stage_exit_codes={"main": 0, "ownership": 0, "aggregate": 0},
    ) == "PASS"
    hexadecimal = key.encode().hex()
    mixed_hex = "".join(char.upper() if index % 2 else char for index, char in enumerate(hexadecimal))
    (specs[0][1] / "pytest.log").write_text(mixed_hex)
    receipt_path = specs[0][1] / "publication.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["artifact_sha256"]["pytest.log"] = hashlib.sha256(
        (specs[0][1] / "pytest.log").read_bytes()
    ).hexdigest()
    receipt_path.write_text(json.dumps(receipt))

    with pytest.raises(RuntimeError, match="CI_PYTEST_IDENTITY_ARTIFACT_LEAK"):
        gate.validate_publication_outputs(
            [target for _, target, _ in specs], head="a" * 40, run_id="123", run_attempt="2",
        )


def test_aggregate_validator_rejects_intermediate_pass_without_final_publication(tmp_path):
    from ops import ci_pytest_gate as gate

    output = tmp_path / "aggregate"
    output.mkdir()
    (output / "aggregate.json").write_text(json.dumps({
        "head": "a" * 40, "run_id": "123", "run_attempt": "2", "result": "PASS",
        "collected": 1, "executed": 1, "overlap": 0, "missing": 0,
    }))
    with pytest.raises(ValueError, match="PYTEST_PUBLICATION_INVALID"):
        gate.validate_aggregate_output(output, head="a" * 40, run_id="123", run_attempt="2")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="CI partition supervisor runs on ubuntu")
@pytest.mark.parametrize("stage", ["main", "ownership", "aggregate"])
def test_supervisor_deadline_reaps_descendants_and_preserves_timeout_code(tmp_path, stage, monkeypatch):
    from ops import ci_pytest_gate as gate

    child_pid = tmp_path / "child.pid"
    script = (
        "import pathlib,signal,subprocess,sys,time;"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "child=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)']);"
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid));"
        "time.sleep(60)"
    )
    records = []
    record = gate._start_managed_process(stage, [sys.executable, "-c", script], dict(os.environ), records)
    try:
        deadline = time.monotonic() + 5
        while not child_pid.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert child_pid.is_file()
        with pytest.raises(gate._SupervisorFailure, match=f"PYTEST_{stage.upper()}_TIMEOUT"):
            gate._wait_managed([record], {stage: 0.05})
        gate._terminate_processes(records, grace_seconds=0.05)
        assert record["process"].returncode == -signal.SIGKILL
        assert not gate._group_alive(record["pgid"])
        monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "k" * 64)
        identity = {"head": "a" * 40, "run_id": "123", "run_attempt": "1"}
        specs = []
        for index, allowed in enumerate((gate._PARTITION_FILES, gate._PARTITION_FILES, gate._AGGREGATE_FILES)):
            source = tmp_path / f"work-{index}"
            target = tmp_path / f"publish-{index}"
            source.mkdir()
            (source / next(iter(allowed))).write_text("safe")
            specs.append((source, target, allowed))
        exits = {"main": 0, "ownership": 0, "aggregate": 0}
        exits[stage] = record["process"].returncode
        assert gate.publish_outputs(
            specs, identity=identity, result="BLOCK", primary_error=f"PYTEST_{stage.upper()}_TIMEOUT",
            terminal_error=f"PYTEST_{stage.upper()}_TIMEOUT", cleanup_error=None,
            stage_exit_codes=exits,
        ) == "BLOCK"
        gate.validate_publication_outputs([target for _, target, _ in specs], **identity)
    finally:
        if record["process"].poll() is None:
            os.killpg(record["pgid"], signal.SIGKILL)
            record["process"].wait()


def test_publication_keeps_primary_failure_when_cleanup_also_fails(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "identity-key-" + "x" * 52)
    source = tmp_path / "work"
    source.mkdir()
    (source / "run.json").write_text("{}")
    published = tmp_path / "published"
    gate.publish_outputs(
        [(source, published, {"run.json"})],
        identity={"head": "a" * 40, "run_id": "123", "run_attempt": "2"},
        result="BLOCK",
        primary_error="PYTEST_MAIN_TIMEOUT",
        cleanup_error="PYTEST_PROCESS_REAP_FAILED",
        stage_exit_codes={"main": None, "ownership": 1, "aggregate": None},
    )
    receipt = json.loads((published / "publication.json").read_text())
    assert receipt["primary_error"] == "PYTEST_MAIN_TIMEOUT"
    assert receipt["cleanup_error"] == "PYTEST_PROCESS_REAP_FAILED"
    assert receipt["result"] == "BLOCK"


def test_cleanup_only_failure_is_recorded_once_without_becoming_primary(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "identity-key-" + "x" * 52)
    source = tmp_path / "work"
    source.mkdir()
    (source / "run.json").write_text("{}")
    published = tmp_path / "published"

    gate.publish_outputs(
        [(source, published, {"run.json"})],
        identity={"head": "a" * 40, "run_id": "123", "run_attempt": "2"},
        result="BLOCK", primary_error=None, cleanup_error="PYTEST_PROCESS_REAP_FAILED",
        stage_exit_codes={"main": 0, "ownership": 0, "aggregate": None},
    )
    receipt = json.loads((published / "publication.json").read_text())
    assert receipt["primary_error"] is None
    assert receipt["cleanup_error"] == "PYTEST_PROCESS_REAP_FAILED"
    assert receipt["publication_error"] is None
    assert "error" not in receipt


def test_initial_reap_failure_does_not_become_primary_error(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("RELEASE_SOURCE_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "x" * 64)

    class Process:
        def __init__(self, pid):
            self.pid = pid

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    starts = 0

    def popen(command, **_kwargs):
        nonlocal starts
        starts += 1
        Path(command[-1]).mkdir(parents=True, exist_ok=True)
        return Process(54000 + starts)

    def complete(records, _timeouts):
        for record in records:
            record["exit_code"] = 0
        return [0 for _ in records]

    cleanup_calls = 0

    def cleanup(*_args, **_kwargs):
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise RuntimeError("PYTEST_PROCESS_REAP_FAILED")

    monkeypatch.setattr(gate.subprocess, "Popen", popen)
    monkeypatch.setattr(gate, "_process_identity", lambda pid: str(pid))
    monkeypatch.setattr(gate, "_wait_managed", complete)
    monkeypatch.setattr(gate, "_terminate_processes", cleanup)
    outputs = [tmp_path / name for name in ("main", "ownership", "aggregate")]
    monkeypatch.setattr(gate.sys, "argv", ["gate", "--partitions", *map(str, outputs)])

    assert gate.main() == 1
    receipt = json.loads((tmp_path / "aggregate-publish" / "publication.json").read_text())
    assert receipt["primary_error"] is None
    assert receipt["cleanup_error"] == "PYTEST_PROCESS_REAP_FAILED"
    assert receipt["publication_error"] is None


def test_aggregate_fixed_set_includes_the_collected_manifest(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    assert "full-collected-nodeids.display.json" in gate._AGGREGATE_FILES
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "identity-key-" + "x" * 52)
    source = tmp_path / "work"
    source.mkdir()
    for name in gate._AGGREGATE_FILES:
        (source / name).write_text("{}")
    (source / "full-collected-nodeids.json").write_text("[]")
    published = tmp_path / "published"
    result = gate.publish_outputs(
        [(source, published, gate._AGGREGATE_FILES)],
        identity={"head": "a" * 40, "run_id": "123", "run_attempt": "2"},
        result="PASS", primary_error=None, cleanup_error=None,
        stage_exit_codes={"main": 0, "ownership": 0, "aggregate": 0},
    )
    assert result == "PASS"
    assert (published / "full-collected-nodeids.json").is_file()


def test_unexpected_exception_keeps_its_safe_type_without_message():
    from ops import ci_pytest_gate as gate

    assert gate._error_code(OSError("password=SHOULD_NOT_APPEAR")) == "PYTEST_SUPERVISOR_OS_ERROR"


def test_cache_cleanup_error_is_recorded_without_replacing_first_stage_failure(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("RELEASE_SOURCE_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "x" * 64)
    calls = []

    class Process:
        def __init__(self, returncode):
            self.pid = 51000 + len(calls)
            self.returncode = returncode

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

    def popen(command, **_kwargs):
        name = "aggregate" if "--aggregate" in command else ("main" if not calls else "ownership")
        output = Path(command[4] if name == "aggregate" else command[-1])
        output.mkdir(parents=True, exist_ok=True)
        calls.append(name)
        return Process(1 if name == "main" else 0)

    class CacheDirectory:
        name = str(tmp_path / "cache")

        def __init__(self, **_kwargs):
            Path(self.name).mkdir()

        def cleanup(self):
            raise RuntimeError("PYTEST_CACHE_CLEANUP_FAILED")

    monkeypatch.setattr(gate.subprocess, "Popen", popen)
    monkeypatch.setattr(gate, "_process_identity", lambda pid: str(pid))
    monkeypatch.setattr(gate, "_observe_process_exit", lambda record: record["process"].poll())
    monkeypatch.setattr(gate.tempfile, "TemporaryDirectory", CacheDirectory)
    monkeypatch.setattr(gate, "_terminate_processes", lambda *_args, **_kwargs: None)
    outputs = [tmp_path / name for name in ("main", "ownership", "aggregate")]
    monkeypatch.setattr(gate.sys, "argv", ["gate", "--partitions", *map(str, outputs)])

    assert gate.main() == 1
    receipt = json.loads((tmp_path / "aggregate-publish" / "publication.json").read_text())
    assert receipt["primary_error"] == "PYTEST_MAIN_FAILED"
    assert receipt["cleanup_error"] == "PYTEST_CACHE_CLEANUP_FAILED"
    assert {path.name for path in (tmp_path / "aggregate-publish").iterdir()} == {"publication.json"}


def test_publication_validator_rejects_cross_stage_state_mismatch(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "identity-key-" + "x" * 52)
    outputs = []
    for index in range(3):
        output = tmp_path / str(index)
        output.mkdir()
        (output / "publication.json").write_text(json.dumps({
            "head": "a" * 40, "run_id": "123", "run_attempt": "2",
            "partition": ("main", "ownership", "aggregate")[index],
            "result": "BLOCK", "partition_result": "BLOCK", "overall_result": "BLOCK",
                "artifact_result": "BLOCK",
                "primary_error": "PYTEST_MAIN_FAILED",
                "terminal_error": None, "cleanup_error": None, "publication_error": None,
            "stage_exit_codes": {"main": 1, "ownership": 0, "aggregate": index},
            "artifact_sha256": {},
        }))
        outputs.append(output)
    with pytest.raises(ValueError, match="PYTEST_PUBLICATION_STATE_MISMATCH"):
        gate.validate_publication_outputs(outputs, head="a" * 40, run_id="123", run_attempt="2")


def test_timeout_does_not_replace_an_earlier_stage_failure():
    from ops import ci_pytest_gate as gate

    class Process:
        def __init__(self, value): self.value = value
        def poll(self): return self.value

    started = time.monotonic() - 1
    records = [
        {"name": "main", "process": Process(1), "started_at": started},
        {"name": "ownership", "process": Process(None), "started_at": started},
    ]
    with pytest.raises(gate._SupervisorFailure, match="PYTEST_MAIN_FAILED"):
        gate._wait_managed(records, {"main": 0.01, "ownership": 0.01})


@pytest.mark.skipif(os.name == "nt", reason="CI partition supervisor runs on ubuntu")
def test_wait_observes_exit_without_reaping_the_process_group_leader(monkeypatch):
    from ops import ci_pytest_gate as gate

    class Process:
        def poll(self):
            raise AssertionError("poll would reap the ownership token")

    record = {
        "name": "main", "process": Process(), "pid": 123, "pgid": 123,
        "started_at": time.monotonic(), "owns_group": True,
    }
    status = SimpleNamespace(si_code=os.CLD_EXITED, si_status=0)
    monkeypatch.setattr(gate.os, "waitid", lambda *_args: status, raising=False)
    monkeypatch.setattr(gate.os, "P_PID", 1, raising=False)
    monkeypatch.setattr(gate.os, "WEXITED", 1, raising=False)
    monkeypatch.setattr(gate.os, "WNOHANG", 1, raising=False)
    monkeypatch.setattr(gate.os, "WNOWAIT", 1, raising=False)
    monkeypatch.setattr(gate.os, "CLD_EXITED", 1, raising=False)

    assert gate._wait_managed([record], {"main": 1}) == [0]
    assert record["exit_code"] == 0
    assert record.get("reaped") is not True


@pytest.mark.skipif(os.name == "nt", reason="CI partition supervisor runs on ubuntu")
def test_cleanup_signals_only_while_unreaped_leader_still_owns_pgid(monkeypatch):
    from ops import ci_pytest_gate as gate

    class Process:
        def __init__(self):
            self.waited = False
            self.returncode = None

        def poll(self):
            self.waited = True
            return 0

        def wait(self, timeout=None):
            self.waited = True
            self.returncode = 0
            return 0

    process = Process()
    record = {
        "name": "main", "process": process, "pid": 123, "pgid": 123,
        "process_identity": "start-1", "owns_group": True,
    }
    signals = []
    monkeypatch.setattr(gate.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(gate, "_process_identity", lambda _pid: "start-1")

    def signal_owned_group(pgid, signum):
        assert not process.waited
        signals.append((pgid, signum))

    monkeypatch.setattr(gate.os, "killpg", signal_owned_group)
    gate._terminate_processes([record], grace_seconds=0)

    assert signals == [(123, signal.SIGTERM), (123, signal.SIGKILL)]
    assert process.waited and record["reaped"] is True


def test_cleanup_never_kills_a_reused_linux_process_group(monkeypatch):
    from ops import ci_pytest_gate as gate

    class Process:
        def wait(self, timeout=None): return 0

    record = {
        "name": "main", "process": Process(), "pid": 123, "pgid": 123,
        "process_identity": "old", "owns_group": True,
    }
    ownership = iter([True, False])
    members = iter([{(123, "old")}, {(999, "new")}])
    signals = []
    clock = iter([0, 0, 0, 2])
    monkeypatch.setattr(gate.sys, "platform", "linux")
    monkeypatch.setattr(gate, "_owned_process_group", lambda _record: next(ownership))
    monkeypatch.setattr(gate, "_linux_group_members", lambda _pgid: next(members))
    monkeypatch.setattr(gate, "_group_alive", lambda _pgid: True)
    monkeypatch.setattr(gate.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(gate.os, "killpg", lambda pgid, signum: signals.append((pgid, signum)))

    with pytest.raises(RuntimeError, match="PYTEST_PROCESS_REAP_FAILED"):
        gate._terminate_processes([record], grace_seconds=0)
    assert signals == [(123, signal.SIGTERM)]


def test_reaped_process_group_is_not_targeted_twice(monkeypatch):
    from ops import ci_pytest_gate as gate

    class Process:
        def __init__(self): self.waits = 0
        def poll(self): return 0
        def wait(self, timeout=None): self.waits += 1; return 0

    process = Process()
    record = {"name": "main", "process": process, "pid": 1, "pgid": 1, "reaped": True}
    monkeypatch.setattr(gate, "_group_alive", lambda _pgid: False)
    gate._terminate_processes([record], grace_seconds=0)
    gate._terminate_processes([record], grace_seconds=0)
    assert process.waits == 0 and record["reaped"] is True


def test_partition_failure_survives_process_reap_failure(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("RELEASE_SOURCE_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "x" * 64)
    calls = []

    class Process:
        def __init__(self, returncode):
            self.pid = 52000 + len(calls)
            self.returncode = returncode

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

    def popen(command, **_kwargs):
        output = Path(command[-1])
        output.mkdir(parents=True, exist_ok=True)
        calls.append(output.name)
        return Process(1 if len(calls) == 1 else 0)

    def fail_reap(*_args, **_kwargs):
        raise RuntimeError("PYTEST_PROCESS_REAP_FAILED")

    monkeypatch.setattr(gate.subprocess, "Popen", popen)
    monkeypatch.setattr(gate, "_process_identity", lambda pid: str(pid))
    monkeypatch.setattr(gate, "_observe_process_exit", lambda record: record["process"].poll())
    monkeypatch.setattr(gate, "_terminate_processes", fail_reap)
    outputs = [tmp_path / name for name in ("main", "ownership", "aggregate")]
    monkeypatch.setattr(gate.sys, "argv", ["gate", "--partitions", *map(str, outputs)])

    assert gate.main() == 1
    receipt = json.loads((tmp_path / "aggregate-publish" / "publication.json").read_text())
    assert receipt["primary_error"] == "PYTEST_MAIN_FAILED"
    assert receipt["cleanup_error"] == "PYTEST_PROCESS_REAP_FAILED"


def test_identity_scan_rejects_uppercase_hex(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate
    key = "k" * 64
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", key)
    (tmp_path / "report.txt").write_text(key.encode().hex().upper())
    with pytest.raises(RuntimeError, match="CI_PYTEST_IDENTITY_ARTIFACT_LEAK"):
        gate._scan_identity_key([tmp_path])


def test_publication_failure_preserves_preexisting_target(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "k" * 64)
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    (source / "unexpected").write_text("x")
    target.mkdir()
    marker = target / "owned-by-another-attempt"
    marker.write_text("keep")
    assert gate.publish_outputs(
        [(source, target, {"report"})], identity=gate._run_identity(), result="BLOCK",
        primary_error="PYTEST_MAIN_FAILED", cleanup_error=None,
        stage_exit_codes={"main": 1, "ownership": 0, "aggregate": 1},
    ) == "UNPUBLISHABLE"
    assert marker.read_text() == "keep"


def test_multi_output_publication_commits_one_shared_root(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "k" * 64)
    identity = {"head": "a" * 40, "run_id": "123", "run_attempt": "1"}
    sources = []
    for name in ("main", "ownership", "aggregate"):
        source = tmp_path / f"work-{name}"
        source.mkdir()
        (source / "report").write_text(name)
        sources.append((source, tmp_path / "publish" / name, {"report"}))
    assert gate.publish_outputs(
        sources, identity=identity, result="PASS", primary_error=None, cleanup_error=None,
        stage_exit_codes={"main": 0, "ownership": 0, "aggregate": 0},
        atomic_root=tmp_path / "publish",
    ) == "PASS"
    assert {path.name for path in (tmp_path / "publish").iterdir()} == {"main", "ownership", "aggregate"}


def test_preexisting_shared_publication_root_is_never_modified(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "k" * 64)
    root = tmp_path / "publish"
    root.mkdir()
    sentinel = root / "sentinel"
    sentinel.write_text("keep")
    source = tmp_path / "work"
    source.mkdir()
    (source / "report").write_text("safe")
    specs = [(source, root / name, {"report"}) for name in ("main", "ownership", "aggregate")]
    assert gate.publish_outputs(
        specs, identity={"head": "a" * 40, "run_id": "123", "run_attempt": "1"},
        result="BLOCK", primary_error="PYTEST_MAIN_FAILED", cleanup_error=None,
        stage_exit_codes={"main": 1, "ownership": 0, "aggregate": 1},
        atomic_root=root,
    ) == "UNPUBLISHABLE"
    assert list(root.iterdir()) == [sentinel]


def test_process_group_identity_loss_never_signals_reused_pgid(monkeypatch):
    from ops import ci_pytest_gate as gate
    class Process:
        returncode = 0
        def poll(self): return self.returncode
        def wait(self, timeout=None): return self.returncode

    record = {"name": "main", "process": Process(), "pid": 7, "pgid": 7,
              "process_identity": "original"}
    monkeypatch.setattr(gate, "_process_identity", lambda _pid: None)
    monkeypatch.setattr(gate, "_group_alive", lambda _pgid: True)
    signalled = []
    monkeypatch.setattr(gate.os, "killpg", lambda *args: signalled.append(args))
    with pytest.raises(RuntimeError, match="PYTEST_PROCESS_REAP_FAILED"):
        gate._terminate_processes([record], grace_seconds=0)
    assert signalled == []


def test_process_group_missing_identities_never_match(monkeypatch):
    from ops import ci_pytest_gate as gate
    class Process:
        def poll(self): return None
        def wait(self, timeout=None): raise subprocess.TimeoutExpired("wait", timeout)

    record = {"name": "main", "process": Process(), "pid": 7, "pgid": 7,
              "process_identity": None}
    monkeypatch.setattr(gate, "_process_identity", lambda _pid: None)
    monkeypatch.setattr(gate, "_group_alive", lambda _pgid: True)
    signalled = []
    monkeypatch.setattr(gate.os, "killpg", lambda *args: signalled.append(args))
    with pytest.raises(RuntimeError, match="PYTEST_PROCESS_REAP_FAILED"):
        gate._terminate_processes([record], grace_seconds=0)
    assert signalled == []


def test_start_refuses_unprovable_process_identity(monkeypatch):
    from ops import ci_pytest_gate as gate
    class Process:
        pid = 7
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 1

    monkeypatch.setattr(gate.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    monkeypatch.setattr(gate, "_process_identity", lambda _pid: None)
    monkeypatch.setattr(gate, "_terminate_new_process_group", lambda _process: None)
    with pytest.raises(gate._SupervisorFailure, match="PYTEST_PROCESS_IDENTITY_UNAVAILABLE"):
        gate._start_managed_process("main", ["pytest"], {}, [])


def test_unidentified_new_session_is_terminated_as_a_group(monkeypatch):
    from ops import ci_pytest_gate as gate
    class Process:
        pid = 7
        waited = False
        def wait(self, timeout=None):
            self.waited = True
            return -signal.SIGKILL

    process = Process()
    alive = iter([True, True])
    def group_alive(_pgid):
        assert not process.waited, "numeric PGID was accessed after leader reap"
        return next(alive)
    monkeypatch.setattr(gate, "_group_alive", group_alive)
    monkeypatch.setattr(gate.time, "sleep", lambda _seconds: None)
    signals = []
    monkeypatch.setattr(gate.os, "killpg", lambda pgid, signum: signals.append((pgid, signum)))
    gate._terminate_new_process_group(process, grace_seconds=0)
    assert signals == [(7, signal.SIGTERM), (7, signal.SIGKILL)]


def test_partition_children_cannot_write_supervisor_step_output(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "step-output"))
    environments = gate._partition_environments(tmp_path / "cache")
    assert all("GITHUB_OUTPUT" not in environment for environment in environments)


def test_published_block_can_still_qualify_successful_ownership(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "k" * 64)
    monkeypatch.setenv("RELEASE_SOURCE_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    output = tmp_path / "ownership"
    _partition_artifacts(output, ["tests/test_owner.py::test_ok"])
    digests = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in output.iterdir() if path.name != "publication.json"
    }
    publication = {
        **gate._run_identity(), "partition": "ownership", "result": "PASS",
        "partition_result": "PASS", "overall_result": "BLOCK", "artifact_result": "PASS",
        "artifact_sha256": digests, "primary_error": "PYTEST_MAIN_FAILED",
        "terminal_error": None, "cleanup_error": None, "publication_error": None,
        "stage_exit_codes": {"main": 1, "ownership": 0, "aggregate": 1},
    }
    (output / "publication.json").write_text(json.dumps(publication))
    assert gate.validate_partition_output(
        output, minimum=1, **gate._run_identity()
    ) == [gate._node_identities(["tests/test_owner.py::test_ok"])[0]]


@pytest.mark.parametrize("primary_error,exits", [
    ("PYTEST_SUPERVISOR_CANCELLED", {"main": 143, "ownership": 0, "aggregate": None}),
    ("PYTEST_MAIN_TIMEOUT", {"main": None, "ownership": 0, "aggregate": None}),
])
def test_terminal_supervisor_error_never_qualifies_ownership_publication(
    tmp_path, monkeypatch, primary_error, exits,
):
    from ops import ci_pytest_gate as gate
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "k" * 64)
    specs = []
    for index, allowed in enumerate((gate._PARTITION_FILES, gate._PARTITION_FILES, gate._AGGREGATE_FILES)):
        source = tmp_path / f"work-{index}"
        target = tmp_path / f"publish-{index}"
        source.mkdir()
        (source / next(iter(allowed))).write_text("safe")
        specs.append((source, target, allowed))
    assert gate.publish_outputs(
        specs, identity={"head": "a" * 40, "run_id": "123", "run_attempt": "1"},
        result="BLOCK", primary_error=primary_error, cleanup_error=None,
        stage_exit_codes=exits,
    ) == "BLOCK"
    receipt = json.loads((specs[1][1] / "publication.json").read_text())
    assert receipt["partition_result"] == "BLOCK"
    with pytest.raises(ValueError, match="PYTEST_PUBLICATION_INVALID"):
        gate._validate_publication(
            specs[1][1], head="a" * 40, run_id="123", run_attempt="1",
        )


@pytest.mark.parametrize("exit_code", [None, -signal.SIGTERM, -signal.SIGKILL])
def test_timeout_errors_accept_only_unfinished_or_supervisor_terminated_stage(exit_code):
    from ops import ci_pytest_gate as gate
    exits = {"main": exit_code, "ownership": 0, "aggregate": 0}
    assert gate._primary_error_matches_exits("PYTEST_MAIN_TIMEOUT", exits)
    assert gate._terminal_error_matches_exits("PYTEST_MAIN_TIMEOUT", exits)
    exits["main"] = 1
    assert not gate._primary_error_matches_exits("PYTEST_MAIN_TIMEOUT", exits)
    assert not gate._terminal_error_matches_exits("PYTEST_MAIN_TIMEOUT", exits)


def test_later_terminal_error_blocks_all_partitions_without_replacing_first_error(
    tmp_path, monkeypatch,
):
    from ops import ci_pytest_gate as gate
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "k" * 64)
    identity = {"head": "a" * 40, "run_id": "123", "run_attempt": "1"}
    specs = []
    for index, allowed in enumerate((gate._PARTITION_FILES, gate._PARTITION_FILES, gate._AGGREGATE_FILES)):
        source = tmp_path / f"work-{index}"
        target = tmp_path / f"publish-{index}"
        source.mkdir()
        (source / next(iter(allowed))).write_text("safe")
        specs.append((source, target, allowed))
    assert gate.publish_outputs(
        specs, identity=identity, result="BLOCK", primary_error="PYTEST_MAIN_FAILED",
        terminal_error="PYTEST_AGGREGATE_TIMEOUT", cleanup_error=None,
        stage_exit_codes={"main": 1, "ownership": 0, "aggregate": None},
    ) == "BLOCK"
    gate.validate_publication_outputs([target for _, target, _ in specs], **identity)
    receipts = [json.loads((target / "publication.json").read_text()) for _, target, _ in specs]
    assert {receipt["partition_result"] for receipt in receipts} == {"BLOCK"}
    assert {receipt["primary_error"] for receipt in receipts} == {"PYTEST_MAIN_FAILED"}
    assert {receipt["terminal_error"] for receipt in receipts} == {"PYTEST_AGGREGATE_TIMEOUT"}

    forged = receipts[1]
    forged["result"] = forged["partition_result"] = "PASS"
    (specs[1][1] / "publication.json").write_text(json.dumps(forged))
    with pytest.raises(ValueError, match="PYTEST_PUBLICATION_INVALID"):
        gate._validate_publication(specs[1][1], **identity)
    with pytest.raises(ValueError, match="PYTEST_PUBLICATION_INVALID"):
        gate.validate_publication_outputs([target for _, target, _ in specs], **identity)


@pytest.mark.parametrize("exits,primary_error", [
    ({"main": "1", "ownership": 0, "aggregate": 1}, "PYTEST_MAIN_FAILED"),
    ({"main": 1, "ownership": 0, "aggregate": 1}, "PYTEST_OWNERSHIP_FAILED"),
    ({"main": 0, "ownership": 0, "aggregate": 1}, "PYTEST_MAIN_FAILED"),
    ({"main": None, "ownership": 0, "aggregate": 1}, "PYTEST_MAIN_FAILED"),
    ({"main": 1, "ownership": 0, "aggregate": 1}, "PYTEST_MAIN_TIMEOUT"),
])
def test_ownership_qualification_rejects_malformed_or_contradictory_state(
    tmp_path, monkeypatch, exits, primary_error,
):
    from ops import ci_pytest_gate as gate
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "k" * 64)
    monkeypatch.setenv("RELEASE_SOURCE_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    output = tmp_path / "ownership"
    _partition_artifacts(output, ["tests/test_owner.py::test_ok"])
    digests = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in output.iterdir() if path.name != "publication.json"
    }
    (output / "publication.json").write_text(json.dumps({
        **gate._run_identity(), "partition": "ownership", "result": "PASS",
        "partition_result": "PASS", "overall_result": "BLOCK", "artifact_result": "PASS",
        "artifact_sha256": digests, "primary_error": primary_error,
        "cleanup_error": None, "publication_error": None, "stage_exit_codes": exits,
    }))
    with pytest.raises(ValueError, match="PYTEST_PUBLICATION_INVALID"):
        gate.validate_partition_output(output, minimum=1, **gate._run_identity())


def test_publication_validator_rejects_inconsistent_pass_receipt(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "identity-key-" + "x" * 52)
    outputs = []
    for index in range(3):
        output = tmp_path / str(index)
        output.mkdir()
        (output / "publication.json").write_text(json.dumps({
            "head": "a" * 40, "run_id": "123", "run_attempt": "2",
            "partition": ("main", "ownership", "aggregate")[index],
            "result": "PASS", "partition_result": "PASS", "overall_result": "BLOCK",
            "artifact_result": "PASS",
            "primary_error": "PYTEST_MAIN_FAILED", "cleanup_error": None,
            "publication_error": None,
            "stage_exit_codes": {"main": 1, "ownership": 0, "aggregate": 0},
            "artifact_sha256": {},
        }))
        outputs.append(output)
    with pytest.raises(ValueError, match="PYTEST_PUBLICATION_INVALID"):
        gate.validate_publication_outputs(outputs, head="a" * 40, run_id="123", run_attempt="2")


def test_signal_does_not_replace_an_earlier_stage_failure(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("RELEASE_SOURCE_SHA", "a" * 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "x" * 64)
    calls = []

    class Process:
        def __init__(self, returncode):
            self.pid = 53000 + len(calls)
            self.returncode = returncode

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            return self.returncode

    def popen(command, **_kwargs):
        output = Path(command[-1])
        output.mkdir(parents=True, exist_ok=True)
        calls.append(output.name)
        return Process(1 if len(calls) == 1 else None)

    monkeypatch.setattr(gate.subprocess, "Popen", popen)
    monkeypatch.setattr(gate, "_process_identity", lambda pid: str(pid))
    monkeypatch.setattr(gate, "_observe_process_exit", lambda record: record["process"].poll())
    monkeypatch.setattr(gate, "_wait_managed", lambda *_args, **_kwargs: (_ for _ in ()).throw(gate._SignalExit(signal.SIGTERM)))
    monkeypatch.setattr(gate, "_terminate_processes", lambda *_args, **_kwargs: None)
    outputs = [tmp_path / name for name in ("main", "ownership", "aggregate")]
    monkeypatch.setattr(gate.sys, "argv", ["gate", "--partitions", *map(str, outputs)])

    assert gate.main() != 0
    receipt = json.loads((tmp_path / "aggregate-publish" / "publication.json").read_text())
    assert receipt["primary_error"] == "PYTEST_MAIN_FAILED"
