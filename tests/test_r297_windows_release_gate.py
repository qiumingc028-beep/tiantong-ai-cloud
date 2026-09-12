import json
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "desktop" / "jd-workbench"
WORKFLOW = ROOT / ".github" / "workflows" / "r291-windows-workbench.yml"
ACCEPTANCE_SCRIPT = ROOT / "ops" / "r297_windows_acceptance.ps1"
EVENT_SIGNER = ROOT / "ops" / "r297_windows_event_signer.py"
TRUSTED_OBSERVER = ROOT / "ops" / "r297_trusted_windows_observer.py"
NATIVE_BOUNDARY = ROOT / "tests" / "r297_windows_native_boundary.ps1"
JOB_SUPERVISOR = ROOT / "ops" / "r297_windows_job_supervisor.py"


def test_r297_windows_gate_packages_only_the_official_workbench():
    package = json.loads((CLIENT / "package.json").read_text(encoding="utf-8"))
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert package.get("dependencies", {}).get("electron") is None
    assert package["devDependencies"]["electron"] == "44.0.0"
    assert package["devDependencies"]["electron-builder"] == "26.15.3"
    assert "desktop/jd-workbench" in workflow
    assert "apps/jd-desktop-agent" not in workflow
    assert "actions/checkout@v7" in workflow
    assert "actions/setup-node@v7" in workflow
    assert 'node-version: "24"' in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "npm ci --no-audit --no-fund" in workflow
    assert "npm run check" in workflow
    assert "npm run dist:win" in workflow


def test_r297_windows_gate_has_complete_trigger_and_artifact_contract():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in workflow
    assert "workflow_dispatch:" in workflow
    assert "      - main" in workflow
    assert "codex/r297-jd-multistore-autosync" in workflow
    assert "      - codex/r297-cloud-integration" in workflow
    assert "      - codex/r297-windows-workflow-wiring-r2" in workflow
    assert "codex/r291-windows-installer" not in workflow
    assert "ELECTRON_RUN_AS_NODE" in workflow
    assert "fs.writeFileSync" in workflow
    assert "Start-Process" in workflow
    assert "-Wait -PassThru" in workflow
    assert "process.execPath" in workflow
    assert "process.versions.chrome" in workflow
    assert "chromium-info.json" in workflow
    assert "Expected one NSIS installer and one portable ZIP" in workflow
    assert "SHA256SUMS.txt" in workflow
    assert "retention-days: 14" in workflow
    assert "tiantong-ai-jd-workbench-r297-build-" in workflow
    assert workflow.count("${{ github.run_id }}-${{ github.run_attempt }}") >= 4
    for path in (
        "backend/__init__.py",
        "backend/services/__init__.py",
        "ops/r297_windows_file_security.py",
        "ops/r297_windows_recovery_probe.py",
        "ops/install_r297_trusted_windows_observer.ps1",
        "ops/install_r297_trusted_linux_host.sh",
        "ops/provision_r297_observer_database.sh",
        "ops/r297_authenticated_observer.py",
        "ops/r297_evidence_broker.py",
        "ops/r297_broker_client.py",
        "ops/r297_event_receipt.py",
        "ops/r297_evidence_storage.py",
        "ops/r297_evidence_role_service.py",
        "ops/r297_role_client.py",
        "ops/r297_evidence_bundle.py",
        "ops/r297_trusted_orchestrator.py",
        "tests/test_r297_windows_file_security.py",
        "tests/test_r297_windows_recovery.py",
        "tests/r297_windows_native_boundary.ps1",
    ):
        assert workflow.count(f"      - {path}") == 2


