from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class DeviceRegistrationEnvelope:
    device_code: str
    device_name: str
    registration_token: str
    nonce: str
    timestamp: str
    signature: str

