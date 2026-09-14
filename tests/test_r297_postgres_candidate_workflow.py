"""Exercise the candidate workflow shell with real, tiny pytest collections."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
import tempfile
import time
import signal
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/r297-candidate-validation.yml"


def run_step(tmp_path, body, *, generation_failure=False, sanitizer_startup_failure=False, cancel_marker=None):
    if not sys.platform.startswith("linux"):
        pytest.skip("candidate workflow executes on Ubuntu")
    with tempfile.TemporaryDirectory(prefix='r297-pg-fixture-', dir='/tmp') as directory:
        return _run_step(tmp_path, body, Path(directory), generation_failure=generation_failure,
                         sanitizer_startup_failure=sanitizer_startup_failure, cancel_marker=cancel_marker)


def _run_step(tmp_path, body, source, *, generation_failure, sanitizer_startup_failure, cancel_marker):
    block = WORKFLOW.read_text().split("      - name: Run complete selected", 1)[1].split("      - name:", 1)[0]
    script = textwrap.dedent(block.split("        run: |\n", 1)[1])
    fixture = source / "test_fixture.py"
    fixture.write_text(body)
    # Only this newly-owned source directory is made readable to the candidate.
    source.chmod(0o755)
    # Change only the selected tests, never the lifecycle being exercised.
    script = re.sub(r"tests/test_r297_acceptance_status.py.*?tests/test_r297_jd_business_uniqueness_migration.py",
                    f"--noconftest {fixture}", script, flags=re.S)
    output = tmp_path / "outputs"
    env = {**os.environ, "GITHUB_ACTIONS": "true", "GITHUB_OUTPUT": str(output),
           "RELEASE_SOURCE_SHA": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
           "PYTHONPATH": str(ROOT), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    env.pop("CI_PYTEST_IDENTITY_KEY", None)
    env.pop("R297_REDACT_EXACT_ENV_NAMES", None)
    # Nested real pytest must not write the outer supervisor's progress/status.
    env.pop("CI_PYTEST_PROGRESS_DIRECTORY", None)
    env.pop("PYTEST_ADDOPTS", None)
    if generation_failure:
        # Fail the randomness boundary, leaving the real shell EXIT path intact.
        script = script.replace("import secrets; print(secrets.token_urlsafe(48))", "raise SystemExit(1)")
    if sanitizer_startup_failure:
        script = script.replace("from pathlib import Path", "import os\n"
                                "if channel := os.environ.get('GITHUB_OUTPUT'):\n"
                                "    with open(channel, 'a') as stream:\n"
                                "        stream.write('publish_path=' + sys.argv[1] + '\\npublication_ready=true\\n')\n"
                                "raise SystemExit(1)\nfrom pathlib import Path")
    # An EXIT observer checks that the workflow's trap really unsets its key.
    script = script.replace("unset CI_PYTEST_IDENTITY_KEY R297_REDACT_EXACT_ENV_NAMES",
                            "unset CI_PYTEST_IDENTITY_KEY R297_REDACT_EXACT_ENV_NAMES; "
                            "test -z \"${CI_PYTEST_IDENTITY_KEY+x}${R297_REDACT_EXACT_ENV_NAMES+x}\"; echo KEY_UNSET")
    command = ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script]
    if cancel_marker is None:
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=40)
    else:
        with subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
            deadline = time.monotonic() + 20
            while not cancel_marker.read_text() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            assert cancel_marker.read_text(), 'candidate did not reach cancellation point'
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=20)
            result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines()) if output.exists() else {}
    masks = [line.removeprefix("::add-mask::") for line in result.stdout.splitlines()
             if line.startswith("::add-mask::")]
    payload = b"".join(p.read_bytes() for p in Path(outputs["publish_path"]).iterdir()) if outputs.get("publish_path") else b""
    visible = "\n".join(line for line in result.stdout.splitlines() if not line.startswith("::add-mask::"))
    result.identity_leaked = any(key.encode() in payload or key in visible or key in result.stderr for key in masks)
    result.identity_digests = [hashlib.sha256(key.encode()).hexdigest() for key in masks]
    # Even a regression's assertion traceback must not print these test keys.
    for key in masks:
        result.stdout = result.stdout.replace(key, "[TEST_IDENTITY]")
        result.stderr = result.stderr.replace(key, "[TEST_IDENTITY]")
    return result, outputs


def test_candidate_generates_identity_and_publishes_only_safe_real_reports(tmp_path):
    result, outputs = run_step(tmp_path, """
