"""Bounded transport to the fixed local, root-owned R297 Broker."""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat
import struct


def peer_uid(connection: socket.socket) -> int:
    if hasattr(socket, "SO_PEERCRED"):
        return struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]
    if hasattr(connection, "getpeereid"):
        return connection.getpeereid()[0]
    if __import__("sys").platform == "darwin":
        return struct.unpack_from("I", connection.getsockopt(0, 1, 80), 4)[0]
    raise RuntimeError("BROKER_PEER_IDENTITY_UNAVAILABLE")


def broker_request(request: dict) -> dict:
    value = os.getenv("R297_ACCEPTANCE_BROKER_SOCKET", "")
    if not value:
        raise RuntimeError("R297_ACCEPTANCE_BROKER_SOCKET_MISSING")
    path = Path(value)
    parent, metadata = path.parent.lstat(), path.lstat()
    owner = os.geteuid() if os.getenv("APP_ENV") == "test" else 0
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != owner or stat.S_IMODE(parent.st_mode) & 0o022
        or not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != owner
        or stat.S_IMODE(metadata.st_mode) & 0o007):
        raise RuntimeError("BROKER_SOCKET_UNTRUSTED")
    content = (json.dumps(request, sort_keys=True) + "\n").encode()
    if len(content) > 4 * 1024 * 1024:
        raise ValueError("BROKER_REQUEST_TOO_LARGE")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(15)
        connection.connect(str(path))
        if peer_uid(connection) != owner:
            raise RuntimeError("BROKER_PEER_UNTRUSTED")
        connection.sendall(content)
        with connection.makefile("rb") as stream:
            response = stream.readline(4 * 1024 * 1024 + 1)
    if len(response) > 4 * 1024 * 1024 or not response.endswith(b"\n"):
        raise RuntimeError("BROKER_RESPONSE_INVALID")
    payload = json.loads(response)
    if payload.get("ok") is not True:
        raise RuntimeError("R297_BROKER_" + str(payload.get("error", "REJECTED")))
    return payload["value"]