def test_r297_windows_acceptance_requires_controlled_https_pairing_secrets():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    acceptance = ACCEPTANCE_SCRIPT.read_text(encoding="utf-8")

    assert "environment: r297-controlled-canary" in workflow
    for name in (
        "R297_WINDOWS_CANARY_BACKEND_HTTPS_URL",
        "R297_WINDOWS_CANARY_PAIRING_ISSUER_BEARER",
        "R297_WINDOWS_CANARY_SERVER_CERTIFICATE_BASE64",
    ):
        assert f"secrets.{name}" not in workflow
        assert name in acceptance
    assert "R297_WINDOWS_CANARY_PAIRING_CODE" not in workflow + acceptance
    assert '"$backendOrigin/api/jd-workbench/pairing-codes"' in acceptance
    assert "$pairingCode | node $probe" in acceptance
    assert "$pairingCode = $null" in acceptance
    assert "R297_WINDOWS_CANARY_HEALTH_URL" not in workflow + acceptance
    assert "R297_WINDOWS_CANARY_SCHEDULER_URL" not in workflow + acceptance
    assert '"$backendOrigin/api/health"' in acceptance
    assert '/api/jd-workbench/stores/$($env:R297_EVIDENCE_STORE_ID)/acceptance-status' in acceptance
    assert '-Headers $ownerHeaders' in acceptance
    assert '$health.release.commit -ceq $head' in acceptance
    assert '$snapshot.release_sha -ceq $head' in acceptance
    assert acceptance.index('CONTROLLED_BACKEND_RELEASE_MISMATCH') < acceptance.index('$pairingResponse =')
    assert acceptance.index('$beforeCycle = [long]$alignedObservation.completed_cycle_count') < acceptance.index('$process.WaitForExit(10000)')
    assert '$observationWindowSeconds = 240' in acceptance
    assert '$observationDeadline = [DateTime]::UtcNow.AddSeconds($observationWindowSeconds)' in acceptance
    assert '$attempt -lt 60 -and $afterCycle -le $beforeCycle' not in acceptance
    assert 'latest_completed_at) -gt $electronExitAt' in acceptance
    assert "CONTROLLED_BACKEND_TLS_CERTIFICATE_MISMATCH" in acceptance
    assert "data_source = 'CONTROLLED_CANARY'" in acceptance


def test_r297_windows_acceptance_signs_only_after_real_electron_exit():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    acceptance = ACCEPTANCE_SCRIPT.read_text(encoding="utf-8")
    signer = EVENT_SIGNER.read_text(encoding="utf-8")

    assert "actions/setup-python@v6" in workflow
    assert "R297_WINDOWS_RUNNER_PRIVATE_KEY_PATH" not in workflow
    assert "R297_WINDOWS_RUNNER_PRIVATE_KEY_BASE64" not in workflow
    assert "R297_EVIDENCE_TRUST_MANIFEST_BASE64" not in workflow
    assert "R297_EVIDENCE_TRUST_MANIFEST_SHA256" not in workflow
    assert "secrets." not in workflow
    for name in (
        "R297_EVIDENCE_NAMESPACE", "R297_EVIDENCE_TENANT_ID",
        "R297_EVIDENCE_COMPANY_ID", "R297_EVIDENCE_STORE_ID", "R297_EVIDENCE_PLATFORM",
        "R297_ACCEPTANCE_RUN_ID",
    ):
        assert name in acceptance
    assert "$process.WaitForExit(10000)" in acceptance
    assert "python -m ops.r297_windows_event_signer" in acceptance
    assert acceptance.index("$process.WaitForExit(10000)") < acceptance.index(
        "python -m ops.r297_windows_event_signer"
    )
    assert "R297_WINDOWS_ELECTRON_EXIT_EVENT.json" in acceptance
    assert "write_sha256_bound_file" in signer
    observer = TRUSTED_OBSERVER.read_text(encoding="utf-8")
    assert "produce_electron_exit_event" in observer
    assert "Electron process was not live when trusted observation began" in observer
    assert "post-exit scheduler observation timed out" in observer
    assert "process_is_running(process_id)" in signer


