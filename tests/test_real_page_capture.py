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
from starlette.requests import Request

import backend.agent_runtime.executors.computer.openclaw_adapter as adapter_module
import backend.agent_runtime.executors.computer.runtime as runtime_module
import backend.auth as auth_module
from backend.auth import (
    CAPTURE_AUTH_WORKFLOW_HEADER,
    create_capture_authorization,
    decode_capture_access_token,
)
from backend.agent_runtime.executors.computer.models import ComputerEvidence
from backend.agent_runtime.executors.computer.base import ComputerExecutorOutcome
from backend.agent_runtime.executors.computer.actions.models import ComputerActionPlan
from backend.agent_runtime.executors.computer.models import ComputerAction, ComputerPolicyEvent
from backend.agent_runtime.executors.computer.openclaw_adapter import (
    WEBSOCKET_GUID,
    OpenClawAdapter,
    _WebSocket,
    validate_capture_target_url,
)
from backend.agent_runtime.workflows.computer.models import ComputerWorkflow
from backend.config import ConfigurationError, Settings
from tests.test_computer_workflows import _create_owned_task, _enable_workflow_flags


def _request(method: str, path: str, *, token: str, workflow_id: str, origin: str = "http://127.0.0.1:59200"):
    parsed = urlsplit(origin)
    headers = [
        (b"authorization", f"Bearer {token}".encode()),
        (CAPTURE_AUTH_WORKFLOW_HEADER.lower().encode(), workflow_id.encode()),
    ]
    return Request(
        {
            "type": "http",
            "method": method,
            "scheme": parsed.scheme,
            "server": (parsed.hostname, parsed.port),
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
        }
    )


def test_capture_authorization_is_short_lived_workflow_bound_and_read_only(monkeypatch):
    settings = SimpleNamespace(
        APP_ENV="test",
        IS_PRODUCTION=False,
        JWT_SECRET="r191-capture-secret-that-is-long-enough-for-tests",
        JWT_ALGORITHM="HS256",
        PAGE_CAPTURE_ALLOWED_ORIGINS=["http://127.0.0.1:59200"],
    )
    monkeypatch.setattr(auth_module, "get_settings", lambda: settings)
    authorization = create_capture_authorization(
        user_id=41,
        workflow_id="workflow-owner-r191",
        target_url="http://127.0.0.1:59200/computer-workflow-center.html",
    )

    assert "r191-capture-secret" not in repr(authorization)
    assert decode_capture_access_token(
        authorization.token,
        _request(
            "GET",
            "/api/v2/computer/workflows",
            token=authorization.token,
            workflow_id=authorization.workflow_id,
        ),
    ) == 41
    assert decode_capture_access_token(
        authorization.token,
        _request(
            "POST",
            "/api/v2/computer/workflows",
            token=authorization.token,
            workflow_id=authorization.workflow_id,
        ),
    ) is None
    assert decode_capture_access_token(
        authorization.token,
        _request(
            "GET",
            "/api/v2/computer/workflows",
            token=authorization.token,
            workflow_id="workflow-foreign-r191",
        ),
    ) is None
    assert decode_capture_access_token(
        authorization.token,
        _request(
            "GET",
            "/api/v2/computer/workflows/foreign",
            token=authorization.token,
            workflow_id=authorization.workflow_id,
        ),
    ) is None


