from __future__ import annotations

import hashlib
import json
import base64
import os
import shutil
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi import HTTPException

import backend.agent_runtime.executors.computer.openclaw_adapter as adapter_module
import backend.agent_runtime.executors.computer.runtime as runtime_module
from backend.agent_runtime.executors.computer.models import ComputerEvidence
from backend.agent_runtime.executors.computer.openclaw_adapter import (
    WEBSOCKET_GUID,
    OpenClawAdapter,
    _WebSocket,
    validate_capture_target_url,
)
from backend.config import ConfigurationError, Settings
from tests.test_computer_workflows import _create_owned_task, _enable_workflow_flags


@pytest.fixture
def chrome_path():
    candidates = [
        os.getenv("PAGE_CAPTURE_TEST_CHROME", ""),
        shutil.which("google-chrome") or "",
        shutil.which("chromium") or "",
        shutil.which("chromium-browser") or "",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    pytest.skip("real page capture requires an installed Chrome or Chromium executable")


@contextmanager
def local_page(requests: list[str] | None = None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if requests is not None:
                requests.append(self.path)
            if self.path == "/style.css":
                body = b"body{background:#f0f4ff}"
                content_type = "text/css"
            else:
                body = b'<!doctype html><link rel="stylesheet" href="/style.css"><title>R185 isolated page</title><h1>R185 real PNG</h1>'
                content_type = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/page"
    finally:
        server.shutdown()
        thread.join(timeout=2)


@contextmanager
def redirecting_page(destination: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", destination)
            self.end_headers()

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/redirect"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_capture_target_url_requires_exact_allowlisted_origin(monkeypatch):
    allowed = ["http://127.0.0.1:59200"]

    assert validate_capture_target_url(
        "http://127.0.0.1:59200/computer-workflow-center.html",
        allowed,
    ) == "http://127.0.0.1:59200/computer-workflow-center.html"

    for blocked in [
        None,
        "",
        "https://127.0.0.1:59200/computer-workflow-center.html",
        "http://127.0.0.1:59201/computer-workflow-center.html",
        "http://127.0.0.1.evil:59200/computer-workflow-center.html",
        "http://user:password@127.0.0.1:59200/computer-workflow-center.html",
        "file:///tmp/screenshot.html",
        "data:text/html,hello",
        "javascript:alert(1)",
    ]:
        with pytest.raises(ValueError):
            validate_capture_target_url(blocked, allowed)

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SERVICE_ROLE", "backend")
    monkeypatch.setenv("OPENCLAW_ADAPTER_ENABLED", "true")
    monkeypatch.setenv("ASSET_STORAGE_ROOT", "/private/tmp/r185-assets")
    monkeypatch.setenv("PAGE_CAPTURE_ALLOWED_ORIGINS", "http://127.0.0.1:59201")
    for name in (
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_USER",
        "DATABASE_PASSWORD",
        "REDIS_HOST",
        "REDIS_PORT",
        "REDIS_DB",
        "REDIS_PASSWORD",
        "REDIS_USERNAME",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError, match="restricted to test origin"):
        Settings()
    monkeypatch.setenv("PAGE_CAPTURE_ALLOWED_ORIGINS", allowed[0])
    assert Settings().PAGE_CAPTURE_ALLOWED_ORIGINS == allowed


def _server_frame(*, final: bool, opcode: int, data: bytes) -> bytes:
    first = (0x80 if final else 0) | opcode
    if len(data) < 126:
        return bytes([first, len(data)]) + data
    return bytes([first, 126]) + len(data).to_bytes(2, "big") + data


def test_websocket_validates_handshake_and_reassembles_fragmented_json(monkeypatch):
    payload = json.dumps({"id": 1, "result": {"data": "x" * 200}}).encode()

    class FakeSocket:
        def __init__(self, *, valid_accept: bool):
            self.valid_accept = valid_accept
            self.buffer = bytearray()

        def settimeout(self, _timeout):
            return None

        def sendall(self, data):
            if not data.startswith(b"GET "):
                return
            request_headers = {
                name.lower(): value.strip()
                for name, value in (
                    line.split(":", 1)
                    for line in data.decode("ascii").split("\r\n")[1:]
                    if ":" in line
                )
            }
            accept = base64.b64encode(
                hashlib.sha1(
                    f"{request_headers['sec-websocket-key']}{WEBSOCKET_GUID}".encode("ascii")
                ).digest()
            ).decode("ascii")
            if not self.valid_accept:
                accept = "invalid"
            response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode("ascii")
            split = 80
            self.buffer.extend(response + _server_frame(final=False, opcode=0x1, data=payload[:split]))
            self.buffer.extend(_server_frame(final=True, opcode=0x0, data=payload[split:]))

        def recv(self, length):
            data = bytes(self.buffer[:length])
            del self.buffer[:length]
            return data

        def close(self):
            return None

    monkeypatch.setattr(adapter_module.socket, "create_connection", lambda *_args, **_kwargs: FakeSocket(valid_accept=True))
    websocket = _WebSocket("ws://127.0.0.1:9222/devtools/page/r185", 1)
    assert websocket._recv_json() == json.loads(payload)

    monkeypatch.setattr(adapter_module.socket, "create_connection", lambda *_args, **_kwargs: FakeSocket(valid_accept=False))
    with pytest.raises(RuntimeError, match="handshake failed"):
        _WebSocket("ws://127.0.0.1:9222/devtools/page/r185", 1)


def test_real_adapter_captures_private_png_with_isolated_profile(tmp_path, monkeypatch, chrome_path):
    processes = []
    commands = []
    real_popen = adapter_module.subprocess.Popen

    def recording_popen(command, **kwargs):
        commands.append(command)
        process = real_popen(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(adapter_module.subprocess, "Popen", recording_popen)
    with local_page() as target_url:
        origin = f"{urlsplit(target_url).scheme}://{urlsplit(target_url).netloc}"
        settings = SimpleNamespace(
            PAGE_CAPTURE_ALLOWED_ORIGINS=[origin],
            PAGE_CAPTURE_CHROME_PATH=chrome_path,
            PAGE_CAPTURE_OUTPUT_ROOT=str(tmp_path / "captures"),
            PAGE_CAPTURE_TIMEOUT_SECONDS=15,
            OPENCLAW_ADAPTER_ENABLED=True,
            ISOLATED_DESKTOP_ENABLED=False,
        )
        context = SimpleNamespace(
            session_id="r185-session",
            trace_id="r185-trace",
            action_type="截图",
            target_url=target_url,
            target_application="独立无头浏览器",
            target_window=target_url,
            text_input=None,
            coordinates=None,
        )

        outcome = OpenClawAdapter(settings=settings).execute_action(context)

    screenshot = Path(urlsplit(outcome.screenshot_reference).path)
    content = screenshot.read_bytes()
    assert content.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(content) > 100
    assert outcome.action_result["sha256"] == hashlib.sha256(content).hexdigest()
    assert outcome.action_result["provider"] == "chrome_cdp_page_capture"
    assert outcome.audit_metadata["provider"] == "chrome_cdp_page_capture"
    assert outcome.audit_metadata["desktop_capture_calls"] == 0
    assert screenshot.stat().st_mode & 0o777 == 0o600
    assert screenshot.parent.stat().st_mode & 0o777 == 0o700
    assert len(processes) == 1 and processes[0].poll() is not None
    assert any(argument.startswith("--user-data-dir=") for argument in commands[0])
    assert all("Library/Application Support/Google/Chrome" not in argument for argument in commands[0])
    assert not list(tmp_path.rglob("profile-*"))


def test_adapter_source_has_no_desktop_capture_or_mock_success_path():
    source = Path(adapter_module.__file__).read_text(encoding="utf-8")

    for forbidden in ("screencapture", "CGWindowListCreateImage", "mock_openclaw", "MockOpenClawTransport"):
        assert forbidden not in source


def test_real_mode_never_selects_mock_executor(monkeypatch):
    settings = SimpleNamespace(OPENCLAW_ADAPTER_ENABLED=True)
    session = SimpleNamespace(executor_type="mock", environment_type="test")
    monkeypatch.setattr(runtime_module, "get_settings", lambda: settings)

    assert isinstance(runtime_module._executor_for_settings(session), OpenClawAdapter)

    settings.OPENCLAW_ADAPTER_ENABLED = False
    settings.IS_PRODUCTION = False
    session.executor_type = "openclaw"
    with pytest.raises(HTTPException, match="真实电脑执行适配器未启用"):
        runtime_module._executor_for_settings(session)


def test_real_adapter_rejects_cross_origin_redirect_without_artifacts(tmp_path, chrome_path):
    destination_requests = []
    with local_page(destination_requests) as destination, redirecting_page(destination) as target_url:
        origin = f"{urlsplit(target_url).scheme}://{urlsplit(target_url).netloc}"
        settings = SimpleNamespace(
            PAGE_CAPTURE_ALLOWED_ORIGINS=[origin],
            PAGE_CAPTURE_CHROME_PATH=chrome_path,
            PAGE_CAPTURE_OUTPUT_ROOT=str(tmp_path / "captures"),
            PAGE_CAPTURE_TIMEOUT_SECONDS=15,
            OPENCLAW_ADAPTER_ENABLED=True,
        )
        context = SimpleNamespace(
            session_id="r185-redirect",
            trace_id="r185-redirect",
            action_type="截图",
            target_url=target_url,
        )

        with pytest.raises(ValueError, match="allowlisted origin"):
            OpenClawAdapter(settings=settings).execute_action(context)

    assert not list(tmp_path.rglob("*.png"))
    assert not list(tmp_path.rglob("profile-*"))
    assert destination_requests == []


def test_workflow_executes_real_page_capture_provider(client, admin_headers, monkeypatch, tmp_path, chrome_path):
    with local_page() as target_url:
        origin = f"{urlsplit(target_url).scheme}://{urlsplit(target_url).netloc}"
        settings = _enable_workflow_flags(monkeypatch)
        settings.OPENCLAW_ADAPTER_ENABLED = True
        settings.PAGE_CAPTURE_ALLOWED_ORIGINS = [origin]
        settings.PAGE_CAPTURE_CHROME_PATH = chrome_path
        settings.PAGE_CAPTURE_OUTPUT_ROOT = str(tmp_path / "captures")
        settings.PAGE_CAPTURE_TIMEOUT_SECONDS = 15
        monkeypatch.setattr("backend.agent_runtime.executors.computer.runtime.get_settings", lambda: settings)
        task_id = _create_owned_task(client, admin_headers, "R185 real page capture")
        created = client.post(
            "/api/v2/computer/workflows",
            headers=admin_headers,
            json={
                "task_id": task_id,
                "goal": "Capture the isolated test page",
                "max_steps": 2,
                "steps": [
                    {"action_type": "截图", "target_url": target_url, "expected_result": "真实PNG"},
                    {"action_type": "等待", "expected_result": "安全结束"},
                ],
            },
        )
        assert created.status_code == 200
        workflow_id = created.json()["workflow"]["workflow_id"]
        assert client.post(f"/api/v2/computer/workflows/{workflow_id}/approve", headers=admin_headers).status_code == 200

        started = client.post(f"/api/v2/computer/workflows/{workflow_id}/start", headers=admin_headers)

    assert started.status_code == 200
    payload = started.json()
    action_result = json.loads(payload["action"]["result"])
    screenshot = Path(urlsplit(payload["action"]["screenshot_after"]).path)
    assert payload["step"]["status"] == "已完成"
    assert action_result["provider"] == "chrome_cdp_page_capture"
    assert screenshot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    screenshot.unlink()


def test_capture_endpoint_rejects_missing_target_before_evidence_write(
    client, owner_headers, monkeypatch, test_db
):
    settings = _enable_workflow_flags(monkeypatch)
    settings.OPENCLAW_ADAPTER_ENABLED = True
    settings.PAGE_CAPTURE_ALLOWED_ORIGINS = ["http://127.0.0.1:59200"]
    settings.PAGE_CAPTURE_CHROME_PATH = "/private/tmp/not-needed-for-missing-target"
    settings.PAGE_CAPTURE_OUTPUT_ROOT = "/private/tmp/tiantong-r185-test-captures"
    monkeypatch.setattr(runtime_module, "get_settings", lambda: settings)
    created = client.post(
        "/api/v2/computer/sessions",
        headers=owner_headers,
        json={"executor_type": "openclaw", "environment_type": "test"},
    )
    assert created.status_code == 200
    session_id = created.json()["session"]["session_id"]
    db = test_db()
    try:
        evidence_before = db.query(ComputerEvidence).count()
    finally:
        db.close()

    response = client.post(f"/api/v2/computer/sessions/{session_id}/capture", headers=owner_headers)

    assert response.status_code == 400
    db = test_db()
    try:
        assert db.query(ComputerEvidence).count() == evidence_before
    finally:
        db.close()