def test_candidate_workflow_fails_before_windows_signing_key_is_exposed():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    candidate = workflow.split("  formal-windows-acceptance:", 1)[1]

    assert "R297_TRUSTED_SIGNER_BOUNDARY_NOT_CONFIGURED" not in candidate
    assert "R297_WINDOWS_RUNNER_PRIVATE_KEY_BASE64" not in candidate
    assert "R297_WINDOWS_RUNNER_PRIVATE_KEY_PATH" not in candidate
    assert "r297_windows_acceptance.ps1" not in candidate
    assert "Checkout immutable" not in candidate
    assert "R297_TRUSTED_WINDOWS_CONTROLLER_PATH" in candidate
    assert "R297_TRUSTED_WINDOWS_CONTROLLER_SHA256" in candidate
    assert "R297_TRUSTED_WINDOWS_CONTROLLER_SID" in candidate
    assert "R297_TRUSTED_WINDOWS_CONTROLLER_SERVICE_NAME" in candidate
    assert "R297_TRUSTED_WINDOWS_CONTROLLER_PIPE_NAME" in candidate
    assert "R297_TRUSTED_SIGNER_SHA" in candidate
    assert "& $controller" not in candidate
    assert "Start-ScheduledTask" not in candidate
    assert "Get-CimInstance -ClassName Win32_Service" in candidate
    assert "NamedPipeClientStream" in candidate
    assert "R297_FORMAL_CONTROLLER_SERVICE_IDENTITY_MISMATCH" in candidate
    assert "R297_FORMAL_CONTROLLER_SERVICE_MUST_NOT_BE_ADMIN" in candidate
    assert "R297_FORMAL_CONTROLLER_LOCAL_ACCOUNT_REQUIRED" in candidate
    assert "AccountDomainSid" in candidate
    assert "R297_FORMAL_CONTROLLER_ACK_INVALID" in candidate
    assert "request_sha256" in candidate


def test_windows_build_is_secretless_and_publishes_before_independent_formal_gate():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    build, formal = workflow.split("  build-windows:", 1)[1].split("  formal-windows-acceptance:", 1)
    assert "environment:" not in build
    assert "secrets." not in build
    assert "R297_TRUSTED_SIGNER_BOUNDARY_NOT_CONFIGURED" not in build
    assert "npm run dist:win" in build
    assert "actions/upload-artifact@v7" in build
    assert "name: tiantong-ai-jd-workbench-r297-build-${{ github.event.pull_request.head.sha || github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}" in build
    assert "if-no-files-found: error" in build
    assert "needs: [build-windows, windows-native-recovery-tests]" in formal
    assert "if: github.event_name == 'workflow_dispatch'" in formal
    assert "environment: r297-controlled-canary" in formal
    assert "actions/download-artifact@v8" in formal
    assert "name: tiantong-ai-jd-workbench-r297-build-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}" in formal
    assert "Checkout immutable" not in formal
    assert "R297_TRUSTED_SIGNER_BOUNDARY_NOT_CONFIGURED" not in formal
    assert "runs-on: [self-hosted, Windows, X64, r297-controlled-canary]" in formal
    assert "secrets." not in formal
    for name in (
        "R297_EVIDENCE_NAMESPACE", "R297_EVIDENCE_TENANT_ID",
        "R297_EVIDENCE_COMPANY_ID", "R297_EVIDENCE_STORE_ID",
    ):
        assert f"vars.{name}" in formal
    assert "R297_WINDOWS_RUNNER_PRIVATE_KEY" not in formal
    assert "R297_EVIDENCE_TRUST_MANIFEST_BASE64" not in formal
    assert "R297_TRUSTED_WINDOWS_CONTROLLER_PATH" in formal
    assert "R297_TRUSTED_WINDOWS_CONTROLLER_SHA256" in formal
    assert "R297_FORMAL_CANDIDATE_RUNNER_MUST_NOT_BE_ADMIN" in formal
    assert "R297_FORMAL_CONTROLLER_WRITABLE_BY_CANDIDATE" in formal
    assert "R297_FORMAL_CONTROLLER_DIGEST_MISMATCH" in formal
    assert "R297_FORMAL_IDENTITY_COLLISION" in formal
    assert "identity.Groups" in formal
    assert "R297_FORMAL_RESULT_HARDLINK_REJECTED" in formal
    assert "R297_FORMAL_RESULT_SIDECAR_INVALID" in formal
    assert "R297_FORMAL_RESULT_BINDING_INVALID" in formal
    assert "R297_FORMAL_RESULT_RUN_ALREADY_EXISTS" in formal
    assert "R297_FORMAL_RESULT_PARENT_REPLACE_ACCESS" in formal
    assert "formal-complete.json" in formal
    assert "R297_FORMAL_COMPLETION_INVALID" in formal
    assert "request_sha256" in formal
    assert "$trustedWriters" in formal
    assert formal.index("$preflightPaths") < formal.index("NamedPipeClientStream")
    assert "${{ github.run_id }}-${{ github.run_attempt }}/formal-result.json" in formal
    assert "path: ${{ vars.R297_TRUSTED_WINDOWS_RESULT_ROOT }}\n" not in formal
    assert "./ops/r297_windows_acceptance.ps1" not in formal