def _local_capture_authorization(target_url: str, *, workflow_id: str = "workflow-owner-r191"):
    parsed = urlsplit(target_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return auth_module.CaptureAuthorization(
        token="r191-local-capture-token",
        workflow_id=workflow_id,
        origin=origin,
        target_path=parsed.path,
        allowed_paths=frozenset({parsed.path, "/style.css"}),
    )


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


@contextmanager
def protected_workflow_page(
    requests: list[tuple[str, str, bool, str]],
    *,
    deny: bool = False,
    attempt_write: bool = False,
    redirect_to_api: bool = False,
    workflow_id_ref: list[str] | None = None,
):
    token = "r191-readonly-test-token"
    workflow_id = "workflow-owner-r191"

    def expected_workflow_id():
        return workflow_id_ref[0] if workflow_id_ref else workflow_id

    class Handler(BaseHTTPRequestHandler):
        def _record(self):
            requests.append(
                (
                    self.command,
                    self.path,
                    self.headers.get("Authorization") == f"Bearer {token}",
                    self.headers.get(CAPTURE_AUTH_WORKFLOW_HEADER, ""),
                )
            )

        def _send(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._record()
            if self.path == "/computer-workflow-center.html":
                if redirect_to_api:
                    self.send_response(302)
                    self.send_header("Location", "/api/v2/computer/workflows")
                    self.end_headers()
                    return
                write_attempt = "await fetch('/api/v2/computer/workflows',{method:'POST'});" if attempt_write else ""
                body = f"""<!doctype html><html style='visibility:hidden'><body>
                    <span id='currentUser'>正在确认身份</span><div id='pageState'>正在加载工作流...</div>
                    <table><tbody id='workflowRows'></tbody></table>
                    <script>(async()=>{{try{{
                      const me=await fetch('/api/me').then(r=>{{if(!r.ok)throw Error('无权访问');return r.json()}});
                      const data=await fetch('/api/v2/computer/workflows').then(r=>{{if(!r.ok)throw Error('无权访问');return r.json()}});
                      {write_attempt}
                      currentUser.textContent=me.display_name;
                      workflowRows.innerHTML=data.items.map(w=>`<tr><td>${{w.workflow_id}}</td></tr>`).join('');
                      pageState.textContent=`已加载 ${{data.items.length}} 个工作流。`;
                      document.documentElement.style.visibility='visible';
                    }}catch(error){{document.body.textContent='无权访问';document.documentElement.style.visibility='visible'}}}})();</script>
                </body></html>""".encode()
                self._send(200, body, "text/html; charset=utf-8")
                return
            authorized = (
                not deny
                and self.headers.get("Authorization") == f"Bearer {token}"
                and self.headers.get(CAPTURE_AUTH_WORKFLOW_HEADER) == expected_workflow_id()
            )
            if not authorized:
                self._send(401, b'{"detail":"unauthorized"}', "application/json")
            elif self.path == "/api/me":
                self._send(200, b'{"display_name":"R191 Owner"}', "application/json")
            elif self.path == "/api/v2/computer/workflows":
                self._send(200, json.dumps({"items": [{"workflow_id": expected_workflow_id()}]}).encode(), "application/json")
            else:
                self._send(404, b"{}", "application/json")

        def do_POST(self):
            self._record()
            self._send(405, b"{}", "application/json")

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_port}"
        authorization = auth_module.CaptureAuthorization(
            token=token,
            workflow_id=workflow_id,
            origin=origin,
            target_path="/computer-workflow-center.html",
            allowed_paths=frozenset(
                {
                    "/computer-workflow-center.html",
                    "/api/me",
                    "/api/v2/computer/workflows",
                }
            ),
        )
        yield f"{origin}/computer-workflow-center.html", authorization
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
    requests = []
    with protected_workflow_page(requests) as (target_url, authorization):
        origin = authorization.origin
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
            capture_authorization=authorization,
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
    screenshot.unlink()


def test_real_adapter_uses_workflow_bound_readonly_auth_and_verifies_owner_page(tmp_path, chrome_path):
    requests = []
    with protected_workflow_page(requests) as (target_url, authorization):
        settings = SimpleNamespace(
            PAGE_CAPTURE_ALLOWED_ORIGINS=[authorization.origin],
            PAGE_CAPTURE_CHROME_PATH=chrome_path,
            PAGE_CAPTURE_OUTPUT_ROOT=str(tmp_path / "captures"),
            PAGE_CAPTURE_TIMEOUT_SECONDS=15,
            OPENCLAW_ADAPTER_ENABLED=True,
        )
        outcome = OpenClawAdapter(settings=settings).execute_action(
            SimpleNamespace(
                session_id="r191-session",
                trace_id="r191-trace",
                action_type="截图",
                target_url=target_url,
                capture_authorization=authorization,
            )
        )

    screenshot = Path(urlsplit(outcome.screenshot_reference).path)
    assert screenshot.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert outcome.action_result["provider"] == "chrome_cdp_page_capture"
    assert authorization.token == ""
    assert all(method in {"GET", "HEAD"} for method, *_ in requests)
    assert all(has_auth and workflow == "workflow-owner-r191" for _, path, has_auth, workflow in requests if path.startswith("/api/"))
    screenshot.unlink()
    assert not list(tmp_path.rglob("profile-*"))


@pytest.mark.parametrize("deny,attempt_write", [(True, False), (False, True)])
def test_real_adapter_rejects_unauthorized_page_and_write_attempt_without_artifacts(
    tmp_path, chrome_path, deny, attempt_write
):
    requests = []
    with protected_workflow_page(requests, deny=deny, attempt_write=attempt_write) as (target_url, authorization):
        settings = SimpleNamespace(
            PAGE_CAPTURE_ALLOWED_ORIGINS=[authorization.origin],
            PAGE_CAPTURE_CHROME_PATH=chrome_path,
            PAGE_CAPTURE_OUTPUT_ROOT=str(tmp_path / "captures"),
            PAGE_CAPTURE_TIMEOUT_SECONDS=15,
            OPENCLAW_ADAPTER_ENABLED=True,
        )
        with pytest.raises((PermissionError, ValueError)):
            OpenClawAdapter(settings=settings).execute_action(
                SimpleNamespace(
                    session_id="r191-session",
                    trace_id="r191-trace",
                    action_type="截图",
                    target_url=target_url,
                    capture_authorization=authorization,
                )
            )

    assert not list(tmp_path.rglob("*.png"))
    assert not list(tmp_path.rglob("profile-*"))
    assert not any(method == "POST" for method, *_ in requests)


def test_real_adapter_rejects_same_origin_redirect_to_allowed_api_without_artifacts(
    tmp_path, chrome_path
):
    requests = []
    with protected_workflow_page(requests, redirect_to_api=True) as (target_url, authorization):
        settings = SimpleNamespace(
            PAGE_CAPTURE_ALLOWED_ORIGINS=[authorization.origin],
            PAGE_CAPTURE_CHROME_PATH=chrome_path,
            PAGE_CAPTURE_OUTPUT_ROOT=str(tmp_path / "captures"),
            PAGE_CAPTURE_TIMEOUT_SECONDS=15,
            OPENCLAW_ADAPTER_ENABLED=True,
        )
        with pytest.raises(ValueError, match="authorized capture target"):
            OpenClawAdapter(settings=settings).execute_action(
                SimpleNamespace(
                    session_id="r191-session",
                    trace_id="r191-trace",
                    action_type="截图",
                    target_url=target_url,
                    capture_authorization=authorization,
                )
            )

    assert not list(tmp_path.rglob("*.png"))
    assert not list(tmp_path.rglob("profile-*"))


def test_capture_token_projects_only_its_workflow_and_parent_task(
    client, admin_headers, monkeypatch
):
    settings = _enable_workflow_flags(monkeypatch)
    settings.APP_ENV = "test"
    settings.IS_PRODUCTION = False
    settings.JWT_SECRET = "r191-capture-projection-secret-that-is-long-enough"
    settings.JWT_ALGORITHM = "HS256"
    settings.PAGE_CAPTURE_ALLOWED_ORIGINS = ["http://127.0.0.1:59200"]
    monkeypatch.setattr(auth_module, "get_settings", lambda: settings)
    task_ids = [
        _create_owned_task(client, admin_headers, f"R191 capture projection {index}")
        for index in (1, 2)
    ]
    workflow_ids = []
    for task_id in task_ids:
        created = client.post(
            "/api/v2/computer/workflows",
            headers=admin_headers,
            json={
                "task_id": task_id,
                "goal": f"Capture projection for task {task_id}",
                "max_steps": 2,
                "steps": [
                    {
                        "action_type": "截图",
                        "target_url": "http://127.0.0.1:59200/computer-workflow-center.html",
                        "expected_result": "owner workflow only",
                    },
                    {"action_type": "等待", "expected_result": "finish"},
                ],
            },
        )
        assert created.status_code == 200
        workflow_ids.append(created.json()["workflow"]["workflow_id"])
    admin_user_id = client.get("/api/me", headers=admin_headers).json()["id"]
    authorization = create_capture_authorization(
        user_id=admin_user_id,
        workflow_id=workflow_ids[0],
        target_url="http://127.0.0.1:59200/computer-workflow-center.html",
    )
    headers = {
        "Authorization": f"Bearer {authorization.token}",
        CAPTURE_AUTH_WORKFLOW_HEADER: authorization.workflow_id,
        "Host": "127.0.0.1:59200",
    }
    client.cookies.clear()

    me = client.get("/api/me", headers=headers)
    workflows = client.get("/api/v2/computer/workflows", headers=headers)
    tasks = client.get("/api/task-center/tasks", headers=headers)

    assert me.status_code == workflows.status_code == tasks.status_code == 200
    assert [item["permission"] for item in me.json()["menus"]] == ["menu.computer_executor"]
    assert [item["workflow_id"] for item in workflows.json()["items"]] == [workflow_ids[0]]
    assert [item["id"] for item in tasks.json()] == [task_ids[0]]
    assert workflow_ids[1] not in workflows.text
    assert str(task_ids[1]) not in {str(item["id"]) for item in tasks.json()}


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
            capture_authorization=_local_capture_authorization(target_url),
        )

        with pytest.raises(ValueError, match="allowed capture boundary"):
            OpenClawAdapter(settings=settings).execute_action(context)

    assert not list(tmp_path.rglob("*.png"))
    assert not list(tmp_path.rglob("profile-*"))
    assert destination_requests == []


