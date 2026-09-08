import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "desktop" / "jd-workbench"
WORKFLOW = ROOT / ".github" / "workflows" / "r291-windows-workbench.yml"
ACCEPTANCE_SCRIPT = ROOT / "ops" / "r297_windows_acceptance.ps1"
EVENT_SIGNER = ROOT / "ops" / "r297_windows_event_signer.py"
TRUSTED_OBSERVER = ROOT / "ops" / "r297_trusted_windows_observer.py"


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

    assert "R297_TRUSTED_SIGNER_BOUNDARY_NOT_CONFIGURED" in candidate
    assert "R297_WINDOWS_RUNNER_PRIVATE_KEY_BASE64" not in candidate
    assert "R297_WINDOWS_RUNNER_PRIVATE_KEY_PATH" not in candidate
    assert "r297_windows_acceptance.ps1" not in candidate


def test_windows_build_is_secretless_and_publishes_before_independent_formal_gate():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    build, formal = workflow.split("  build-windows:", 1)[1].split("  formal-windows-acceptance:", 1)
    assert "environment:" not in build
    assert "secrets." not in build
    assert "R297_TRUSTED_SIGNER_BOUNDARY_NOT_CONFIGURED" not in build
    assert "npm run dist:win" in build
    assert "actions/upload-artifact@v7" in build
    assert "name: tiantong-ai-jd-workbench-r297-build-${{ github.event.pull_request.head.sha || github.sha }}" in build
    assert "if-no-files-found: error" in build
    assert "needs: build-windows" in formal
    assert "if: github.event_name == 'workflow_dispatch'" in formal
    assert "environment: r297-controlled-canary" in formal
    assert "actions/download-artifact@v8" in formal
    assert "name: tiantong-ai-jd-workbench-r297-build-${{ github.sha }}" in formal
    assert "ref: ${{ github.sha }}" in formal
    assert "R297_TRUSTED_SIGNER_BOUNDARY_NOT_CONFIGURED" in formal
    assert "secrets." not in formal
    assert "./ops/r297_windows_acceptance.ps1" not in formal


def test_trusted_windows_observer_is_fixed_source_and_does_not_execute_candidate():
    source = TRUSTED_OBSERVER.read_text(encoding="utf-8")
    assert "R297_TRUSTED_SIGNER_SHA" in source
    assert '["git", "rev-parse", "HEAD"]' in source
    assert "Electron process was not live when trusted observation began" in source
    assert "Electron executable identity mismatch" in source
    assert "latest_completed_at" in source
    assert "produce_electron_exit_event" in source
    assert "Start-Process" not in source


def test_r297_windows_acceptance_run_id_is_per_dispatch_not_static_environment_state():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pagehide_workflow_run_id:" in workflow
    assert "required: true" in workflow
    assert "vars.R297_ACCEPTANCE_RUN_ID" not in workflow
    assert "formal-windows-acceptance:" in workflow
    assert "name: formal-windows-acceptance" in workflow
    assert "if: github.event_name == 'workflow_dispatch'" in workflow
    build, formal = workflow.split("  build-windows:", 1)[1].split("  formal-windows-acceptance:", 1)
    assert "environment: r297-controlled-canary" not in build
    assert "actions/setup-node@v7" in formal
    assert 'node-version: "24"' in formal
    assert "R297_TRUSTED_SIGNER_BOUNDARY_NOT_CONFIGURED" in formal
