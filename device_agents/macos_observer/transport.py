from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class ObservationTransportResult:
    ok: bool
    message: str


class ObservationTransport(Protocol):
    def send_heartbeat(self, payload: dict[str, object]) -> ObservationTransportResult:
        ...

    def send_observation(self, payload: dict[str, object]) -> ObservationTransportResult:
        ...


class LocalObservationTransport:
    def send_heartbeat(self, payload: dict[str, object]) -> ObservationTransportResult:
        return ObservationTransportResult(ok=True, message="本地模拟心跳已发送")

    def send_observation(self, payload: dict[str, object]) -> ObservationTransportResult:
        return ObservationTransportResult(ok=True, message="本地模拟观察已发送")