import os
def test_identity():
    key = os.environ.get('CI_PYTEST_IDENTITY_KEY', '')
    assert len(key) >= 64
    assert os.environ['R297_REDACT_EXACT_ENV_NAMES'] == 'CI_PYTEST_IDENTITY_KEY'
    assert all(name not in os.environ for name in ('GITHUB_OUTPUT', 'GITHUB_ENV', 'GITHUB_PATH', 'GITHUB_STEP_SUMMARY'))
""")
    code = result.returncode
    assert code == 0, "candidate step failed"
    assert outputs.get("publication_ready") == "true"
    published = Path(outputs["publish_path"])
    assert published.is_absolute() and published.name.startswith("r297-postgres-publish.")
    assert ET.parse(published / "junit.xml").getroot().find("testsuite").get("tests") == "1"
    assert "KEY_UNSET" in result.stdout
    assert "CI_PYTEST_IDENTITY_KEY" not in "\n".join(outputs.values())


def test_normal_test_failure_retains_real_redacted_report_and_fresh_hmac(tmp_path):
    keys = []
    for attempt in ("first", "second"):
        folder = tmp_path / attempt
        folder.mkdir()
        result, outputs = run_step(folder, """
import os
def test_failure():
    raise RuntimeError(os.environ['CI_PYTEST_IDENTITY_KEY'])
def test_success():
    pass
""")
        code = result.returncode
        assert code == 1
        assert outputs.get("publication_ready") == "true"
        published = Path(outputs["publish_path"])
        suite = ET.parse(published / "junit.xml").getroot().find("testsuite")
        assert (suite.get("tests"), suite.get("failures")) == ("2", "1")
        payload = b"".join(p.read_bytes() for p in published.iterdir())
        assert len(result.identity_digests) == 1
        leaked = result.identity_leaked
        assert not leaked
        assert b"[REDACTED]" in payload
        assert result.stdout.count("KEY_UNSET") == 2
        nodes = json.loads((published / "collected-nodeids.json").read_text())
        assert len(nodes) == 2 and all(re.fullmatch(r"[0-9a-f]{64}", n) for n in nodes)
        keys.append(result.identity_digests[0])
    assert keys[0] != keys[1]


@pytest.mark.parametrize("encoding", ["base64", "hex", "HEX"])
def test_encoded_key_contamination_never_opens_upload_gate(tmp_path, encoding):
    result, outputs = run_step(tmp_path, f"""
import base64, os
def test_failure():
    key = os.environ['CI_PYTEST_IDENTITY_KEY'].encode()
    value = base64.b64encode(key).decode() if {encoding!r} == 'base64' else key.hex()
    raise RuntimeError(value.upper() if {encoding!r} == 'HEX' else value)
""")
    code = result.returncode
    assert code == 1
    assert not outputs
    assert "POSTGRES_REPORT_PUBLICATION_FAILED" in result.stdout
    assert result.stdout.count("KEY_UNSET") == 1
    assert not result.stderr


def test_generation_failure_still_cleans_identity_without_publication(tmp_path):
    result, outputs = run_step(tmp_path, "def test_unused(): pass", generation_failure=True)
    code = result.returncode
    assert code != 0
    assert not outputs
    assert "KEY_UNSET" in result.stdout


def test_interrupted_pytest_never_publishes_incomplete_junit(tmp_path):
    result, outputs = run_step(tmp_path, "def test_cancel(): raise KeyboardInterrupt()")
    code = result.returncode
    assert code == 2
    assert not outputs
    assert "POSTGRES_TEST_EXECUTION_INCOMPLETE" in result.stdout
    assert "KEY_UNSET" in result.stdout


def test_missing_real_junit_does_not_generate_replacement(tmp_path):
    result, outputs = run_step(tmp_path, "import os\ndef test_exit(): os._exit(0)")
    code = result.returncode
    assert code == 1
    assert not outputs
    assert "POSTGRES_REPORT_PUBLICATION_FAILED" in result.stdout
    assert "KEY_UNSET" in result.stdout


def test_skip_stays_block_even_when_pytest_returns_zero(tmp_path):
    result, outputs = run_step(tmp_path, "import pytest\ndef test_skip(): pytest.skip('not verified')")
    code = result.returncode
    assert code == 1
    assert outputs.get("publication_ready") == "true"
    suite = ET.parse(Path(outputs["publish_path"]) / "junit.xml").getroot().find("testsuite")
    assert (suite.get("tests"), suite.get("skipped")) == ("1", "1")


def test_sanitizer_startup_failure_is_not_a_safe_test_failure(tmp_path):
    result, outputs = run_step(tmp_path, "def test_ok(): pass", sanitizer_startup_failure=True)
    code = result.returncode
    assert code == 1
    assert not outputs


def test_sigterm_runs_exit_cleanup_and_never_publishes(tmp_path):
    with tempfile.NamedTemporaryFile(prefix='r297-pg-cancel-', dir='/tmp') as handle:
        marker = Path(handle.name)
        marker.chmod(0o666)
        result, outputs = run_step(tmp_path, f"""
