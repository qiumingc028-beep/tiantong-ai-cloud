from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HeartbeatPulse:
    device_code: str
    nonce: str
    timestamp: str
    signature: str

