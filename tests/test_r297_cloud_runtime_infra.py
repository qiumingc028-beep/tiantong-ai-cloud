import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "services" / "jd-cloud-browser-runtime"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_runtime_image_contains_complete_non_root_x11_novnc_stack():
    dockerfile = read("services/jd-cloud-browser-runtime/Dockerfile")
    start = read("services/jd-cloud-browser-runtime/start-runtime.sh")

    for package in ("xvfb", "openbox", "x11vnc", "websockify", "novnc", "tini"):
        assert package in dockerfile
    assert "COPY services/jd-cloud-browser-runtime/" in dockerfile
    assert "desktop/jd-workbench/readonly-collector.js" in dockerfile
    assert "desktop/jd-workbench/security-policy.js" in dockerfile
    assert "USER runtime" in dockerfile
    assert "mcr.microsoft.com/playwright:v1.62.1-noble@sha256:" in dockerfile
    assert "nginx=1.24.0-2ubuntu7.17" in dockerfile
    assert "npx playwright install" not in dockerfile
    assert 'chromiumSandbox: true' in read("services/jd-cloud-browser-runtime/server.mjs")
    seccomp = json.loads(read("services/jd-cloud-browser-runtime/seccomp_profile.json"))
    assert seccomp["defaultAction"] == "SCMP_ACT_ERRNO"
    assert set(seccomp["syscalls"][0]["names"]) == {"clone", "setns", "unshare"}
    for process in ("Xvfb", "openbox", "x11vnc", "websockify", "node server.mjs"):
        assert process in start
    assert 'rm -f "/tmp/.X${display_number}-lock"' in start


def test_runtime_compose_uses_only_minimal_secrets_and_is_not_publicly_exposed():
    compose = read("docker-compose.prod.yml")
    collector = read("backend/services/jd_collectors.py")
    runtime = compose.split("\n  postgres:\n", 1)[0]
    backend = compose.split("\n  backend:\n", 1)[1].split("\n  worker:\n", 1)[0]
    worker = compose.split("\n  worker:\n", 1)[1].split("\n  nginx:\n", 1)[0]

    assert "env_file" not in runtime
    for name in ("JD_BROWSER_CAPTURE_TOKEN", "JD_BROWSER_CONTROL_TOKEN", "JD_BROWSER_VIEWER_TICKET_SIGNING_KEY", "JD_BROWSER_VIEWER_COOKIE_SIGNING_KEY"):
        assert name in runtime
    assert "JD_SESSION_MASTER_KEY" in runtime
    assert 'shm_size: "1gb"' in runtime
    assert "/tmp/.X11-unix" in runtime
    assert "/tmp/jd-cloud-profiles" in runtime and "tmpfs" in runtime
    assert "jd_session_archives:/data/jd-session-archives" in runtime
    assert "read_only: true" in runtime
    assert "cap_drop: [ALL]" in runtime
    assert "cap_add: [SYS_CHROOT]" in runtime
    assert "seccomp=services/jd-cloud-browser-runtime/seccomp_profile.json" in runtime
    assert "ports:" not in runtime
    assert '"6080"' not in runtime
    assert 'JD_SESSION_MASTER_KEY: ""' in backend
    assert 'JD_SESSION_MASTER_KEY: ""' in worker
    assert 'JD_BROWSER_CAPTURE_TOKEN: ""' in backend
    assert 'JD_BROWSER_CONTROL_TOKEN: ""' in worker
    assert 'JD_BROWSER_VIEWER_TICKET_SIGNING_KEY: ""' in worker
    assert 'JD_BROWSER_VIEWER_COOKIE_SIGNING_KEY: ""' in worker
    assert "JD_BROWSER_CAPTURE_TOKEN" in worker
    assert "JD_BROWSER_CONTROL_TOKEN" in backend
    assert 'JD_BROWSER_VIEWER_TICKET_SIGNING_KEY: ""' in backend
    assert 'JD_BROWSER_VIEWER_COOKIE_SIGNING_KEY: ""' in backend
    assert 'os.getenv("JD_BROWSER_CAPTURE_TOKEN"' in collector
    assert "JD_BROWSER_CONTROL_TOKEN" not in collector