def test_workflow_executes_real_page_capture_provider(client, admin_headers, monkeypatch, tmp_path, chrome_path):
    workflow_id_ref = []
    requests = []
    with protected_workflow_page(requests, workflow_id_ref=workflow_id_ref) as (target_url, authorization):
        origin = f"{urlsplit(target_url).scheme}://{urlsplit(target_url).netloc}"
        settings = _enable_workflow_flags(monkeypatch)
        settings.OPENCLAW_ADAPTER_ENABLED = True
        settings.PAGE_CAPTURE_ALLOWED_ORIGINS = [origin]
        settings.PAGE_CAPTURE_CHROME_PATH = chrome_path
        settings.PAGE_CAPTURE_OUTPUT_ROOT = str(tmp_path / "captures")
        settings.PAGE_CAPTURE_TIMEOUT_SECONDS = 15
        monkeypatch.setattr("backend.agent_runtime.executors.computer.runtime.get_settings", lambda: settings)
        monkeypatch.setattr(
            "backend.agent_runtime.workflows.computer.runner.create_capture_authorization",
            lambda **kwargs: auth_module.CaptureAuthorization(
                token=authorization.token,
                workflow_id=kwargs["workflow_id"],
                origin=authorization.origin,
                target_path=authorization.target_path,
                allowed_paths=authorization.allowed_paths,
            ),
        )
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
        workflow_id_ref.append(workflow_id)
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


