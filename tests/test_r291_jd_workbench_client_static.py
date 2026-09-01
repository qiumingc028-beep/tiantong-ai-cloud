import json
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "desktop" / "jd-workbench"


def read(relative_path: str) -> str:
    return (CLIENT / relative_path).read_text(encoding="utf-8")


def test_r291_desktop_client_has_minimum_runnable_files_and_fixed_electron():
    required = {
        "package.json",
        "main.js",
        "preload.js",
        "cloud-client.js",
        "cloud-client.behavior.test.js",
        "security-policy.js",
        "security-policy.behavior.test.js",
        "renderer/index.html",
        "renderer/app.js",
        "renderer/styles.css",
    }
    assert required <= {
        str(path.relative_to(CLIENT))
        for path in CLIENT.rglob("*")
        if path.is_file()
    }
    package = json.loads(read("package.json"))
    assert package["main"] == "main.js"
    assert package["scripts"]["start"] == "electron ."
    assert package["devDependencies"]["electron"] == "44.0.0"
    assert "security-policy.behavior.test.js" in package["scripts"]["check"]
    assert "cloud-client.behavior.test.js" in package["scripts"]["check"]


def test_r291_uses_webcontentsview_and_never_deprecated_or_embedded_views():
    main = read("main.js")
    renderer = read("renderer/index.html")
    assert "WebContentsView" in main
    assert "BrowserView" not in main
    assert "<iframe" not in renderer.lower()
    assert "<webview" not in renderer.lower()


def test_r291_remote_view_has_exact_persistent_store_partition_and_security_preferences():
    main = read("main.js")
    assert "persist:jd-${canonicalStoreUuid(storeUuid)}" in main
    assert "STORE_UUID_PATTERN" in main
    assert "session.fromPartition(partition" in main
    assert "targetSession.isPersistent()" in main
    for setting in (
        "nodeIntegration: false",
        "nodeIntegrationInWorker: false",
        "nodeIntegrationInSubFrames: false",
        "contextIsolation: true",
        "sandbox: true",
        "webSecurity: true",
        "allowRunningInsecureContent: false",
        "webviewTag: false",
        "devTools: false",
        "navigateOnDragDrop: false",
    ):
        assert setting in main


def test_r291_jd_allowlist_is_https_exact_host_only_and_has_no_wildcards():
    policy = read("security-policy.js")
    host_block = re.search(r"JD_HTTPS_HOSTS\s*=.*?Set\(\[(.*?)\]\)\)", policy, re.S)
    assert host_block
    hosts = re.findall(r"'([^']+)'", host_block.group(1))
    assert "shop.jd.com" in hosts
    assert "passport.shop.jd.com" in hosts
    assert hosts
    assert all("*" not in host and "://" not in host and "/" not in host for host in hosts)
    assert "parsed.protocol !== 'https:'" in policy
    assert "JD_HTTPS_HOSTS.has(parsed.hostname)" in policy
    assert "STATIC_RESOURCE_TYPES" in policy
    assert "isAuditedMainFrameRoute" in policy
    assert "ENDPOINT_NOT_AUDITED" in policy
    assert "new Set(['GET', 'HEAD'])" in policy
    assert ".endsWith(" not in policy
    assert "parsed.hostname.endsWith" not in policy


def test_r291_inactive_partition_is_denied_before_url_and_auth_checks():
    policy = read("security-policy.js")
    main = read("main.js")
    inactive_position = policy.index("if (isActive !== true)")
    target_position = policy.index("const target = parseAllowedHttpsUrl(url)")
    assert inactive_position < target_position
    assert "INACTIVE_PARTITION" in policy
    assert "isActive: isPartitionActive(storeUuid, partition, targetSession)" in main
    assert "decision.code !== 'INACTIVE_PARTITION'" in main


