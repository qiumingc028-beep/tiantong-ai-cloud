from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_repository_tests_run_and_upload_before_protected_evidence_gate():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    windows = (ROOT / ".github/workflows/r291-windows-workbench.yml").read_text(encoding="utf-8")
    acceptance = (ROOT / "tests/test_r297_acceptance_gates.py").read_text(encoding="utf-8")

    repository_job = workflow.split("  repository-tests:", 1)[1].split("\n  test-and-build:", 1)[0]
    assert "needs:" not in repository_job
    assert "timeout-minutes: 90" in repository_job
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in repository_job
    assert 'test "$(git rev-parse HEAD)" = "$RELEASE_SOURCE_SHA"' in repository_job
    assert '-m "not r297_process_evidence and not r297_windows_evidence"' in repository_job
    assert "--junitxml=/tmp/pytest-results.xml" in repository_job
    assert "name: r297-pytest-${{ github.event.pull_request.head.sha || github.sha }}" in repository_job
    assert "if: always()" in repository_job
    assert "python ops/r297_ci_redact.py /tmp/pytest-results.xml /tmp/pytest-results.log" in repository_job
    assert "continue-on-error" not in workflow
    full_job = workflow.split("  test-and-build:", 1)[1]
    assert "timeout-minutes: 90" in full_job.split("\n    steps:", 1)[0]
    assert acceptance.count("@pytest.mark.r297_process_evidence") == 8
    assert acceptance.count("@pytest.mark.r297_windows_evidence") == 1

    evidence_step = workflow.index("- name: Generate R297 real-process acceptance evidence")
    evidence_tail = workflow[evidence_step:]
    assert "--signed-event-bundle" in evidence_tail
    assert "--junitxml=/tmp/r297-process-evidence-results.xml" in evidence_tail
    assert "name: r297-process-evidence-log-${{ github.event.pull_request.head.sha || github.sha }}" in evidence_tail
    assert "if: always()" in evidence_tail
    assert "test ! -f \"$artifact\" || python ops/r297_ci_redact.py \"$artifact\"" in evidence_tail
    assert "if-no-files-found: warn" not in evidence_tail
    assert "-m r297_windows_evidence" in windows
    assert "R297_WINDOWS_ACCEPTANCE_EVIDENCE:" in windows
    windows_job = windows.split("  build-windows:", 1)[1]
    assert "timeout-minutes: 90" in windows_job.split("\n    steps:", 1)[0]
    assert "RELEASE_SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}" in windows_job
    assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in windows_job
    assert "r297-windows-evidence-validation-${{ github.event.pull_request.head.sha || github.sha }}" in windows
    windows_acceptance = (ROOT / "ops/r297_windows_acceptance.ps1").read_text(encoding="utf-8")
    assert "$env:RELEASE_SOURCE_SHA -eq $head" in windows_acceptance
    assert "$env:GITHUB_SHA -eq $head" not in windows_acceptance
