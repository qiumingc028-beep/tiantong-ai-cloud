from __future__ import annotations

from typing import Any, Protocol

from .audit import payload_summary
from .executor_types import ExecutorContext, ExecutorProtocol, ExecutorResult
from .executors.browser.executor import ReadonlyHttpBrowserExecutor
from ..research_runtime.executor import ResearchExecutor


class MockExecutor:
    executor_type = "mock"
    name = "MockExecutor"

    def validate(self, context: ExecutorContext) -> None:
        if context.executor_type != "mock":
            raise ValueError("MockExecutor only supports mock capabilities")

    def execute(self, context: ExecutorContext) -> ExecutorResult:
        self.validate(context)
        from datetime import datetime, timezone

        started_at = datetime.now(timezone.utc)
        mode = str(context.input_payload.get("simulate_mode") or context.input_payload.get("mode") or "success").strip().lower()
        payload = dict(context.input_payload)
        payload.setdefault("message", "模拟执行完成")
        payload.setdefault("mode", mode)
        payload.setdefault("capability_id", context.capability_id)
        payload.setdefault("trace_id", context.trace_id)
        payload.setdefault("employee_id", context.employee_id)
        payload.setdefault("task_id", context.task_id)

        if mode == "failure":
            finished_at = datetime.now(timezone.utc)
            return ExecutorResult(
                success=False,
                output={"message": "模拟失败", "mode": mode},
                error_code="MOCK_FAILURE",
                error_message="模拟执行失败",
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=max(1, int((finished_at - started_at).total_seconds() * 1000)),
                metadata={"executor": self.name, "payload_summary": payload_summary(context.input_payload)},
            )
        if mode == "timeout":
            finished_at = datetime.now(timezone.utc)
            return ExecutorResult(
                success=False,
                output={"message": "模拟超时", "mode": mode},
                error_code="MOCK_TIMEOUT",
                error_message="模拟执行超时",
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=max(1, int((finished_at - started_at).total_seconds() * 1000)),
                metadata={"executor": self.name, "payload_summary": payload_summary(context.input_payload)},
                retryable=False,
            )
        if mode == "retry" and context.retry_count < 1:
            finished_at = datetime.now(timezone.utc)
            return ExecutorResult(
                success=False,
                output={"message": "模拟重试触发", "mode": mode},
                error_code="MOCK_RETRY",
                error_message="模拟触发自动重试",
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=max(1, int((finished_at - started_at).total_seconds() * 1000)),
                metadata={"executor": self.name, "payload_summary": payload_summary(context.input_payload)},
                retryable=True,
            )

        finished_at = datetime.now(timezone.utc)
        return ExecutorResult(
            success=True,
            output={
                "message": "模拟执行成功",
                "mode": mode,
                "capability_id": context.capability_id,
                "employee_code": context.employee_code,
                "task_id": context.task_id,
                "trace_id": context.trace_id,
            },
            error_code=None,
            error_message=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(1, int((finished_at - started_at).total_seconds() * 1000)),
            metadata={"executor": self.name, "payload_summary": payload_summary(context.input_payload)},
        )

    def cancel(self, context: ExecutorContext) -> dict[str, Any]:
        return {"cancelled": True, "executor": self.name, "execution_id": context.execution_id}

    def health_check(self) -> dict[str, Any]:
        return {"ok": True, "executor": self.name, "status": "ready"}

    def get_metadata(self) -> dict[str, Any]:
        return {"executor_type": self.executor_type, "name": self.name, "supports_real_world": False}


EXECUTORS: dict[str, ExecutorProtocol] = {
    "mock": MockExecutor(),
    "browser": ReadonlyHttpBrowserExecutor(),
    "research": ResearchExecutor(),
}


def get_executor(executor_type: str) -> ExecutorProtocol:
    executor = EXECUTORS.get((executor_type or "mock").strip().lower())
    if not executor:
        raise ValueError(f"unsupported executor type: {executor_type}")
    return executor
