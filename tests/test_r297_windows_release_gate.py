import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "desktop" / "jd-workbench"
WORKFLOW = ROOT / ".github" / "workflows" / "r291-windows-workbench.yml"
ACCEPTANCE_SCRIPT = ROOT / "ops" / "r297_windows_acceptance.ps1"


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
    assert "tiantong-ai-jd-workbench-r297-windows" in workflow


def test_r297_windows_acceptance_requires_controlled_https_pairing_secrets():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    acceptance = ACCEPTANCE_SCRIPT.read_text(encoding="utf-8")

    assert "environment: r297-controlled-canary" in workflow
    for name in (
        "R297_WINDOWS_CANARY_BACKEND_HTTPS_URL",
        "R297_WINDOWS_CANARY_PAIRING_ISSUER_BEARER",
        "R297_WINDOWS_CANARY_SERVER_CERTIFICATE_BASE64",
    ):
        assert f"secrets.{name}" in workflow
        assert name in acceptance
    assert "R297_WINDOWS_CANARY_PAIRING_CODE" not in workflow + acceptance
    assert '"$backendOrigin/api/jd-workbench/pairing-codes"' in acceptance
    assert "$pairingCode | node $probe" in acceptance
    assert "$pairingCode = $null" in acceptance
    assert "R297_WINDOWS_CANARY_HEALTH_URL" not in workflow + acceptance
    assert "R297_WINDOWS_CANARY_SCHEDULER_URL" not in workflow + acceptance
    assert '"$backendOrigin/api/health"' in acceptance
    assert '"$backendOrigin/api/jd-workbench/internal/acceptance-status"' in acceptance
    assert "CONTROLLED_BACKEND_TLS_CERTIFICATE_MISMATCH" in acceptance
    assert "data_source = 'CONTROLLED_CANARY'" in acceptance