def test_r291_authentication_post_is_exact_context_operation_and_active_main_frame_only():
    policy = read("security-policy.js")
    auth_block = re.search(r"JD_AUTH_ROUTES\s*=.*?\[(.*?)\]\);", policy, re.S)
    assert auth_block
    assert "hostname: 'passport.jd.com', pathname: '/new/login.aspx'" in auth_block.group(1)
    assert "hostname: 'passport.shop.jd.com', pathname: '/login/index.action/jdm'" in auth_block.group(1)
    assert "jshopx" not in auth_block.group(1)
    assert "isMainFrameSource === true" in policy
    assert "isAuthenticationContextRoute(currentMainFrameUrl)" in policy
    assert "isAuthenticationApiTarget(target.href)" in policy
    assert "dsm.account.service.LoginFacade.login" in policy
    assert "dsm.account.service.VenderAccountConfigFacade.getConfig" in policy
    assert "parsed.pathname === '/jdm/home'" in policy
    assert "JD_AUTH_HOSTS" not in policy


def test_r291_node_policy_behavior_includes_negative_cases():
    node = shutil.which("node")
    assert node, "Node.js is required for the R291 desktop policy behavior gate"
    completed = subprocess.run(
        [node, str(CLIENT / "security-policy.behavior.test.js")],
        cwd=CLIENT,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert "R297_SECURITY_POLICY_AND_RECOGNITION=PASS" in completed.stdout
    cloud_completed = subprocess.run(
        [node, str(CLIENT / "cloud-client.behavior.test.js")],
        cwd=CLIENT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert cloud_completed.returncode == 0, cloud_completed.stderr
    assert "R297_CLOUD_CLIENT_BEHAVIOR=4_SIGNED_REQUESTS_PASS" in cloud_completed.stdout


def test_r291_does_not_claim_unverified_business_write_count_is_zero():
    main = read("main.js")
    renderer = read("renderer/app.js")
    html = read("renderer/index.html")
    assert "businessWriteCount: 0" not in main
    assert "businessWriteStatus: 'UNVERIFIED'" in main
    assert "BUSINESS_WRITE_COUNT=${snapshot.businessWriteStatus}" in renderer
    assert "BUSINESS_WRITE_COUNT=UNVERIFIED" in html


def test_r291_blocks_privileged_remote_page_capabilities():
    main = read("main.js")
    preload = read("preload.js")
    remote_surface = main + "\n" + preload
    for forbidden in (
        "capturePage",
        ".debugger",
        "shell.openExternal",
        "cookies.get",
        "cookies.set",
        "contentTracing",
        "netLog",
    ):
        assert forbidden not in remote_surface
    assert "executeJavaScript(buildRecognizerScript())" in main
    assert "executeJavaScript(SNAPSHOT_SCRIPT, true)" in main
    assert "executeJavaScript" not in preload
    assert "setWindowOpenHandler" in main
    assert "will-download" in main
    assert "event.preventDefault()" in main
    assert "setPermissionRequestHandler" in main
    assert "setPermissionCheckHandler" in main


def test_r291_reports_unknown_domain_captcha_and_risk_as_human_action_required():
    policy = read("security-policy.js")
    main = read("main.js")
    renderer = read("renderer/app.js")
    assert "UNKNOWN_DOMAIN" in policy
    assert "RISK_OR_CAPTCHA" in policy
    assert "HUMAN_ACTION_REQUIRED" in main
    assert "page-title-updated" in main
    assert "验证码|安全验证|风险验证|风控|身份核验" in main
    assert "CAPTCHA" in renderer
    assert "RISK_CONTROL" in renderer
    assert "LOGIN_EXPIRED" in renderer


def test_r291_switch_lock_and_suspend_revoke_network_and_clear_service_workers():
    main = read("main.js")
    assert "app.requestSingleInstanceLock()" in main
    assert "app.on('second-instance'" in main
    assert "powerMonitor.on('lock-screen'" in main
    assert "powerMonitor.on('unlock-screen'" in main
    assert "powerMonitor.on('suspend'" in main
    assert "powerMonitor.on('resume'" in main
    assert "remoteViewAccessPaused = true" in main
    assert "if (remoteViewAccessPaused)" in main
    assert "throw new Error('REMOTE_VIEW_PAUSED')" in main
    assert "activeContext = null" in main
    assert "context.disposed = true" in main
    assert "serviceWorkers.stopAllRunning()" in main
    assert "clearStorageData({ storages: ['serviceworkers'] })" in main
    assert "closeAllConnections()" in main
    assert "contents.close({ waitForBeforeUnload: false })" in main
    stop_block = re.search(
        r"function stopForSystemEvent\(reason\) \{(.*?)\n\}", main, re.S
    )
    assert stop_block
    assert "queueViewTransition" not in stop_block.group(1)
    assert "Promise.all([destroyActiveView(reason), closeCollectionView()])" in stop_block.group(1)
    destroy_call = main.index("await destroyActiveView('STORE_SWITCHED')")
    new_view = main.index("const view = new WebContentsView", destroy_call)
    assert destroy_call < new_view
    assert "AUTHORIZATION_REFRESH_MS = 30_000" in main
    assert "AUTHORIZATION_LEASE_MS = 45_000" in main
    assert "Date.now() < authorizationLeaseExpiresAt" in main
    assert "purgeStoreSession" in main
    assert "await targetSession.clearStorageData()" in main


def test_r291_stores_only_arrive_from_fixed_cloud_pairing_and_token_is_protected():
    main = read("main.js")
    preload = read("preload.js")
    cloud = read("cloud-client.js")
    html = read("renderer/index.html")
    assert "https://internal.tiantongai.com" in cloud
    assert "/api/jd-workbench/pair" in cloud
    assert "/api/jd-workbench/stores" in cloud
    assert "/api/jd-workbench/heartbeat" in cloud
    assert "url !== PAIR_URL && url !== STORES_URL" in cloud
    assert "safeStorage.encryptString" in cloud
    assert "safeStorage.decryptString" in cloud
    assert "encryptedPrivateKey" in cloud
    assert "generateKeyPairSync('rsa'" in cloud
    assert "X-R291-Timestamp" in cloud
    assert "X-R291-Nonce" in cloud
    assert "X-R291-Signature" in cloud
    assert "getSelectedStorageBackend() === 'basic_text'" in cloud
    assert "SECURE_STORAGE_BASIC_TEXT_REJECTED" in cloud
    assert "headers.Authorization = `Device ${identity.token}`" in cloud
    assert "device_token" not in preload
    assert "addStore" not in preload
    assert "removeStore" not in preload
    assert 'id="storeUuid"' not in html
    assert "客户端不能手工添加" in html
    assert "rows.map(normalizeCloudStore)" in main
    assert "raw.partition !== partition" in main


def test_r297_collection_is_whitelisted_readonly_and_has_no_mock_business_data():
    main = read("main.js")
    preload = read("preload.js")
    html = read("renderer/index.html")
    assert "querySelector" not in main
    assert "querySelector" not in preload
    assert "collectionEnabled: true" in main
    assert "只读取官方页面白名单经营指标和订单状态" in html
    assert "readonly-collector" in main
    assert "READ_ONLY_WRITE_BLOCKED" in main
    assert "暂无数据" in html
    assert not re.search(r"[¥￥]\s*\d", html)


def test_r291_preload_exposes_only_typed_workbench_operations():
    preload = read("preload.js")
    assert "contextBridge.exposeInMainWorld" in preload
    assert "ipcRenderer.invoke" in preload
    assert "ipcRenderer.send(" not in preload
    assert "loadURL" not in preload
    assert "require('node:fs')" not in preload
    assert "getSnapshot" in preload
    assert "pair:" in preload
    assert "refreshStores:" in preload
    assert "selectStore" in preload
    assert "reportHumanAction" in preload


def test_r291_shell_has_strict_csp_and_no_renderer_network_access():
    html = read("renderer/index.html")
    assert "Content-Security-Policy" in html
    assert "script-src 'self'" in html
    assert "connect-src 'none'" in html
    assert "object-src 'none'" in html
    assert "frame-src 'none'" in html
    assert "form-action 'none'" in html