def test_windows_native_reports_publish_only_after_stable_atomic_finalization():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    native = workflow.split("      - name: Run complete Windows recovery regressions", 1)[1].split(
        "      - name: Upload sanitized native Windows reports", 1
    )[0]
    upload = workflow.split("      - name: Upload sanitized native Windows reports", 1)[1].split(
        "  formal-windows-acceptance:", 1
    )[0]
    assert "Remove-Item Env:GITHUB_OUTPUT" in native
    assert "[Guid]::NewGuid()" in native
    assert "[IO.File]::Open($source" in native
    assert "[IO.FileShare]::None" in native
    assert "$validatedDigests[$name]" in native
    assert "R297_NATIVE_PRIMARY_ERROR=$primaryErrorCode" in native
    assert "R297_NATIVE_PUBLICATION_ERROR=$publicationErrorCode" in native
    assert "R297_NATIVE_REPORT_PUBLICATION_FAILED" in native
    assert "publication_complete=true" in native
    assert "steps.native_publication.outputs.publication_complete == 'true'" in upload
    assert "steps.native_reports.outputs.publish_path != ''" in upload
    assert "steps.native_reports.outputs.publish_path" in upload
    assert "r297-windows-native-work" not in upload
    assert "r297-windows-native-stage" not in upload
    assert '<testsuite tests="1"' not in native


def test_trusted_windows_observer_is_fixed_source_and_does_not_execute_candidate():
    source = TRUSTED_OBSERVER.read_text(encoding="utf-8")
    assert "R297_TRUSTED_SIGNER_SHA" in source
    assert "SIGNER_SHA" in source
    assert "CODE_MANIFEST.json" in source
    assert '["git", "rev-parse", "HEAD"]' not in source
    assert "Electron process was not live when trusted observation began" in source
    assert "Electron executable identity mismatch" in source
    assert "latest_completed_at" in source
    assert "produce_electron_exit_event" in source
    assert "Start-Process" not in source


def test_r297_windows_acceptance_run_id_is_per_dispatch_not_static_environment_state():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pagehide_workflow_run_id:" in workflow
    assert "pagehide_workflow_run_attempt:" in workflow
    assert "required: true" in workflow
    assert "vars.R297_ACCEPTANCE_RUN_ID" not in workflow
    assert "formal-windows-acceptance:" in workflow
    assert "name: formal-windows-acceptance" in workflow
    assert "if: github.event_name == 'workflow_dispatch'" in workflow
    build, formal = workflow.split("  build-windows:", 1)[1].split("  formal-windows-acceptance:", 1)
    assert "environment: r297-controlled-canary" not in build
    assert "pagehide_workflow_run_id" in formal
    assert "pagehide_workflow_run_attempt" in formal
    assert "R297_TRUSTED_SIGNER_BOUNDARY_NOT_CONFIGURED" not in formal


