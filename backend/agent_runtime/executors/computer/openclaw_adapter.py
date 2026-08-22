from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from ....config import get_settings
from .base import ComputerExecutorBase, ComputerExecutorOutcome
from .evidence import utcnow


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
REAL_PROVIDER = "chrome_cdp_page_capture"
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def validate_capture_target_url(target_url: str | None, allowed_origins: list[str]) -> str:
    value = (target_url or "").strip()
    if not value:
        raise ValueError("target_url is required")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("target_url is not an allowed HTTP URL")
    origin = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port is not None:
        origin = f"{origin}:{parsed.port}"
    normalized_allowed = {item.strip().rstrip("/") for item in allowed_origins if item.strip()}
    if origin not in normalized_allowed:
        raise ValueError("target_url origin is not allowlisted")
    return value


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = sock.recv(length - len(chunks))
        if not chunk:
            raise RuntimeError("Chrome DevTools connection closed")
        chunks.extend(chunk)
    return bytes(chunks)


class _WebSocket:
    def __init__(self, url: str, timeout: float):
        parsed = urlsplit(url)
        if parsed.scheme != "ws" or parsed.hostname != "127.0.0.1" or not parsed.port:
            raise RuntimeError("Chrome DevTools endpoint is not loopback")
        self.sock = socket.create_connection((parsed.hostname, parsed.port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            f"GET {parsed.path or '/'}{('?' + parsed.query) if parsed.query else ''} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port}\r\n"
            "Origin: http://localhost\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = bytearray()
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("Chrome DevTools WebSocket handshake closed")
            response.extend(chunk)
        headers, remainder = bytes(response).split(b"\r\n\r\n", 1)
        header_lines = headers.decode("ascii").split("\r\n")
        response_headers = {
            name.strip().lower(): value.strip()
            for name, value in (line.split(":", 1) for line in header_lines[1:] if ":" in line)
        }
        expected_accept = base64.b64encode(
            hashlib.sha1(f"{key}{WEBSOCKET_GUID}".encode("ascii")).digest()
        ).decode("ascii")
        if (
            len(header_lines[0].split()) < 2
            or header_lines[0].split()[1] != "101"
            or response_headers.get("upgrade", "").lower() != "websocket"
            or "upgrade" not in response_headers.get("connection", "").lower()
            or not secrets.compare_digest(response_headers.get("sec-websocket-accept", ""), expected_accept)
        ):
            raise RuntimeError("Chrome DevTools WebSocket handshake failed")
        self._buffer = bytearray(remainder)
        self.next_id = 1
        self.events: list[dict] = []
        self.allowed_origins: list[str] = []

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _send_frame(self, opcode: int, data: bytes) -> None:
        first = bytearray([0x80 | opcode])
        length = len(data)
        if length < 126:
            first.append(0x80 | length)
        elif length < 65536:
            first.append(0x80 | 126)
            first.extend(length.to_bytes(2, "big"))
        else:
            first.append(0x80 | 127)
            first.extend(length.to_bytes(8, "big"))
        mask = secrets.token_bytes(4)
        first.extend(mask)
        first.extend(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(first)

    def _send_json(self, payload: dict) -> None:
        self._send_frame(0x1, json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    def _recv_bytes(self, length: int) -> bytes:
        if len(self._buffer) < length:
            self._buffer.extend(_recv_exact(self.sock, length - len(self._buffer)))
        data = bytes(self._buffer[:length])
        del self._buffer[:length]
        return data

    def _recv_frame(self) -> tuple[bool, int, bytes]:
        first, second = self._recv_bytes(2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = int.from_bytes(self._recv_bytes(2), "big")
        elif length == 127:
            length = int.from_bytes(self._recv_bytes(8), "big")
        mask = self._recv_bytes(4) if second & 0x80 else None
        data = bytearray(self._recv_bytes(length))
        if mask:
            for index in range(len(data)):
                data[index] ^= mask[index % 4]
        return bool(first & 0x80), opcode, bytes(data)

    def _recv_json(self) -> dict:
        fragments = bytearray()
        fragmented_opcode = None
        while True:
            final, opcode, data = self._recv_frame()
            if opcode == 0x8:
                raise RuntimeError("Chrome DevTools WebSocket closed")
            if opcode == 0x9:
                self._send_frame(0xA, data)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                if fragmented_opcode is not None:
                    raise RuntimeError("unexpected Chrome DevTools text frame")
                if final:
                    return json.loads(data.decode("utf-8"))
                fragmented_opcode = opcode
                fragments.extend(data)
                continue
            if opcode == 0x0 and fragmented_opcode == 0x1:
                fragments.extend(data)
                if final:
                    return json.loads(bytes(fragments).decode("utf-8"))
                continue
            raise RuntimeError("unexpected Chrome DevTools frame")

    def _continue_allowlisted_request(self, message: dict) -> bool:
        if message.get("method") != "Fetch.requestPaused":
            return False
        paused = message.get("params") or {}
        paused_url = str((paused.get("request") or {}).get("url") or "")
        try:
            validate_capture_target_url(paused_url, self.allowed_origins)
            method = "Fetch.continueRequest"
            params = {"requestId": paused["requestId"]}
        except ValueError:
            method = "Fetch.failRequest"
            params = {"requestId": paused["requestId"], "errorReason": "BlockedByClient"}
        self._send_json({"id": self.next_id, "method": method, "params": params})
        self.next_id += 1
        if method == "Fetch.failRequest":
            raise ValueError("page navigation left the allowlisted origin")
        return True

    def call(self, method: str, params: dict | None = None) -> dict:
        request_id = self.next_id
        self.next_id += 1
        self._send_json({"id": request_id, "method": method, "params": params or {}})
        while True:
            message = self._recv_json()
            if self._continue_allowlisted_request(message):
                continue
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(f"Chrome DevTools command failed: {method}")
                return message.get("result") or {}
            self.events.append(message)

    def navigate(self, target_url: str, allowed_origins: list[str]) -> dict:
        self.allowed_origins = allowed_origins
        request_id = self.next_id
        self.next_id += 1
        self._send_json({"id": request_id, "method": "Page.navigate", "params": {"url": target_url}})
        while True:
            message = self._recv_json()
            if self._continue_allowlisted_request(message):
                continue
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError("Chrome DevTools command failed: Page.navigate")
                return message.get("result") or {}
            self.events.append(message)

    def wait_for(self, method: str, deadline: float) -> dict:
        while True:
            for index, event in enumerate(self.events):
                if event.get("method") == method:
                    return self.events.pop(index)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Chrome DevTools event timed out: {method}")
            event = self._recv_json()
            if self._continue_allowlisted_request(event):
                continue
            if event.get("method") == method:
                return event
            self.events.append(event)


class OpenClawAdapter(ComputerExecutorBase):
    def __init__(self, *, settings=None):
        self.settings = settings or get_settings()

    def _target_url(self, context) -> str:
        return validate_capture_target_url(
            getattr(context, "target_url", None),
            list(getattr(self.settings, "PAGE_CAPTURE_ALLOWED_ORIGINS", [])),
        )

    def _ensure_enabled(self) -> None:
        if not bool(getattr(self.settings, "OPENCLAW_ADAPTER_ENABLED", False)):
            raise RuntimeError("real page capture adapter is disabled")

    def validate(self, context):
        target_url = self._target_url(context)
        chrome = Path(str(getattr(self.settings, "PAGE_CAPTURE_CHROME_PATH", "")))
        output_root = Path(str(getattr(self.settings, "PAGE_CAPTURE_OUTPUT_ROOT", "")))
        if not chrome.is_absolute() or not chrome.is_file() or not os.access(chrome, os.X_OK):
            raise RuntimeError("configured Chrome executable is unavailable")
        resolved_root = output_root.resolve(strict=False)
        temp_roots = {
            Path(tempfile.gettempdir()).resolve(),
            Path("/tmp").resolve(),
            Path("/private/tmp").resolve(),
        }
        if not output_root.is_absolute() or not any(
            resolved_root != root and resolved_root.is_relative_to(root) for root in temp_roots
        ):
            raise RuntimeError("page capture output root must be a dedicated temporary directory")
        return target_url

    def create_session(self, context):
        self._ensure_enabled()
        return {"session_id": context.session_id, "provider": REAL_PROVIDER, "created_at": utcnow().isoformat()}

    def execute_action(self, context):
        self._ensure_enabled()
        started = utcnow()
        if context.action_type == "等待":
            return ComputerExecutorOutcome(
                success=True,
                action_result={"message": "安全等待步骤完成", "provider": "builtin_wait"},
                started_at=started,
                finished_at=utcnow(),
                duration_ms=0,
                audit_metadata={"provider": "builtin_wait"},
            )
        if context.action_type != "截图":
            raise RuntimeError("real page capture adapter only permits screenshot and wait actions")
        capture = self._capture(context)
        return ComputerExecutorOutcome(
            success=True,
            action_result={
                "message": "独立浏览器页面截图完成",
                "provider": REAL_PROVIDER,
                "sha256": capture["sha256"],
                "size_bytes": capture["size_bytes"],
                "final_url": capture["final_url"],
            },
            screenshot_reference=capture["screenshot_reference"],
            window_title=capture["final_url"],
            active_application="isolated_headless_chrome",
            started_at=started,
            finished_at=utcnow(),
            duration_ms=max(0, int((utcnow() - started).total_seconds() * 1000)),
            audit_metadata={"provider": REAL_PROVIDER, "desktop_capture_calls": 0},
        )

    def _capture(self, context) -> dict:
        target_url = self.validate(context)
        timeout = float(getattr(self.settings, "PAGE_CAPTURE_TIMEOUT_SECONDS", 20))
        output_root = Path(self.settings.PAGE_CAPTURE_OUTPUT_ROOT)
        output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        output_root.chmod(0o700)
        profile = Path(tempfile.mkdtemp(prefix="profile-", dir=output_root))
        profile.chmod(0o700)
        screenshot = output_root / f"{secrets.token_hex(16)}.png"
        process = None
        websocket = None
        try:
            command = [
                str(self.settings.PAGE_CAPTURE_CHROME_PATH),
                "--headless=new",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-sync",
                "--disable-background-networking",
                "--disable-component-update",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=0",
                "--remote-allow-origins=http://localhost",
                f"--user-data-dir={profile}",
                "--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1",
                "about:blank",
            ]
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            deadline = time.monotonic() + timeout
            port_file = profile / "DevToolsActivePort"
            while not port_file.exists():
                if process.poll() is not None:
                    raise RuntimeError("isolated Chrome exited during startup")
                if time.monotonic() >= deadline:
                    raise TimeoutError("isolated Chrome startup timed out")
                time.sleep(0.05)
            port = int(port_file.read_text(encoding="utf-8").splitlines()[0])
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
            connection.request("GET", "/json/list")
            response = connection.getresponse()
            targets = json.loads(response.read().decode("utf-8"))
            connection.close()
            page = next((target for target in targets if target.get("type") == "page"), None)
            if not page or not page.get("webSocketDebuggerUrl"):
                raise RuntimeError("isolated Chrome page target unavailable")
            websocket = _WebSocket(page["webSocketDebuggerUrl"], timeout)
            websocket.call("Page.enable")
            websocket.call("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
            navigation = websocket.navigate(target_url, list(self.settings.PAGE_CAPTURE_ALLOWED_ORIGINS))
            if navigation.get("errorText"):
                raise RuntimeError("isolated page navigation failed")
            websocket.wait_for("Page.loadEventFired", deadline)
            evaluated = websocket.call("Runtime.evaluate", {"expression": "location.href", "returnByValue": True})
            final_url = str(((evaluated.get("result") or {}).get("value") or "")).strip()
            validate_capture_target_url(final_url, list(self.settings.PAGE_CAPTURE_ALLOWED_ORIGINS))
            captured = websocket.call(
                "Page.captureScreenshot",
                {"format": "png", "fromSurface": True, "captureBeyondViewport": False},
            )
            content = base64.b64decode(captured.get("data") or "", validate=True)
            if len(content) <= len(PNG_SIGNATURE) or not content.startswith(PNG_SIGNATURE):
                raise RuntimeError("Chrome did not return a valid PNG")
            fd = os.open(screenshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(content)
            return {
                "screenshot_reference": screenshot.as_uri(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "final_url": final_url,
            }
        except Exception:
            screenshot.unlink(missing_ok=True)
            raise
        finally:
            if websocket is not None:
                websocket.close()
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            if profile.exists():
                shutil.rmtree(profile)

    def capture_screen(self, context):
        return self._capture(context)

    def get_window_state(self, context):
        return {"windows": [], "active_application": "isolated_headless_chrome", "provider": REAL_PROVIDER}

    def cancel(self, context):
        return {"success": True, "status": "已取消"}

    def pause(self, context):
        return {"success": True, "status": "已暂停"}

    def resume(self, context):
        return {"success": True, "status": "执行中"}

    def handoff_to_human(self, context):
        return {"success": False, "status": "不支持桌面接管"}

    def close_session(self, context):
        return {"success": True, "status": "已关闭"}

    def health_check(self):
        chrome = Path(str(getattr(self.settings, "PAGE_CAPTURE_CHROME_PATH", "")))
        return {"healthy": chrome.is_file() and os.access(chrome, os.X_OK), "provider": REAL_PROVIDER}

    def get_metadata(self):
        return {"name": "OpenClawAdapter", "provider": REAL_PROVIDER}
