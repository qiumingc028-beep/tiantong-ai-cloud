from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..agent_runtime.runtime import invoke_agent_runtime
from ..agent_runtime.executors.computer.runtime import ComputerRuntime
from ..agent_runtime.executors.computer.schemas import ComputerActionPayload, ComputerSessionCreatePayload
from ..knowledge_center.knowledge_search import search_knowledge
from .models import Skill, SkillInvocation
from .registry import audit_employee_log, json_text, skill_to_dict, utcnow


@dataclass
class RuntimeResult:
    success: bool
    output: dict
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    metadata: dict | None = None

    @property
    def duration_ms(self) -> int | None:
        if not self.started_at or not self.finished_at:
            return None
        return max(0, int((self.finished_at - self.started_at).total_seconds() * 1000))


def redact_payload(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in ("secret", "token", "password", "cookie", "authorization", "private_key")):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        if len(value) > 256:
            return value[:256]
        return value
    return value


def invoke_mock_runtime(db: Session, skill: Skill, input_payload: dict, employee_code: str, trace_id: str | None, simulate_outcome: str | None = None) -> RuntimeResult:
    if simulate_outcome == "timeout":
        started = utcnow()
        finished = utcnow()
        return RuntimeResult(False, {"message": "执行超时"}, "EXECUTION_TIMEOUT", "执行超时", started, finished, {"executor": "mock_runtime"})
    if simulate_outcome == "failure":
        started = utcnow()
        finished = utcnow()
        return RuntimeResult(False, {"message": "模拟失败"}, "EXECUTION_FAILED", "模拟失败", started, finished, {"executor": "mock_runtime"})

    outcome = invoke_agent_runtime(
        skill_code=skill.skill_code,
        employee_code=employee_code,
        trace_id=trace_id,
        handler=lambda: execute_skill(skill, input_payload, db=db, employee_code=employee_code),
    )
    return RuntimeResult(
        success=outcome.success,
        output=outcome.output,
        error_code=outcome.error_code,
        error_message=outcome.error_message,
        started_at=outcome.started_at,
        finished_at=outcome.finished_at,
        metadata=outcome.metadata or {},
    )


