from __future__ import annotations

from dataclasses import dataclass

from .action_validator import validate_action_payload
from .base import ComputerExecutorBase, ComputerExecutorOutcome
from .evidence import make_screenshot_reference, utcnow
from .policy import ensure_executor_enabled


@dataclass
class MockComputerExecutor(ComputerExecutorBase):
    def validate(self, context):
        return context

    def create_session(self, context):
        ensure_executor_enabled()
        return {"success": True, "session_id": context.session_id, "status": "已创建", "executor_type": "mock"}

    def execute_action(self, context):
        ensure_executor_enabled()
        validate_action_payload(context)
        started = utcnow()
        screenshot = make_screenshot_reference(context.session_id or "mock", context.trace_id)
        return ComputerExecutorOutcome(
            success=True,
            action_result={
                "message": "模拟电脑操作完成",
                "action_type": context.action_type,
                "target_application": context.target_application,
                "target_window": context.target_window,
            },
            screenshot_reference=screenshot,
            window_title=context.target_window or "隔离测试窗口",
            active_application=context.target_application or "隔离测试浏览器",
            started_at=started,
            finished_at=utcnow(),
            duration_ms=0,
            audit_metadata={"executor": "mock", "trace_id": context.trace_id},
        )

    def capture_screen(self, context):
        return {"success": True, "screenshot_reference": make_screenshot_reference(context.session_id or "mock", context.trace_id)}

    def get_window_state(self, context):
        return {
            "success": True,
            "windows": [context.target_window or "隔离测试窗口"],
            "active_application": context.target_application or "隔离测试浏览器",
        }

    def cancel(self, context):
        return {"success": True, "status": "已取消"}

    def pause(self, context):
        return {"success": True, "status": "已暂停"}

    def resume(self, context):
        return {"success": True, "status": "执行中"}

    def handoff_to_human(self, context):
        return {"success": True, "status": "等待人工接管"}

    def close_session(self, context):
        return {"success": True, "status": "已关闭"}

    def health_check(self):
        return {"healthy": True, "provider": "mock"}

    def get_metadata(self):
        return {"name": "MockComputerExecutor", "provider": "mock"}