def test_runtime_local_proxy_is_the_only_authenticated_novnc_path():
    nginx = read("nginx/production.conf")
    runtime_nginx = read("services/jd-cloud-browser-runtime/nginx.conf")
    start = read("services/jd-cloud-browser-runtime/start-runtime.sh")

    assert "proxy_pass http://jd-browser-runtime:8787" in nginx
    assert "jd-browser-runtime:6080" not in nginx
    assert "auth_request /_viewer_auth" in runtime_nginx
    assert "proxy_pass http://127.0.0.1:6080" in runtime_nginx
    assert "viewer/exchange/$store$is_args$args" in runtime_nginx
    assert "access_log off" in runtime_nginx
    assert "access_log off" in nginx
    assert "127.0.0.1:6080" in start
    assert "proxy_set_header Upgrade $http_upgrade" in nginx
    assert "proxy_set_header Connection \"upgrade\"" in nginx
    assert "6080" not in read("docker-compose.prod.yml").split("\n  postgres:\n", 1)[0]


def test_ci_builds_and_runs_runtime_with_real_health_xvfb_chromium_and_novnc_checks():
    workflow = read(".github/workflows/ci.yml")

    assert "workflow_dispatch:" in workflow
    assert "codex/r297-cloud-integration" in workflow
    assert "services/jd-cloud-browser-runtime/Dockerfile" in workflow
    assert "npm test" in workflow
    for name in ("JD_BROWSER_CAPTURE_TOKEN_REQUIRED", "JD_BROWSER_CONTROL_TOKEN", "JD_BROWSER_VIEWER_TICKET_SIGNING_KEY", "JD_BROWSER_VIEWER_COOKIE_SIGNING_KEY"):
        assert name in workflow
    for evidence in (
        "RUNTIME_HEALTH_STATUS=200",
        "RUNTIME_XVFB_PID=",
        "RUNTIME_CHROMIUM_PID=",
        "RUNTIME_NOVNC_WEBSOCKET=PASS",
        "RUNTIME_UID=",
        "RUNTIME_ENV_NAMES=",
        "RUNTIME_RESTART=PASS",
        "RESTART_COMMAND=PASS",
        "HEALTH_READY=PASS",
        "PROFILE_RESTORED=PASS",
        "OLD_COOKIE_REJECTED=PASS",
        "NEW_TICKET_ISSUED=PASS",
        "NEW_COOKIE_ACCEPTED=PASS",
        "OLD_TICKET_REPLAY_REJECTED=PASS",
        "REVOKE_PERSISTED=PASS",
        "SECOND_RESTART_OLD_COOKIE_REJECTED=PASS",
        "ARTIFACT_CLEANUP=PASS",
    ):
        assert evidence in workflow
    assert workflow.count('docker port "$container" 8787/tcp') >= 1
    assert 'docker port "$container" 6080/tcp' not in workflow


def test_runtime_package_uses_runtime_playwright_dependency_only():
    package = json.loads((RUNTIME / "package.json").read_text(encoding="utf-8"))

    assert package["dependencies"]["playwright"] == "1.62.1"
    assert "@playwright/test" not in package["dependencies"]


def test_database_restore_contract_is_fail_closed():
    deploy = read("ops/r297_workbench_deploy.sh")

    assert "pg_restore --clean --if-exists" in deploy
    assert "database.restore-test" in deploy
    assert "database_constraints" in deploy
    assert "cmp \"$BACKUP_DIR/database.before.inventory\" \"$BACKUP_DIR/database.restore-test.inventory\"" in deploy
    assert "cmp \"$BACKUP_DIR/database.before.constraints\" \"$BACKUP_DIR/database.restore-test.constraints\"" in deploy
    assert "database.after-restore.constraints" in deploy
    assert "sha256sum --check" in deploy
    assert "assert " not in deploy
    for stage in ("AFTER_ISOLATED_RESTORE", "AFTER_MIGRATION", "AFTER_HEALTH", "AFTER_LOGIN"):
        assert f"fail_if_requested {stage}" in deploy
    assert deploy.rindex("ROLLBACK_ACTIVE=0") > deploy.index("fail_if_requested AFTER_LOGIN")
    assert "Alembic downgrade does not restore deleted business data" in deploy

    preflight = read("ops/r297_workbench_preflight.sh")
    assert "assert payload" not in preflight
    assert "jd-browser-runtime" in preflight


def test_database_restore_failure_injection_hooks_fail_closed():
    result = subprocess.run(
        ["bash", "ops/r297_workbench_deploy.sh"],
        cwd=ROOT,
        env={**os.environ, "R297_SELF_TEST_FAILURE_INJECTION": "1"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "R297_FAILURE_INJECTION_SELF_TEST=PASS" in result.stdout
    restore_test = read("ops/r297_database_restore_contract_test.sh")
    workflow = read(".github/workflows/ci.yml")
    for contract in (
        "pg_restore --exit-on-error", "before.inventory", "after-rollback.inventory",
        "before.constraints", "after-rollback.constraints", "corrupt.dump"
    ):
        assert contract in restore_test
    assert "bash ops/r297_database_restore_contract_test.sh" in workflow
