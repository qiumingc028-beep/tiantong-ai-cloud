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
    (root / "publication.json").write_text(json.dumps({
        "head": head, "run_id": "123", "run_attempt": "1", "result": "PASS",
        "artifact_result": "PASS", "primary_error": None, "cleanup_error": None,
        "publication_error": None,
        "stage_exit_codes": {"main": 0, "ownership": 0, "aggregate": 0},
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
    monkeypatch.delenv("CI_PYTEST_IDENTITY_KEY")

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
            "head": "a" * 40, "run_id": "123", "run_attempt": "1", "result": "PASS",
            "artifact_result": "PASS", "primary_error": None, "cleanup_error": None,
            "publication_error": None,
            "stage_exit_codes": {"main": 0, "ownership": 0, "aggregate": 0},
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
    (partition / "publication.json").write_text(json.dumps(publication))
    aggregate = tmp_path / "aggregate"
    aggregate.mkdir()
    (aggregate / "aggregate.json").write_text(json.dumps({
        "head": "a" * 40, "run_id": "123", "run_attempt": "2", "result": "PASS",
        "collected": 1, "executed": 1, "overlap": 0, "missing": 0,
    }))
    (aggregate / "publication.json").write_text(json.dumps({
        "head": "a" * 40, "run_id": "123", "run_attempt": "2", "result": "PASS",
        "artifact_result": "PASS", "primary_error": None, "cleanup_error": None,
        "publication_error": None,
        "stage_exit_codes": {"main": 0, "ownership": 0, "aggregate": 0},
    }))
    for command in (
        [sys.executable, "-O", "-m", "ops.ci_pytest_gate", "--validate-partition", str(partition), "1"],
        [sys.executable, "-O", "-m", "ops.ci_pytest_gate", "--validate-aggregate", str(aggregate)],
    ):
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        assert result.returncode == 0 and "CI_PYTEST_VALIDATION=PASS" in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="CI partition supervisor runs on ubuntu")
def test_partition_cleanup_terminates_and_reaps_its_process_group(tmp_path):
    from ops import ci_pytest_gate as gate

    child_pid = tmp_path / "child.pid"
    script = (
        "import pathlib,signal,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)']);"
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid));"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"
    )
    process = subprocess.Popen([sys.executable, "-c", script], start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not child_pid.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        descendant = int(child_pid.read_text())
        records = [{"name": "partition", "process": process, "pid": process.pid, "pgid": os.getpgid(process.pid)}]
        gate._terminate_processes(records, grace_seconds=0.05)
        assert process.returncode == -signal.SIGKILL
        assert descendant != process.pid
        assert not gate._group_alive(records[0]["pgid"])
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


@pytest.mark.skipif(os.name == "nt", reason="CI partition supervisor runs on ubuntu")
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


@pytest.mark.parametrize("encoding", ["raw", "base64", "hex"])
def test_partition_artifact_scan_rejects_identity_key_encodings(tmp_path, monkeypatch, encoding):
    from ops import ci_pytest_gate as gate

    key = "identity-key-" + "x" * 52
    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", key)
    value = {"raw": key, "base64": base64.b64encode(key.encode()).decode(), "hex": key.encode().hex()}[encoding]
    output = tmp_path / "output"
    output.mkdir()
    (output / "artifact.txt").write_text(value)
    with pytest.raises(RuntimeError, match="CI_PYTEST_IDENTITY_ARTIFACT_LEAK"):
        gate._scan_identity_key([output])


@pytest.mark.skipif(os.name == "nt", reason="CI partition supervisor runs on ubuntu")
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


@pytest.mark.skipif(os.name == "nt", reason="CI partition supervisor runs on ubuntu")
def test_partition_supervisor_handles_term_and_reaps_both_groups(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    real_popen = subprocess.Popen
    started = []
    both_started = threading.Event()

    def start(command, **kwargs):
        process = real_popen(
            [sys.executable, "-c", "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"],
            start_new_session=kwargs["start_new_session"],
        )
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
    assert "/tmp/r297-publish-pytest/" in workflow
    assert "/tmp/r297-publish-ownership/" in workflow
    assert "/tmp/r297-publish-full-coverage/" in workflow
    for unsafe in (
        "path: /tmp/r297-pytest/",
        "path: /tmp/r297-ownership-matrix/",
        "path: /tmp/r297-full-coverage/",
    ):
        assert unsafe not in workflow
    assert "id: pytest_gate" in workflow
    assert "--validate-publication" in workflow
    assert workflow.count("steps.pytest_gate.outputs.publication_ready == 'true'") == 3


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

    assert result == "BLOCK"
    assert {path.name for path in published.iterdir()} == {"publication.json"}
    receipt = json.loads((published / "publication.json").read_text())
    assert receipt["result"] == "BLOCK"
    assert receipt["primary_error"] == "CI_PYTEST_IDENTITY_ARTIFACT_LEAK"
    assert key not in (published / "publication.json").read_text()


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


@pytest.mark.skipif(os.name == "nt", reason="CI partition supervisor runs on ubuntu")
@pytest.mark.parametrize("stage", ["main", "ownership", "aggregate"])
def test_supervisor_deadline_reaps_descendants_and_preserves_timeout_code(tmp_path, stage):
    from ops import ci_pytest_gate as gate

    child_pid = tmp_path / "child.pid"
    script = (
        "import pathlib,signal,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)']);"
        f"pathlib.Path({str(child_pid)!r}).write_text(str(child.pid));"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"
    )
    records = []
    record = gate._start_managed_process(stage, [sys.executable, "-c", script], dict(os.environ), records)
    try:
        with pytest.raises(gate._SupervisorFailure, match=f"PYTEST_{stage.upper()}_TIMEOUT"):
            gate._wait_managed([record], {stage: 0.05})
        gate._terminate_processes(records, grace_seconds=0.05)
        assert record["process"].returncode == -signal.SIGKILL
        assert not gate._group_alive(record["pgid"])
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


def test_aggregate_fixed_set_includes_the_collected_manifest(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

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
            "result": "BLOCK", "artifact_result": "BLOCK",
            "primary_error": "PYTEST_MAIN_FAILED",
            "cleanup_error": None, "publication_error": None,
            "stage_exit_codes": {"main": 1, "ownership": 0, "aggregate": index},
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


def test_reaped_process_group_is_not_targeted_twice(monkeypatch):
    from ops import ci_pytest_gate as gate

    class Process:
        def __init__(self): self.waits = 0
        def poll(self): return 0
        def wait(self, timeout=None): self.waits += 1; return 0

    process = Process()
    record = {"name": "main", "process": process, "pid": 1, "pgid": 1}
    monkeypatch.setattr(gate, "_group_alive", lambda _pgid: False)
    gate._terminate_processes([record], grace_seconds=0)
    gate._terminate_processes([record], grace_seconds=0)
    assert process.waits == 1 and record["reaped"] is True


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
    monkeypatch.setattr(gate, "_terminate_processes", fail_reap)
    outputs = [tmp_path / name for name in ("main", "ownership", "aggregate")]
    monkeypatch.setattr(gate.sys, "argv", ["gate", "--partitions", *map(str, outputs)])

    assert gate.main() == 1
    receipt = json.loads((tmp_path / "aggregate-publish" / "publication.json").read_text())
    assert receipt["primary_error"] == "PYTEST_MAIN_FAILED"
    assert receipt["cleanup_error"] == "PYTEST_PROCESS_REAP_FAILED"


def test_publication_validator_rejects_inconsistent_pass_receipt(tmp_path, monkeypatch):
    from ops import ci_pytest_gate as gate

    monkeypatch.setenv("CI_PYTEST_IDENTITY_KEY", "identity-key-" + "x" * 52)
    outputs = []
    for index in range(3):
        output = tmp_path / str(index)
        output.mkdir()
        (output / "publication.json").write_text(json.dumps({
            "head": "a" * 40, "run_id": "123", "run_attempt": "2",
            "result": "PASS", "artifact_result": "PASS",
            "primary_error": "PYTEST_MAIN_FAILED", "cleanup_error": None,
            "publication_error": None,
            "stage_exit_codes": {"main": 1, "ownership": 0, "aggregate": 0},
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
    monkeypatch.setattr(gate, "_wait_managed", lambda *_args, **_kwargs: (_ for _ in ()).throw(gate._SignalExit(signal.SIGTERM)))
    monkeypatch.setattr(gate, "_terminate_processes", lambda *_args, **_kwargs: None)
    outputs = [tmp_path / name for name in ("main", "ownership", "aggregate")]
    monkeypatch.setattr(gate.sys, "argv", ["gate", "--partitions", *map(str, outputs)])

    assert gate.main() != 0
    receipt = json.loads((tmp_path / "aggregate-publish" / "publication.json").read_text())
    assert receipt["primary_error"] == "PYTEST_MAIN_FAILED"
