from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


@dataclass(slots=True)
class ExecutorContext:
    execution_id: str
    trace_id: str
    capability_id: str
    capability_name: str
    capability_type: str
    executor_type: str
    employee_id: int | None
    employee_code: str | None
    employee_name: str | None
    task_id: int | None
    retry_count: int
    timeout_seconds: int
    input_payload: dict[str, Any]


@dataclass(slots=True)
class ExecutorResult:
    success: bool
    output: dict[str, Any]
    error_code: str | None
    error_message: str | None
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    metadata: dict[str, Any]
    retryable: bool = False


class ExecutorProtocol(Protocol):
    def validate(self, context: ExecutorContext) -> None: ...

    def execute(self, context: ExecutorContext) -> ExecutorResult: ...

    def cancel(self, context: ExecutorContext) -> dict[str, Any]: ...

    def health_check(self) -> dict[str, Any]: ...

    def get_metadata(self) -> dict[str, Any]: ...