def test_workflow_capture_persistence_failure_rolls_back_rows_and_screenshot(
    client, admin_headers, monkeypatch, tmp_path, chrome_path, test_db
):
    settings = _enable_workflow_flags(monkeypatch)
    settings.OPENCLAW_ADAPTER_ENABLED = True
    settings.PAGE_CAPTURE_ALLOWED_ORIGINS = ["http://127.0.0.1:59200"]
    settings.PAGE_CAPTURE_CHROME_PATH = chrome_path
    settings.PAGE_CAPTURE_OUTPUT_ROOT = str(tmp_path / "captures")
    settings.PAGE_CAPTURE_TIMEOUT_SECONDS = 15
    monkeypatch.setattr("backend.agent_runtime.executors.computer.runtime.get_settings", lambda: settings)
    authorizations = []

    def issue_authorization(**kwargs):
        authorization = _local_capture_authorization(
            kwargs["target_url"],
            workflow_id=kwargs["workflow_id"],
        )
        authorizations.append(authorization)
        return authorization

    screenshot = tmp_path / "captures" / "failed-r191.png"
    screenshot.parent.mkdir(mode=0o700)

    class SuccessfulCaptureExecutor:
        def execute_action(self, _context):
            screenshot.write_bytes(b"\x89PNG\r\n\x1a\nR191")
            return ComputerExecutorOutcome(
                success=True,
                action_result={"provider": "chrome_cdp_page_capture"},
                screenshot_reference=screenshot.as_uri(),
            )

    monkeypatch.setattr(
        "backend.agent_runtime.workflows.computer.runner.create_capture_authorization",
        issue_authorization,
    )
    monkeypatch.setattr(runtime_module, "_executor_for_settings", lambda _session: SuccessfulCaptureExecutor())
    monkeypatch.setattr(
        runtime_module,
        "add_evidence_row",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("R191 evidence persistence failure")),
    )
    task_id = _create_owned_task(client, admin_headers, "R191 rollback denied capture")
    created = client.post(
        "/api/v2/computer/workflows",
        headers=admin_headers,
        json={
            "task_id": task_id,
            "goal": "Denied capture must leave no execution rows",
            "max_steps": 2,
            "steps": [
                {
                    "action_type": "截图",
                    "target_url": "http://127.0.0.1:59200/computer-workflow-center.html",
                    "expected_result": "必须安全拒绝",
                },
                {"action_type": "等待", "expected_result": "不应到达"},
            ],
        },
    )
    assert created.status_code == 200
    workflow_id = created.json()["workflow"]["workflow_id"]
    assert client.post(f"/api/v2/computer/workflows/{workflow_id}/approve", headers=admin_headers).status_code == 200
    db = test_db()
    try:
        workflow = db.get(ComputerWorkflow, workflow_id)
        session_id = workflow.session_id
        before = (
            workflow.status,
            workflow.current_step,
            db.query(ComputerActionPlan).filter(ComputerActionPlan.session_id == session_id).count(),
            db.query(ComputerAction).filter(ComputerAction.session_id == session_id).count(),
            db.query(ComputerPolicyEvent).filter(ComputerPolicyEvent.session_id == session_id).count(),
            db.query(ComputerEvidence).filter(ComputerEvidence.session_id == session_id).count(),
        )
    finally:
        db.close()

    with pytest.raises(RuntimeError, match="R191 evidence persistence failure"):
        client.post(f"/api/v2/computer/workflows/{workflow_id}/start", headers=admin_headers)

    db = test_db()
    try:
        workflow = db.get(ComputerWorkflow, workflow_id)
        after = (
            workflow.status,
            workflow.current_step,
            db.query(ComputerActionPlan).filter(ComputerActionPlan.session_id == session_id).count(),
            db.query(ComputerAction).filter(ComputerAction.session_id == session_id).count(),
            db.query(ComputerPolicyEvent).filter(ComputerPolicyEvent.session_id == session_id).count(),
            db.query(ComputerEvidence).filter(ComputerEvidence.session_id == session_id).count(),
        )
        assert after == before
    finally:
        db.close()
    assert len(authorizations) == 1
    assert authorizations[0].token == ""
    assert not screenshot.exists()


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
