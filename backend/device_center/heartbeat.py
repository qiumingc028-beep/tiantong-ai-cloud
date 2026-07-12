from __future__ import annotations

from datetime import datetime, timezone

from .models import Device


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def mark_online(device: Device, *, ip_hash: str | None = None, agent_version: str | None = None, capabilities_json: str | None = None) -> Device:
    device.status = "在线"
    device.last_seen_at = utcnow()
    if ip_hash is not None:
        device.last_ip_hash = ip_hash
    if agent_version:
        device.agent_version = agent_version
    if capabilities_json is not None:
        device.capabilities_json = capabilities_json
    return device