def execute_skill(skill: Skill, input_payload: dict, *, db: Session, employee_code: str) -> dict:
    payload = input_payload or {}
    skill_code = skill.skill_code
    if skill_code == "research.public.report_organize":
        text = str(payload.get("research_report") or payload.get("content") or payload.get("text") or "")
        summary = {
            "report_title": str(payload.get("title") or skill.chinese_name),
            "research_summary": text[:500] or "公开研究内容已整理。",
            "key_points": [line.strip(" -") for line in text.splitlines() if line.strip()][:10],
            "evidence_count": len(payload.get("sources") or []),
            "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else hashlib.sha256(skill.skill_code.encode()).hexdigest(),
            "source_urls": [item.get("url") for item in payload.get("sources", []) if isinstance(item, dict) and item.get("url")],
            "collected_by": employee_code,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }
        return {"skill": skill_to_dict(skill, include_relations=False), "result": summary, "redacted_input": redact_payload(payload)}
    if skill_code == "knowledge.local.search":
        query = str(payload.get("query") or payload.get("q") or "").strip()
        result = search_knowledge(query or skill.chinese_name, limit=int(payload.get("limit") or 10), knowledge_type=payload.get("knowledge_type"))
        return {"skill": skill_to_dict(skill, include_relations=False), "result": result, "redacted_input": redact_payload(payload)}
    if skill_code == "computer.sandbox.status_check":
        session_payload = ComputerSessionCreatePayload(
            execution_id=payload.get("execution_id"),
            task_id=payload.get("task_id"),
            employee_id=payload.get("employee_id"),
            skill_id=skill.id,
            executor_type="mock",
            environment_type=payload.get("environment_type") or "test",
            risk_level=skill.risk_level,
            approval_status="无需审批",
            allowed_applications=["隔离测试浏览器", "隔离文本编辑器", "隔离演示窗口"],
            allowed_windows=[".*"],
            trace_id=payload.get("trace_id"),
        )
        session = ComputerRuntime.create_session(db, session_payload)
        action = ComputerActionPayload(
            action_type="查看屏幕",
            target_application="隔离测试浏览器",
            target_window="隔离测试窗口",
            text_input=None,
            timeout=30,
            trace_id=payload.get("trace_id"),
            approval_context={"skill_code": skill.skill_code},
            simulate_outcome=payload.get("simulate_outcome"),
        )
        result = ComputerRuntime.execute_action(db, session, action)
        return {
            "skill": skill_to_dict(skill, include_relations=False),
            "result": {
                "session": result["session"],
                "action": result["action"],
                "evidence": result["evidence"],
                "message": "隔离桌面状态检查完成",
            },
            "redacted_input": redact_payload(payload),
        }
    if skill_code == "computer.macos.window_check":
        from ..device_center.service import record_device_observation_from_snapshot, get_device

        device_id = str(payload.get("device_id") or "").strip()
        if not device_id:
            raise HTTPException(status_code=400, detail="设备编号缺失")
        device = get_device(db, device_id)["device"]
        snapshot = {
            "task_id": payload.get("task_id"),
            "employee_id": payload.get("employee_id"),
            "skill_id": skill.id,
            "observation_goal": payload.get("observation_goal") or "Mac 测试窗口状态检查",
            "allowed_applications": payload.get("allowed_applications") or ["VS Code", "Chrome", "Safari"],
            "allowed_windows": payload.get("allowed_windows") or [".*测试.*"],
            "max_screenshots": payload.get("max_screenshots") or 3,
            "trace_id": payload.get("trace_id"),
            "windows": payload.get("windows") or [
                {
                    "application_name": "Chrome",
                    "bundle_id": "com.google.Chrome",
                    "window_title": "天统 AI 测试页面 - 只读观察",
                    "risk_flags": [],
                    "suggested_next_step": "继续只读观察",
                }
            ],
            "screen_state": payload.get("screen_state") or "屏幕正常",
            "suggested_next_step": payload.get("suggested_next_step") or "继续只读观察",
        }
        observation = record_device_observation_from_snapshot(db, device_id, snapshot)
        return {
            "skill": skill_to_dict(skill, include_relations=False),
            "result": {
                "device_id": device["device_id"],
                "status": "执行成功",
                "current_application": (snapshot["windows"][0].get("application_name") if snapshot["windows"] else None),
                "current_window": (snapshot["windows"][0].get("window_title") if snapshot["windows"] else None),
                "window_count": len(snapshot["windows"]),
                "screenshot_reference": observation["events"][0]["screenshot_reference"] if observation["events"] else None,
                "screen_state": snapshot["screen_state"],
                "suggested_next_step": snapshot["suggested_next_step"],
                "observation": observation["observation"],
            },
            "redacted_input": redact_payload(payload),
        }
    if skill_code == "computer.macos.single_step_action":
        from ..agent_runtime.executors.computer.actions.service import create_action_plan
        from ..agent_runtime.executors.computer.schemas import ComputerActionPlanCreatePayload

        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            session_payload = ComputerSessionCreatePayload(
                executor_type="mock",
                environment_type=payload.get("environment_type") or "test",
                risk_level="中低",
                approval_status="等待审批",
                allowed_applications=payload.get("allowed_applications") or ["隔离测试浏览器", "隔离文本编辑器", "隔离演示窗口"],
                allowed_windows=payload.get("allowed_windows") or [".*隔离.*", ".*测试.*"],
                trace_id=payload.get("trace_id"),
            )
            session = ComputerRuntime.create_session(db, session_payload)
            session_id = session.session_id
        plan_payload = ComputerActionPlanCreatePayload(
            session_id=session_id,
            observation_id=payload.get("observation_id"),
            task_id=payload.get("task_id"),
            employee_id=payload.get("employee_id"),
            skill_id=skill.id,
            target_application=payload.get("target_application") or "隔离测试浏览器",
            target_bundle_id=payload.get("target_bundle_id"),
            target_window=payload.get("target_window") or "天统 AI 单步操作测试窗口",
            goal=payload.get("goal") or "Mac 测试页面单步操作",
            action_type=payload.get("action_type") or "单击",
            control_type=payload.get("control_type"),
            control_label=payload.get("control_label"),
            control_identifier=payload.get("control_identifier"),
            target_description=payload.get("target_description") or payload.get("goal") or "Mac 测试页面单步操作",
            coordinates=payload.get("coordinates"),
            text_input=payload.get("text_input"),
            approval_mode="逐步审批",
            risk_level="中低" if payload.get("action_type") in {"移动鼠标", "输入普通文本"} else "中风险",
            max_actions=1,
            trace_id=payload.get("trace_id"),
            allow_coordinate_fallback=bool(payload.get("allow_coordinate_fallback")),
        )
        plan_result = create_action_plan(db, plan_payload)
        return {
            "skill": skill_to_dict(skill, include_relations=False),
            "result": {
                "plan": plan_result["plan"],
                "target": plan_result["target"],
                "approval": plan_result["approval"],
                "preview": plan_result["preview"],
                "message": "动作计划已创建，等待逐步审批。",
            },
            "redacted_input": redact_payload(payload),
        }
    if payload.get("simulate_outcome") == "cancel":
        raise HTTPException(status_code=400, detail="执行已取消")
    return {
        "skill": skill_to_dict(skill, include_relations=False),
        "result": {
            "message": "技能已安全执行",
            "input": redact_payload(payload),
            "employee_code": employee_code,
        },
    }


def finalize_invocation(db: Session, invocation: SkillInvocation, result: RuntimeResult, *, employee_code: str, task_id: int | None = None, execution_id: int | None = None):
    invocation.status = "执行成功" if result.success else ("已超时" if result.error_code == "EXECUTION_TIMEOUT" else "执行失败")
    invocation.started_at = result.started_at
    invocation.finished_at = result.finished_at
    invocation.duration_ms = result.duration_ms
    invocation.output_summary = json_text(result.output)
    invocation.error_code = result.error_code
    invocation.error_message = result.error_message
    audit_employee_log(
        db,
        user_id=None,
        action="skill_invocation",
        detail=f"skill_code={invocation.skill_id} employee={employee_code} status={invocation.status}",
        skill_id=invocation.skill_id,
    )
    if task_id is not None:
        from ..models import TaskCenterResult

        db.add(
            TaskCenterResult(
                task_id=task_id,
                ai_employee_code=employee_code,
                ai_employee_name=employee_code,
                result_content=json_text(result.output) or "{}",
                attachments_json="[]",
            )
        )
    if execution_id is not None:
        invocation.execution_id = execution_id
    db.commit()
    db.refresh(invocation)
    return invocation
