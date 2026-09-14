"""Bounded client for a fixed local Receiver or Observer service."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pwd
import socket
import stat

from ops.r297_broker_client import peer_uid


def role_request(socket_path: Path, request: dict, *, expected_user: str) -> dict:
    metadata = socket_path.lstat()
    expected_uid = pwd.getpwnam(expected_user).pw_uid
    if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != expected_uid or stat.S_IMODE(metadata.st_mode) & 0o007:
        raise RuntimeError("ROLE_SOCKET_UNTRUSTED")
    content = (json.dumps(request, sort_keys=True) + "\n").encode()
    if len(content) > 64 * 1024:
        raise ValueError("ROLE_REQUEST_TOO_LARGE")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(30)
        connection.connect(str(socket_path))
        if peer_uid(connection) != expected_uid:
            raise RuntimeError("ROLE_PEER_UNTRUSTED")
        connection.sendall(content)
        with connection.makefile("rb") as stream:
            response = stream.readline(256 * 1024 + 1)
    if not response.endswith(b"\n") or len(response) > 256 * 1024:
        raise RuntimeError("ROLE_RESPONSE_INVALID")
    result = json.loads(response)
    if result.get("ok") is not True:
        code = result.get("error")
        raise RuntimeError(code if code in {"ROLE_NO_RECOVERABLE_FACT", "ROLE_RECOVERY_BLOCKED"} else "ROLE_REQUEST_REJECTED")
    return result["value"]