def test_windows_native_job_runs_windows_only_boundaries_without_protected_environment():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    native = workflow.split("  windows-native-recovery-tests:", 1)[1].split(
        "  formal-windows-acceptance:", 1
    )[0]
    assert "runs-on: windows-latest" in native
    assert "environment:" not in native and "secrets." not in native
    assert "tests/r297_windows_native_boundary.ps1" in native
    assert "tests/test_r297_windows_file_security.py" in native
    assert "tests/test_r297_windows_recovery.py" in native
    assert "tests/test_r297_trusted_windows_observer.py" in native
    assert "tests/test_r297_trusted_host_installers.py" in native
    assert "R297_NATIVE_POWER_LOSS_REBOOT=NOT_TESTED" in native
    assert "R297_EVIDENCE_CLASS=TEST_ONLY" in native
    assert "R297_FORMAL_EVIDENCE=false" in native
    assert "name: test-only-r297-windows-native-recovery-" in native
    assert "classification.txt" in native
    assert "tzdata==2026.3" in requirements
    assert "ops/r297_evidence_trust_manifest.test.json text eol=lf" in attributes
    assert workflow.count("- ops/r297_evidence_trust_manifest.test.json") == 2
    assert workflow.count("- .gitattributes") == 2
    assert "--junitxml=$junit" in native
    assert "ops/r297_ci_redact.py" in native
    assert "Test-Path -LiteralPath $junit -PathType Leaf" in native
    assert "if-no-files-found: error" in native
    assert "r297-windows-native-work-$nonce" in native
    assert "steps.native_reports.outputs.publish_path" in native
    assert "R297_NATIVE_SOURCE_SHA=$env:RELEASE_SOURCE_SHA" in native
    assert "R297_NATIVE_RUN_ID=${{ github.run_id }}" in native
    assert "R297_NATIVE_RUN_ATTEMPT=${{ github.run_attempt }}" in native
    assert "id: native_boundary" not in native
    assert "continue-on-error: true" not in native
    assert "--timeout-seconds 300 -- pwsh -NoProfile -NonInteractive -File tests/r297_windows_native_boundary.ps1" in native
    assert "$boundarySupervisorResult.cleanup_error" in native
    assert "$boundarySupervisionComplete" in native
    assert "R297_NATIVE_PROBE_COMPLETE=true" in native
    assert "-and $boundarySupervisionComplete -and $reportsComplete" in native
    assert "$publicationReady = $copyComplete -and $boundarySupervisionComplete" in native
    assert "R297_NATIVE_BOUNDARY_RESULT=$boundaryResult" in native
    assert "tests/test_r297_trusted_host_installers.py `" not in native
    for nodeid in (
        "test_windows_producer_permissions_reach_children_with_inheritance_disabled",
        "test_windows_installer_separates_candidate_from_fixed_observer",
        "test_windows_relay_receipt_is_admin_installed_into_protected_root",
        "test_windows_installer_rejects_acl_bypass_privileges_and_stale_logons",
    ):
        assert f"tests/test_r297_trusted_host_installers.py::{nodeid}" in native
    upload = native.split("      - name: Upload sanitized native Windows reports", 1)[1]
    assert "native-work" not in upload
    assert "R297_NATIVE_PUBLICATION_ERROR" in native
    assert "R297_NATIVE_CLEANUP_ERROR=$cleanupErrorCode" in native
    job_env, steps = native.split("    steps:", 1)
    assert "ASSET_STORAGE_ROOT" not in job_env
    recovery = steps.split("      - name: Run complete Windows recovery regressions", 1)[1]
    assert "ASSET_STORAGE_ROOT: ${{ runner.temp }}\\r297-assets" in recovery.split("      - name:", 1)[0]


