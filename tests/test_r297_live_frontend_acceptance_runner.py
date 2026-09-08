from pathlib import Path
import os
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_live_frontend_runner_is_public_fail_closed_and_receiver_compatible():
    source = (ROOT / "tests/r297_live_frontend_acceptance.cjs").read_text(encoding="utf-8")

    for required in (
        "R297_WINDOWS_CANARY_BACKEND_HTTPS_URL",
        "R297_OWNER_STORAGE_STATE_PATH",
        "R297_EVIDENCE_NAMESPACE",
        "R297_EVIDENCE_TENANT_ID",
        "R297_EVIDENCE_COMPANY_ID",
        "R297_EVIDENCE_STORE_ID",
        "R297_ACCEPTANCE_RUN_ID",
        "R297_LIVE_OUTPUT_DIR",
        "/api/jd-workbench/stores/${config.storeId}/acceptance-status",
        "/api/jd-workbench/stores/${config.storeId}/login-session",
        "/api/jd-workbench/stores/${storeId}/login-ticket",
        "/jd-browser/novnc/${id}/exchange",
        "/jd-browser/novnc/${config.storeId}/vnc.html",
        "/jd-browser/novnc/${storeId}/websockify",
        "event_is_trusted",
        "PageTransitionEvent",
        "synthetic_event_rejected",
        "r297-native-pagehide-evidence-${config.releaseSha}.json",
        "r297-native-pagehide-manifest-${config.releaseSha}.json",
        "R297_AUTHENTICATED_OBSERVER_REQUIRED",
    ):
        assert required in source

    assert "/internal/jd-browser/" not in source
    assert "scheduler_continues:" not in source
    assert source.count("scheduler_continues") == 2
    assert "'scheduler_continues'" in source
    assert "event.payload.scheduler_continues" in source
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "session_id" not in source
    assert "ignoreHTTPSErrors" not in source
    assert "--ignore-certificate-errors" not in source

    # The raw browser event remains the exact receiver input; scope/run binding is
    # recorded separately from the browser payload and is signed off-browser.
    assert "['event', 'observed_at', 'release_sha', 'store_id']" in source
    assert "context.exposeBinding('__tiantongR297AuthenticatedObserver'" in source
    assert "httpOnly" in source and "sameSite" in source and "secure" in source
    assert "redactSelectors" in source
    assert "zip', ['-j', '-X'" in source
    assert "assert.equal(consoleErrors.length, 0" in source
    assert "assert.equal(pageErrors.length, 0" in source
    assert "assert.equal(failedRequests.length, 0" in source
    assert "context.on('console'" in source
    assert "context.on('weberror'" in source
    assert "webError.error()" in source
    assert "context.on('requestfailed'" in source
    assert "page.on('console'" not in source
    assert "context.request.delete(" in source
    assert "sessionCleanupRequired = true" in source
    assert "process.once('SIGINT'" in source
    assert "process.once('SIGTERM'" in source
    assert "popup.waitForEvent('websocket'" in source
    assert "验收输出目录必须为空" in source
    assert "runner checkout HEAD与验收release不一致" in source
    assert "git', ['rev-parse', 'HEAD']" in source
    assert "exactKeys(createBody, ['store_id', 'status', 'expires_in'])" in source
    assert "createBody.expires_in <= 600" in source
    assert "const controller = new AbortController()" in source


def test_live_frontend_runner_reports_every_missing_protected_input_without_starting_browser():
    command = ["node", str(ROOT / "tests/r297_live_frontend_acceptance.cjs"), "--check-config"]
    env = {key: value for key, value in os.environ.items() if not key.startswith("R297_")}

    completed = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)

    assert completed.returncode == 1
    for name in (
        "R297_WINDOWS_CANARY_BACKEND_HTTPS_URL",
        "R297_EXPECTED_RELEASE_SHA",
        "R297_ACCEPTANCE_RUN_ID",
        "R297_OWNER_STORAGE_STATE_PATH",
        "R297_LIVE_OUTPUT_DIR",
        "R297_EVIDENCE_NAMESPACE",
        "R297_EVIDENCE_TENANT_ID",
        "R297_EVIDENCE_COMPANY_ID",
        "R297_EVIDENCE_STORE_ID",
        "R297_EVIDENCE_CROSS_STORE_ID",
        "R297_EVIDENCE_CROSS_TENANT_STORE_ID",
        "R297_PAGE_EVENT_RECEIVER_ACK_PATH",
        "R297_AUTHENTICATED_OBSERVER_ACK_PATH",
    ):
        assert name in completed.stderr
    assert "Cannot find module 'playwright'" not in completed.stderr


def test_live_frontend_runner_closes_receiver_viewer_and_timeout_gaps():
    source = (ROOT / "tests/r297_live_frontend_acceptance.cjs").read_text(encoding="utf-8")

    for required in (
        "R297_PAGE_EVENT_RECEIVER_ACK_PATH",
        "R297_AUTHENTICATED_OBSERVER_ACK_PATH",
        "verifySignedAcknowledgement",
        "verify_signed_event",
        "SIGNATURE_RE",
        "assertPageReceiverAcknowledgement",
        "assertObserverAcknowledgement",
        "waitForViewerReady",
        "viewer_rfb_ready",
        "receiver_acknowledgement",
        "authenticated_observer",
    ):
        assert required in source

    assert "required('R297_ACCEPTANCE_RUN_ATTEMPT')" not in source
    assert "required('R297_ACCEPTANCE_CHALLENGE')" not in source
    assert "verifier.stdin.end(content)" in source
    assert "spawnSync('python3'" not in source
    assert "verify_signed_event(event" in source
    assert "服务端回执必须位于浏览器验收输出目录之外" in source
    assert "if (matches) sessionCleanupRequired = true" in source
    assert source.index("await createSettlement") < source.index("context.request.delete(")
    assert "verifier.once('close'" in source

    assert "popup.waitForEvent('websocket'" in source
    assert "noVNC_connected" in source
    assert "scheduler_continues: true" not in source
    assert source.index("const receiver = await") < source.index("const deleted = await")
    assert source.index("const observer = await") < source.index("const deleted = await")
    assert "existing_socket_revoked" in source
    assert source.index("const deleted = await") < source.index("撤销后既有Viewer WebSocket关闭")
    assert source.index("撤销后既有Viewer WebSocket关闭") < source.index("const revoked = await")
    assert "const [, viewer] = await Promise.all([" in source
    assert source.index("const revocationReady =") < source.index("const deleted = await")
    assert source.index("assertLiveViewerForRevocation(revocationViewer)") < source.index("const deleted = await")
    assert "() => revocationViewer.websocket.isClosed()" in source
    assert "R297OwnerLogin.openViewer({" in source

    completed = subprocess.run(
        ["node", str(ROOT / "tests/r297_live_frontend_acceptance.cjs"), "--self-test"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert "R297_LIVE_FRONTEND_SELF_TEST=PASS" in completed.stdout
