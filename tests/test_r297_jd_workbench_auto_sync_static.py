from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "desktop" / "jd-workbench"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_r297_packages_the_auto_sync_coordinator_and_version():
    package = read(CLIENT / "package.json")
    lock = read(CLIENT / "package-lock.json")
    assert '"version": "2.97.0-r297"' in package
    assert '"auto-sync.js"' in package
    assert '"version": "2.97.0-r297"' in lock


def test_r297_main_starts_multi_store_automatic_sync_and_windows_autostart():
    main = read(CLIENT / "main.js")
    assert "createAutoSyncCoordinator" in main
    assert "stores.map(safeStoreState)" in main
    assert "syncAuthorizedStoreAutomatically" in main
    assert "automaticSyncCoordinator.start()" in main
    assert "automaticSyncCoordinator.runNow()" in main
    assert "beforeCycle: beginAutomaticSyncCycle" in main
    assert "afterCycle: finishAutomaticSyncCycle" in main
    assert "automaticSyncViewHidden" in main
    assert "app.setLoginItemSettings({ openAtLogin: true })" in main


def test_r297_auto_sync_has_five_minute_cycle_and_bounded_retries():
    coordinator = read(CLIENT / "auto-sync.js")
    assert "const DEFAULT_INTERVAL_MS = 5 * 60 * 1000" in coordinator
    assert "30 * 1000, 2 * 60 * 1000, 5 * 60 * 1000, 15 * 60 * 1000, 30 * 60 * 1000" in coordinator
    assert "60 * 1000, 3 * 60 * 1000, 10 * 60 * 1000" not in coordinator
    assert "HUMAN_ACTION_REQUIRED" in coordinator
    assert "CAPTCHA_REQUIRED" in coordinator
    assert "LOGIN_EXPIRED" in coordinator
    assert "if (inFlight) return inFlight" in coordinator


def test_r297_renderer_exposes_automatic_status_and_manual_sync_all_fallback():
    html = read(CLIENT / "renderer" / "index.html")
    renderer = read(CLIENT / "renderer" / "app.js")
    preload = read(CLIENT / "preload.js")
    assert "全自动同步" in html
    assert "立即同步全部" in html
    assert "automaticSyncStatus" in html
    assert "syncAllNow" in renderer
    assert "syncAllNow" in preload
    assert "SESSION_STOPPED: '自动轮询中'" in renderer


def test_r297_cloud_dashboard_refreshes_every_thirty_seconds():
    page = read(ROOT / "frontend" / "jd-dashboard.html")
    assert "R297" in page
    assert "30秒自动刷新" in page
    assert "setInterval(loadData,30000)" in page