def test_windows_native_reports_publish_only_after_sanitized_validation():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    native = workflow.split("  windows-native-recovery-tests:", 1)[1].split(
        "  formal-windows-acceptance:", 1
    )[0]
    run_step, upload = native.split("      - name: Upload sanitized native Windows reports", 1)

    assert "id: native_reports" in run_step
    assert "r297-windows-native-work" in run_step
    assert "r297-windows-native-publish" in run_step
    assert "publication_ready=true" in run_step
    assert "Remove-Item -LiteralPath $full -Recurse" in run_step
    assert "Remove-Item -LiteralPath $publish -Recurse" not in run_step
    assert "Remove-OwnedTree $work" in run_step
    assert "Remove-OwnedTree $stage" in run_step
    assert "$workOwned" in run_step and "$stageOwned" in run_step
    assert "steps.native_reports.outputs.publication_ready == 'true'" in upload
    assert "steps.native_publication.outcome == 'success'" in upload
    assert "steps.native_publication.outputs.publication_complete == 'true'" in upload
    assert "steps.native_reports.outputs.publish_path != ''" in upload
    assert "steps.native_reports.outcome == 'success'" not in upload
    assert "!cancelled()" in upload
    assert "R297_NATIVE_REPORT_DIGEST_MISMATCH" in run_step
    assert "[IO.FileShare]::None" in run_step
    assert "$validatedDigests[$name]" in run_step
    assert "[IO.Path]::IsPathFullyQualified($rawPublish)" in run_step
    assert "R297_NATIVE_REPORT_PATH_INVALID" in run_step
    assert "R297_NATIVE_PUBLISH_NONCE" in run_step
    assert "[IO.Path]::GetDirectoryName($publish)" in run_step
    assert "[IO.Path]::GetPathRoot($publish)" in run_step
    assert "$publishItem.Attributes -band [IO.FileAttributes]::ReparsePoint" in run_step
    assert "R297_NATIVE_PRIMARY_ERROR=$primaryErrorCode" in run_step
    assert "R297_NATIVE_PUBLICATION_ERROR=$publicationErrorCode" in run_step
    assert "${{ steps.native_reports.outputs.publish_path }}/r297-windows-native-pytest.log" in upload
    assert "${{ steps.native_reports.outputs.publish_path }}/r297-windows-native-junit.xml" in upload
    assert "${{ steps.native_reports.outputs.publish_path }}/r297-windows-native-classification.txt" in upload
    assert "${{ runner.temp }}/r297-windows-native-pytest.log" not in upload
    assert "${{ runner.temp }}/r297-windows-native-junit.xml" not in upload
    assert '<testsuite tests="1"' not in native


def test_windows_native_pytest_is_owned_and_reaped_before_publication():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    supervisor = JOB_SUPERVISOR.read_text(encoding="utf-8")
    native = workflow.split("  windows-native-recovery-tests:", 1)[1].split(
        "  formal-windows-acceptance:", 1
    )[0]
    assert workflow.count("- ops/r297_windows_job_supervisor.py") == 2
    assert "python ops/r297_windows_job_supervisor.py" in native
    assert "R297_NATIVE_PROCESS_REAP_FAILED" in supervisor
    assert "R297_NATIVE_REPORT_CLEANUP_FAILED" in native
    assert "AssignProcessToJobObject" in supervisor
    assert "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE" in supervisor
    assert "TerminateJobObject" in supervisor
    assert "QueryInformationJobObject" in supervisor
    assert "CREATE_BREAKAWAY_FROM_JOB" not in supervisor
    assert supervisor.index("AssignProcessToJobObject(job, process)") < supervisor.index(
        'args.gate.write_text("go\\n"'
    )