import time
from pathlib import Path
def test_cancel_parent():
    Path({str(marker)!r}).write_text('ready')
    time.sleep(0.5)
""", cancel_marker=marker)
    code = result.returncode
    assert code == 143
    assert not outputs
    assert "KEY_UNSET" in result.stdout


def test_workflow_upload_requires_nonempty_safe_publication_and_run_binding():
    workflow = WORKFLOW.read_text()
    upload = workflow.split("      - name: Upload actual database test results", 1)[1]
    assert "!cancelled()" in upload
    assert "steps.postgres_tests.outputs.publication_ready == 'true'" in upload
    assert "steps.postgres_tests.outputs.publish_path != ''" in upload
    assert "path: ${{ steps.postgres_tests.outputs.publish_path }}" in upload
    assert "${{ github.run_id }}-${{ github.run_attempt }}" in upload
    assert '>> "$GITHUB_ENV"' not in workflow


@pytest.mark.parametrize("ending", ["os._exit(2)", "os._exit(0)", "raise RuntimeError(base64.b64encode(os.environ['CI_PYTEST_IDENTITY_KEY'].encode()).decode())"])
def test_pytest_cannot_forge_publication_before_failing(tmp_path, ending):
    result, outputs = run_step(tmp_path, f"""
import os, base64
from pathlib import Path
def test_forge():
    if output := os.environ.get('GITHUB_OUTPUT'):
        raw = Path(os.environ['CI_PYTEST_COLLECTION_MANIFEST']).parent / 'unreviewed'
        raw.mkdir()
        (raw / 'raw.log').write_text('UNREVIEWED_TEST_ONLY')
        with open(output, 'a') as stream:
            stream.write('publish_path=' + str(raw) + '\\npublication_ready=true\\n')
    {ending}
""")
    code = result.returncode
    assert code != 0
    assert not outputs


def test_pytest_and_descendant_cannot_modify_parent_publication(tmp_path):
    protected = tmp_path / 'parent-publication'
    protected.mkdir(mode=0o700)
    report = protected / 'junit.xml'
    report.write_text('PARENT_OWNED_ORIGINAL')
    result, outputs = run_step(tmp_path, f"""
import os, subprocess, sys
from pathlib import Path
def test_no_publication_authority():
    assert os.getuid() != {os.getuid()}
    assert os.getgroups() == []
    assert 'NoNewPrivs:\\t1' in Path('/proc/self/status').read_text()
    assert 'CapEff:\\t0000000000000000' in Path('/proc/self/status').read_text()
    try:
        os.setuid(0)
    except PermissionError:
        pass
    else:
        raise AssertionError('root authority recovered')
    for attack in [lambda: Path({str(report)!r}).write_text('changed'),
                   lambda: Path({str(protected)!r}).chmod(0o777)]:
        try:
            attack()
        except PermissionError:
            pass
        else:
            raise AssertionError('publication writable')
    code = "from pathlib import Path; Path(" + repr({str(report)!r}) + ").write_text('changed')"
    child = subprocess.run([sys.executable, '-c', code], capture_output=True)
    assert child.returncode != 0
""")
    code = result.returncode
    assert code == 0
    assert outputs.get('publication_ready') == 'true'
    assert report.read_text() == 'PARENT_OWNED_ORIGINAL'


@pytest.mark.parametrize('invalid', ['extra-file', 'symlink'])
def test_launcher_rejects_unowned_layout_without_mutation(tmp_path, invalid):
    if not sys.platform.startswith('linux') or os.geteuid() != 0:
        pytest.skip('privilege-drop launcher requires an isolated root Linux container')
    work = tmp_path / 'r297-postgres-work.test'
    work.mkdir(mode=0o700)
    (work / 'pytest.log').touch()
    if invalid == 'extra-file':
        (work / 'keep').write_text('preserved')
        target = work
    else:
        target = tmp_path / 'r297-postgres-work.link'
        target.symlink_to(work, target_is_directory=True)
    before = work.stat()
    result = subprocess.run([sys.executable, str(ROOT / 'ops/r297_candidate_pytest.py'), str(target),
                             '-c', 'raise SystemExit(97)'], capture_output=True, text=True)
    code = result.returncode
    assert code == 2
    after = work.stat()
    assert (before.st_uid, before.st_gid, before.st_mode) == (after.st_uid, after.st_gid, after.st_mode)
    if invalid == 'extra-file':
        assert (work / 'keep').read_text() == 'preserved'
