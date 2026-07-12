from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from ..agent_runtime.executor_types import ExecutorContext, ExecutorResult
from .search_executor import execute_research_workflow


@dataclass(slots=True)
class _BrowserReader:
    def __call__(self, url: str, *, trace_id: str, allowed_domains: list[str], blocked_domains: list[str]) -> dict[str, Any]:
        from ..agent_runtime.executor import get_executor

        executor = get_executor("browser")
        domain = urlparse(url).netloc.lower()
        effective_allowed_domains = allowed_domains or [domain]
        browser_payload = {
            "url": url,
            "extract_fields": ["title", "body"],
            "allow_redirects": True,
            "method": "GET",
            "timeout_seconds": 20,
            "max_response_bytes": 500000,
            "allowed_domains": effective_allowed_domains,
            "blocked_domains": blocked_domains,
            "trace_id": trace_id,
        }
        context = ExecutorContext(
            execution_id=f"browser-{trace_id}",
            trace_id=trace_id,
            capability_id="browser.public.read",
            capability_name="公开网页读取",
            capability_type="浏览器操作",
            executor_type="browser",
            employee_id=None,
            employee_code=None,
            employee_name=None,
            task_id=None,
            retry_count=0,
            timeout_seconds=20,
            input_payload=browser_payload,
        )
        result = executor.execute(context)
        return result.output


class ResearchExecutor:
    executor_type = "research"
    name = "ResearchExecutor"

    def validate(self, context: ExecutorContext) -> None:
        if context.executor_type != "research":
            raise ValueError("ResearchExecutor only supports research capabilities")

    def execute(self, context: ExecutorContext) -> ExecutorResult:
        self.validate(context)
        started_at = datetime.now(timezone.utc)
        browser_reader = _BrowserReader()
        try:
            output = execute_research_workflow(context.input_payload, trace_id=context.trace_id, browser_reader=browser_reader)
        except Exception as exc:
            finished_at = datetime.now(timezone.utc)
            return ExecutorResult(
                success=False,
                output={"message": "公开研究执行失败"},
                error_code="RESEARCH_EXECUTION_FAILED",
                error_message=str(exc),
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=max(1, int((finished_at - started_at).total_seconds() * 1000)),
                metadata={"executor": self.name},
                retryable=False,
            )
        finished_at = datetime.now(timezone.utc)
        return ExecutorResult(
            success=True,
            output=output,
            error_code=None,
            error_message=None,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=max(1, int((finished_at - started_at).total_seconds() * 1000)),
            metadata={"executor": self.name},
        )

    def cancel(self, context: ExecutorContext) -> dict[str, Any]:
        return {"cancelled": True, "executor": self.name, "execution_id": context.execution_id}

    def health_check(self) -> dict[str, Any]:
        return {"ok": True, "executor": self.name, "status": "ready"}

    def get_metadata(self) -> dict[str, Any]:
        return {"executor_type": self.executor_type, "name": self.name, "supports_real_world": False}
