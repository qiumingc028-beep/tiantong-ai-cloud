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
