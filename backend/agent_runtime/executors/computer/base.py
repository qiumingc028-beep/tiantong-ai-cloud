from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ComputerExecutorOutcome:
    success: bool
    action_result: dict
    screenshot_reference: str | None = None
    window_title: str | None = None
    active_application: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    audit_metadata: dict | None = None


class ComputerExecutorBase(ABC):
    @abstractmethod
    def validate(self, context): ...

    @abstractmethod
    def create_session(self, context): ...

    @abstractmethod
    def execute_action(self, context): ...

    @abstractmethod
    def capture_screen(self, context): ...

    @abstractmethod
    def get_window_state(self, context): ...

    @abstractmethod
    def cancel(self, context): ...

    @abstractmethod
    def pause(self, context): ...

    @abstractmethod
    def resume(self, context): ...

    @abstractmethod
    def handoff_to_human(self, context): ...

    @abstractmethod
    def close_session(self, context): ...

    @abstractmethod
    def health_check(self): ...

    @abstractmethod
    def get_metadata(self): ...