def test_windows_job_supervisor_cleanup_failure_keeps_fixed_result(tmp_path, monkeypatch, capsys):
    from ops import r297_windows_job_supervisor as supervisor

    class FakeKernel:
        def CreateJobObjectW(self, *_args):
            return 1

        def SetInformationJobObject(self, *_args):
            return True

        def OpenProcess(self, *_args):
            return 0

        def TerminateJobObject(self, *_args):
            return False

        def CloseHandle(self, *_args):
            return True

    class FakeChild:
        pid = 123

        def poll(self):
            return None

        def terminate(self):
            raise RuntimeError("sensitive-cleanup-detail")

        def wait(self, **_kwargs):
            raise RuntimeError("sensitive-wait-detail")

    result = tmp_path / "result.json"
    monkeypatch.setattr(supervisor, "_api", lambda: FakeKernel())
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *_args, **_kwargs: FakeChild())
    assert supervisor._supervise(SimpleNamespace(
        gate=tmp_path / "gate", log=tmp_path / "log", result=result,
        timeout_seconds=1, command=["ignored"],
    )) == 1
    assert json.loads(result.read_text()) == {
        "cleanup_error": "R297_NATIVE_PROCESS_REAP_FAILED",
        "process_exit_code": None,
        "supervisor_error": "R297_NATIVE_PROCESS_OWNERSHIP_FAILED",
    }
    assert "sensitive" not in "".join(capsys.readouterr())


def test_windows_job_supervisor_records_process_handle_close_failure(tmp_path, monkeypatch):
    from ops import r297_windows_job_supervisor as supervisor

    class FakeKernel:
        close_calls = 0

        def CreateJobObjectW(self, *_args):
            return 1

        def SetInformationJobObject(self, *_args):
            return True

        def OpenProcess(self, *_args):
            return 2

        def AssignProcessToJobObject(self, *_args):
            return True

        def TerminateJobObject(self, *_args):
            return True

        def CloseHandle(self, *_args):
            self.close_calls += 1
            return self.close_calls != 1

    class FakeChild:
        pid = 123

        def poll(self):
            return 0

        def wait(self, **_kwargs):
            return 0

    result = tmp_path / "result.json"
    monkeypatch.setattr(supervisor, "_api", lambda: FakeKernel())
    monkeypatch.setattr(supervisor, "_active_processes", lambda *_args: 0)
    monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *_args, **_kwargs: FakeChild())
    assert supervisor._supervise(SimpleNamespace(
        gate=tmp_path / "gate", log=tmp_path / "log", result=result,
        timeout_seconds=1, command=["ignored"],
    )) == 1
    assert json.loads(result.read_text()) == {
        "cleanup_error": "R297_NATIVE_PROCESS_REAP_FAILED",
        "process_exit_code": 0,
        "supervisor_error": None,
    }


def test_native_boundary_probe_uses_real_windows_accounts_acl_handles_and_hardlinks():
    source = NATIVE_BOUNDARY.read_text(encoding="utf-8")
    assert "New-LocalUser" in source and "Remove-LocalUser" in source
    assert "Start-Process" in source and "-Credential" in source
    assert "FileShare]::Read" in source
    assert "New-Item -ItemType HardLink" in source
    assert "R297_NATIVE_ACL_NEGATIVE=PASS" in source
    assert "R297_NATIVE_HANDLE_DELETE_DENIAL=PASS" in source
    assert "R297_NATIVE_HARDLINK=PASS" in source
    assert source.index("if ($primaryErrorCode)") < source.index("if ($cleanupErrorCode)")
    assert "R297_NATIVE_CLEANUP_ERROR=$cleanupErrorCode" in source
    assert "R297_NATIVE_PROBE_COMPLETE=true" in source
    assert "R297_NATIVE_PROBE_FAILED" in source
    assert "} finally {\n  try {" in source
    assert "throw $primaryErrorCode" not in source
    assert source.index("} finally {") < source.index("R297_NATIVE_PROBE_COMPLETE=true") < source.index(
        "if ($primaryErrorCode)"
    )
