from __future__ import annotations

from dataclasses import dataclass

from .base import ComputerExecutorBase, ComputerExecutorOutcome
from .evidence import utcnow, make_screenshot_reference
from .policy import ensure_real_adapter_enabled


@dataclass
class MockOpenClawTransport:
    healthy: bool = True

    def health_check(self) -> dict:
        return {"healthy": self.healthy, "provider": "mock_openclaw"}

    def create_session(self, context) -> dict:
        return {"session_id": context.session_id, "provider": "mock_openclaw", "created_at": utcnow().isoformat()}

    def execute_action(self, context) -> dict:
        return {
            "success": True,
            "result": {"message": "OpenClaw 模拟执行完成"},
            "screenshot_reference": make_screenshot_reference(context.session_id, context.trace_id),
            "window_title": context.target_window or "隔离测试窗口",
            "active_application": context.target_application or "隔离测试浏览器",
        }


class OpenClawAdapter(ComputerExecutorBase):
    def __init__(self, transport: MockOpenClawTransport | None = None):
        self.transport = transport or MockOpenClawTransport()

    def validate(self, context):
        return context

    def create_session(self, context):
        ensure_real_adapter_enabled()
        return self.transport.create_session(context)

    def execute_action(self, context):
        ensure_real_adapter_enabled()
        payload = self.transport.execute_action(context)
        return ComputerExecutorOutcome(
            success=bool(payload.get("success", True)),
            action_result=payload.get("result", {}),
            screenshot_reference=payload.get("screenshot_reference"),
            window_title=payload.get("window_title"),
            active_application=payload.get("active_application"),
            started_at=utcnow(),
            finished_at=utcnow(),
            duration_ms=0,
            audit_metadata={"provider": "mock_openclaw"},
        )

    def capture_screen(self, context):
        return {"screenshot_reference": make_screenshot_reference(context.session_id, context.trace_id)}

    def get_window_state(self, context):
        return {"windows": [context.target_window or "隔离测试窗口"], "active_application": context.target_application or "隔离测试浏览器"}

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
        return self.transport.health_check()

    def get_metadata(self):
        return {"name": "OpenClawAdapter", "provider": "mock_openclaw"}
