from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.agent_runtime.executors.computer.actions.service import approve_action, create_action_plan, execute_action, preview_action_plan
from backend.agent_runtime.executors.computer.actions.schemas import ComputerActionPlanCreatePayload
from backend.agent_runtime.executors.computer.schemas import ComputerSessionCreatePayload
from backend.agent_runtime.executors.computer.runtime import ComputerRuntime
from backend.config import get_settings
from backend.models import AiEmployee, TaskCenterResult, TaskCenterTask, User

from .approval import approve_checkpoint, approve_scope_approval, create_checkpoint_approval, create_scope_approval, reject_checkpoint, reject_scope_approval, utcnow
from .audit import summarize_workflow_audit
from .budget import ensure_budget_within_limits, normalize_budget
from .checkpoint import checkpoint_type_for_step, requires_checkpoint
from .models import ComputerWorkflow, ComputerWorkflowApproval, ComputerWorkflowCheckpoint, ComputerWorkflowRecovery, ComputerWorkflowStep, ComputerWorkflowVerification
from .planner import build_workflow_plan
from .recovery import record_recovery
from .schemas import ComputerWorkflowCreatePayload
from .verifier import verify_step_result


SAFE_CONTINUE_ACTIONS = {"查看屏幕", "获取窗口列表", "移动鼠标", "滚动", "截图", "等待"}


def _workflow_to_dict(workflow: ComputerWorkflow) -> dict:
    return {
        "workflow_id": workflow.workflow_id,
        "task_id": workflow.task_id,
        "employee_id": workflow.employee_id,
        "skill_id": workflow.skill_id,
        "device_id": workflow.device_id,
        "session_id": workflow.session_id,
        "goal": workflow.goal,
        "status": workflow.status,
        "risk_level": workflow.risk_level,
        "approval_status": workflow.approval_status,
        "total_steps": workflow.total_steps,
        "current_step": workflow.current_step,
        "max_steps": workflow.max_steps,
        "checkpoint_count": workflow.checkpoint_count,
        "execution_budget": json.loads(workflow.execution_budget_json or "{}"),
        "started_at": workflow.started_at.isoformat() if workflow.started_at else None,
        "expires_at": workflow.expires_at.isoformat() if workflow.expires_at else None,
        "finished_at": workflow.finished_at.isoformat() if workflow.finished_at else None,
        "stop_reason": workflow.stop_reason,
        "trace_id": workflow.trace_id,
        "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
        "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
    }


def _step_to_dict(step: ComputerWorkflowStep) -> dict:
    return {
        "step_id": step.step_id,
        "workflow_id": step.workflow_id,
        "sequence_number": step.sequence_number,
        "action_type": step.action_type,
        "target_application": step.target_application,
        "target_bundle_id": step.target_bundle_id,
        "target_window": step.target_window,
        "target_control": step.target_control,
        "input_summary": step.input_summary,
        "expected_result": step.expected_result,
        "risk_level": step.risk_level,
        "approval_required": step.approval_required,
        "checkpoint_required": step.checkpoint_required,
        "status": step.status,
        "action_id": step.action_id,
        "verification_id": step.verification_id,
        "started_at": step.started_at.isoformat() if step.started_at else None,
        "finished_at": step.finished_at.isoformat() if step.finished_at else None,
        "error_code": step.error_code,
        "error_message": step.error_message,
        "trace_id": step.trace_id,
    }


def _checkpoint_to_dict(checkpoint: ComputerWorkflowCheckpoint) -> dict:
    return {
        "checkpoint_id": checkpoint.checkpoint_id,
        "workflow_id": checkpoint.workflow_id,
        "step_id": checkpoint.step_id,
        "checkpoint_type": checkpoint.checkpoint_type,
        "reason": checkpoint.reason,
        "screenshot_reference": checkpoint.screenshot_reference,
        "state_summary": checkpoint.state_summary,
        "risk_level": checkpoint.risk_level,
        "approval_status": checkpoint.approval_status,
        "approved_by": checkpoint.approved_by,
        "approved_at": checkpoint.approved_at.isoformat() if checkpoint.approved_at else None,
        "expires_at": checkpoint.expires_at.isoformat() if checkpoint.expires_at else None,
        "created_at": checkpoint.created_at.isoformat() if checkpoint.created_at else None,
    }


def _approval_to_dict(approval: ComputerWorkflowApproval) -> dict:
    return {
        "approval_id": approval.approval_id,
        "workflow_id": approval.workflow_id,
        "approval_scope": approval.approval_scope,
        "approval_status": approval.approval_status,
        "approved_by": approval.approved_by,
        "approved_at": approval.approved_at.isoformat() if approval.approved_at else None,
        "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
        "reject_reason": approval.reject_reason,
        "trace_id": approval.trace_id,
        "created_at": approval.created_at.isoformat() if approval.created_at else None,
        "updated_at": approval.updated_at.isoformat() if approval.updated_at else None,
    }


def _verification_to_dict(verification: ComputerWorkflowVerification) -> dict:
    return {
        "verification_id": verification.verification_id,
        "workflow_id": verification.workflow_id,
        "step_id": verification.step_id,
        "verification_status": verification.verification_status,
        "before_screenshot_reference": verification.before_screenshot_reference,
        "after_screenshot_reference": verification.after_screenshot_reference,
        "state_summary": verification.state_summary,
        "result_summary": verification.result_summary,
        "trace_id": verification.trace_id,
        "created_at": verification.created_at.isoformat() if verification.created_at else None,
    }


def _recovery_to_dict(recovery: ComputerWorkflowRecovery) -> dict:
    return {
        "recovery_id": recovery.recovery_id,
        "workflow_id": recovery.workflow_id,
        "step_id": recovery.step_id,
        "recovery_type": recovery.recovery_type,
        "status": recovery.status,
        "reason": recovery.reason,
        "result_summary": recovery.result_summary,
        "trace_id": recovery.trace_id,
        "created_at": recovery.created_at.isoformat() if recovery.created_at else None,
        "finished_at": recovery.finished_at.isoformat() if recovery.finished_at else None,
    }


def _get_task(db: Session, task_id: int | None) -> TaskCenterTask | None:
    return db.get(TaskCenterTask, task_id) if task_id else None


def _ensure_task_result(db: Session, workflow: ComputerWorkflow, result_content: str) -> None:
    if workflow.task_id is None:
        return
    task = db.get(TaskCenterTask, workflow.task_id)
    if not task:
        return
    db.add(
        TaskCenterResult(
            task_id=task.id,
            ai_employee_code=task.assigned_ai_employee_code or "tianshu",
            ai_employee_name=task.assigned_ai_employee_name or "天数：智能数据分析中心",
            result_content=result_content,
            attachments_json=json.dumps([], ensure_ascii=False),
        )
    )
    if task.status in {"created", "split", "assigned", "running"}:
        task.status = "result_submitted"
        task.summary = result_content[:1000]


def create_workflow(db: Session, payload: ComputerWorkflowCreatePayload):
    workflow, steps = build_workflow_plan(db, payload)
    session_id = workflow.session_id
    if not session_id:
        session_payload = ComputerSessionCreatePayload(
            execution_id=None,
            task_id=workflow.task_id,
            employee_id=workflow.employee_id,
            skill_id=workflow.skill_id,
            executor_type="mock",
            environment_type="test",
            risk_level=workflow.risk_level,
            approval_status="等待审批",
            allowed_applications=["隔离测试浏览器", "隔离文本编辑器", "隔离演示窗口"],
            allowed_windows=[".*隔离.*", ".*测试.*"],
            trace_id=workflow.trace_id,
        )
        session = ComputerRuntime.create_session(db, session_payload)
        workflow.session_id = session.session_id
        db.flush()
    approval = create_scope_approval(db, workflow, approval_scope=workflow.goal, trace_id=workflow.trace_id)
    preview = preview_workflow(db, workflow.workflow_id)
    db.commit()
    db.refresh(workflow)
    db.refresh(approval)
    return {
        "workflow": _workflow_to_dict(workflow),
        "steps": [_step_to_dict(step) for step in steps],
        "approval": _approval_to_dict(approval),
        "preview": preview["preview"],
    }


def get_workflow(db: Session, workflow_id: str) -> dict:
    workflow = db.get(ComputerWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return {
        "workflow": _workflow_to_dict(workflow),
        "steps": [_step_to_dict(step) for step in db.query(ComputerWorkflowStep).filter(ComputerWorkflowStep.workflow_id == workflow_id).order_by(ComputerWorkflowStep.sequence_number.asc()).all()],
        "approvals": [_approval_to_dict(row) for row in db.query(ComputerWorkflowApproval).filter(ComputerWorkflowApproval.workflow_id == workflow_id).order_by(ComputerWorkflowApproval.created_at.asc()).all()],
        "checkpoints": [_checkpoint_to_dict(row) for row in db.query(ComputerWorkflowCheckpoint).filter(ComputerWorkflowCheckpoint.workflow_id == workflow_id).order_by(ComputerWorkflowCheckpoint.created_at.asc()).all()],
        "verifications": [_verification_to_dict(row) for row in db.query(ComputerWorkflowVerification).filter(ComputerWorkflowVerification.workflow_id == workflow_id).order_by(ComputerWorkflowVerification.created_at.asc()).all()],
        "recoveries": [_recovery_to_dict(row) for row in db.query(ComputerWorkflowRecovery).filter(ComputerWorkflowRecovery.workflow_id == workflow_id).order_by(ComputerWorkflowRecovery.created_at.asc()).all()],
    }


def preview_workflow(db: Session, workflow_id: str) -> dict:
    workflow = db.get(ComputerWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    steps = db.query(ComputerWorkflowStep).filter(ComputerWorkflowStep.workflow_id == workflow.workflow_id).order_by(ComputerWorkflowStep.sequence_number.asc()).all()
    approval = db.query(ComputerWorkflowApproval).filter(ComputerWorkflowApproval.workflow_id == workflow.workflow_id).order_by(ComputerWorkflowApproval.created_at.desc()).first()
    checkpoints = db.query(ComputerWorkflowCheckpoint).filter(ComputerWorkflowCheckpoint.workflow_id == workflow.workflow_id).order_by(ComputerWorkflowCheckpoint.created_at.asc()).all()
    return {
        "workflow": _workflow_to_dict(workflow),
        "steps": [_step_to_dict(step) for step in steps],
        "approval": _approval_to_dict(approval) if approval else None,
        "checkpoints": [_checkpoint_to_dict(row) for row in checkpoints],
        "preview": {
            "goal": workflow.goal,
            "step_count": len(steps),
            "max_steps": workflow.max_steps,
            "stop_conditions": ["目标窗口变化", "出现敏感内容", "出现禁止页面", "审批失效", "超时", "本地停止"],
            "expected_result": "有限多步骤工作流按审批逐步执行",
        },
    }


def approve_workflow(db: Session, workflow_id: str, *, approved_by: int | None, trace_id: str | None) -> dict:
    workflow = db.get(ComputerWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    approval = db.query(ComputerWorkflowApproval).filter(ComputerWorkflowApproval.workflow_id == workflow_id).order_by(ComputerWorkflowApproval.created_at.desc()).first()
    if not approval:
        approval = create_scope_approval(db, workflow, approved_by=approved_by, approval_scope=workflow.goal, trace_id=trace_id)
    approval = approve_scope_approval(db, approval, approved_by=approved_by, trace_id=trace_id)
    workflow.approval_status = "已批准"
    workflow.status = "已批准"
    db.commit()
    db.refresh(workflow)
    db.refresh(approval)
    return {"workflow": _workflow_to_dict(workflow), "approval": _approval_to_dict(approval)}


def reject_workflow(db: Session, workflow_id: str, *, approved_by: int | None, reason: str | None, trace_id: str | None) -> dict:
    workflow = db.get(ComputerWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    approval = db.query(ComputerWorkflowApproval).filter(ComputerWorkflowApproval.workflow_id == workflow_id).order_by(ComputerWorkflowApproval.created_at.desc()).first()
    if not approval:
        approval = create_scope_approval(db, workflow, approved_by=approved_by, approval_scope=workflow.goal, trace_id=trace_id)
    approval = reject_scope_approval(db, approval, approved_by=approved_by, reason=reason, trace_id=trace_id)
    workflow.approval_status = "已拒绝"
    workflow.status = "已拒绝"
    workflow.stop_reason = reason or "工作流被拒绝"
    db.commit()
    db.refresh(workflow)
    db.refresh(approval)
    return {"workflow": _workflow_to_dict(workflow), "approval": _approval_to_dict(approval)}


def _build_action_payload(step: ComputerWorkflowStep, workflow: ComputerWorkflow):
    action_type_map = {
        "查看屏幕": "查看屏幕",
        "获取窗口列表": "获取窗口列表",
        "激活允许的窗口": "激活允许的窗口",
        "移动鼠标": "移动鼠标",
        "单击": "单击",
        "滚动": "滚动",
        "输入普通文本": "输入普通文本",
        "按允许的快捷键": "按允许的快捷键",
        "截图": "截图",
        "等待": "等待",
    }
    return ComputerActionPlanCreatePayload(
        session_id=workflow.session_id or "",
        task_id=workflow.task_id,
        employee_id=workflow.employee_id,
        skill_id=workflow.skill_id,
        target_application=step.target_application,
        target_bundle_id=step.target_bundle_id,
        target_window=step.target_window,
        goal=workflow.goal,
        action_type=action_type_map.get(step.action_type, step.action_type),
        control_type=step.target_control,
        control_label=step.target_control,
        control_identifier=step.target_control,
        target_description=step.expected_result or step.input_summary or workflow.goal,
        coordinates=None,
        text_input=step.input_summary if step.action_type == "输入普通文本" else None,
        approval_mode="逐步审批",
        risk_level=step.risk_level,
        max_actions=1,
        trace_id=step.trace_id or workflow.trace_id,
        allow_coordinate_fallback=False,
    )


def _next_step(db: Session, workflow: ComputerWorkflow) -> ComputerWorkflowStep | None:
    return (
        db.query(ComputerWorkflowStep)
        .filter(ComputerWorkflowStep.workflow_id == workflow.workflow_id, ComputerWorkflowStep.sequence_number > workflow.current_step)
        .order_by(ComputerWorkflowStep.sequence_number.asc())
        .first()
    )


def _pause_workflow(db: Session, workflow: ComputerWorkflow, reason: str | None = None) -> dict:
    workflow.status = "已暂停"
    if reason:
        workflow.stop_reason = reason
    db.commit()
    db.refresh(workflow)
    return {"workflow": _workflow_to_dict(workflow)}


def start_workflow(db: Session, workflow_id: str, *, current_application: str | None = None, current_window: str | None = None, current_screenshot_hash: str | None = None, trace_id: str | None = None) -> dict:
    workflow = db.get(ComputerWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if workflow.approval_status != "已批准":
        raise HTTPException(status_code=403, detail="工作流尚未批准")
    if workflow.status not in {"已批准", "已暂停", "等待关键节点确认", "执行中"}:
        raise HTTPException(status_code=409, detail="工作流状态不允许启动")
    step = _next_step(db, workflow)
    if not step:
        workflow.status = "已完成"
        workflow.finished_at = utcnow()
        db.commit()
        db.refresh(workflow)
        return {"workflow": _workflow_to_dict(workflow), "steps": []}
    return execute_step(db, workflow_id, step.sequence_number, current_application=current_application, current_window=current_window, current_screenshot_hash=current_screenshot_hash, trace_id=trace_id)


def execute_step(db: Session, workflow_id: str, sequence_number: int, *, current_application: str | None = None, current_window: str | None = None, current_screenshot_hash: str | None = None, trace_id: str | None = None) -> dict:
    workflow = db.get(ComputerWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if workflow.status in {"已取消", "已终止", "已失败", "已超时"}:
        raise HTTPException(status_code=409, detail="工作流已结束")
    step = (
        db.query(ComputerWorkflowStep)
        .filter(ComputerWorkflowStep.workflow_id == workflow.workflow_id, ComputerWorkflowStep.sequence_number == sequence_number)
        .one_or_none()
    )
    if not step:
        raise HTTPException(status_code=404, detail="工作流步骤不存在")
    ensure_budget_within_limits(workflow)
    if workflow.session_id is None:
        raise HTTPException(status_code=409, detail="工作流会话不存在")
    if step.status not in {"待执行", "已批准", "已跳过"}:
        raise HTTPException(status_code=409, detail="工作流步骤状态不允许执行")
    workflow.status = "执行中"
    if not workflow.started_at:
        workflow.started_at = utcnow()
    step.started_at = utcnow()
    approved_checkpoint = (
        db.query(ComputerWorkflowCheckpoint)
        .filter(
            ComputerWorkflowCheckpoint.workflow_id == workflow.workflow_id,
            ComputerWorkflowCheckpoint.step_id == step.step_id,
            ComputerWorkflowCheckpoint.approval_status == "已批准",
        )
        .order_by(ComputerWorkflowCheckpoint.created_at.desc())
        .first()
    )
    if step.checkpoint_required and not approved_checkpoint:
        checkpoint = create_checkpoint_approval(
            db,
            workflow,
            step_id=step.step_id,
            checkpoint_type=checkpoint_type_for_step(step),
            reason=step.expected_result or step.input_summary or workflow.goal,
            risk_level=step.risk_level,
            screenshot_reference=current_screenshot_hash,
            state_summary=current_window or current_application,
            trace_id=trace_id or workflow.trace_id,
        )
        step.status = "等待审批"
        workflow.status = "等待关键节点确认"
        db.commit()
        db.refresh(workflow)
        db.refresh(step)
        db.refresh(checkpoint)
        return {"workflow": _workflow_to_dict(workflow), "step": _step_to_dict(step), "checkpoint": _checkpoint_to_dict(checkpoint), "paused": True}
    plan_payload = _build_action_payload(step, workflow)
    plan_result = create_action_plan(db, plan_payload)
    plan_id = plan_result["plan"]["plan_id"]
    approval = approve_action(db, plan_id=plan_id, approved_by=None, approval_scope=workflow.goal, trace_id=trace_id or workflow.trace_id, current_screenshot_hash=current_screenshot_hash)
    action_result = execute_action(
        db,
        plan_id=plan_id,
        current_application=current_application,
        current_window=current_window,
        current_screenshot_hash=current_screenshot_hash,
        trace_id=trace_id or workflow.trace_id,
    )
    runtime_result = action_result.get("result") or {}
    action_data = runtime_result.get("action") or {}
    verification_row = verify_step_result(
        db,
        workflow,
        step,
        before_screenshot_reference=plan_result["target"].get("screenshot_before"),
        after_screenshot_reference=action_data.get("screenshot_after") or action_data.get("screenshot_before"),
        state_summary=current_window or current_application,
        result_summary=action_data.get("result") or action_data.get("error_message"),
        verification_status=(runtime_result.get("verification") or {}).get("verification_status") or "无法判断",
        trace_id=trace_id or workflow.trace_id,
    )
    step.action_id = action_result["target"]["action_id"]
    step.started_at = step.started_at or utcnow()
    step.finished_at = utcnow()
    step.status = "已完成" if verification_row.verification_status in {"结果符合预期", "结果部分符合"} else "已失败"
    workflow.current_step = max(workflow.current_step, sequence_number)
    workflow.checkpoint_count = workflow.checkpoint_count + (1 if step.checkpoint_required else 0)
    workflow.status = "已暂停"
    if step.status == "已失败":
        workflow.status = "已失败"
        workflow.stop_reason = verification_row.result_summary or "步骤验证失败"
    next_step = _next_step(db, workflow)
    if not next_step:
        workflow.status = "已完成" if step.status == "已完成" else workflow.status
        if workflow.status == "已完成":
            workflow.finished_at = utcnow()
            _ensure_task_result(db, workflow, f"工作流 {workflow.goal} 已完成")
    elif workflow.status == "已暂停" and step.action_type in SAFE_CONTINUE_ACTIONS and not next_step.checkpoint_required and get_settings().WORKFLOW_AUTO_CONTINUE_ENABLED:
        workflow.status = "执行中"
    recovery = None
    if step.status == "已失败":
        recovery = record_recovery(db, workflow, step_id=step.step_id, reason=workflow.stop_reason, result_summary="失败后停止，等待人工恢复", trace_id=trace_id or workflow.trace_id)
        workflow.status = "已失败"
    db.commit()
    db.refresh(workflow)
    db.refresh(step)
    if recovery:
        db.refresh(recovery)
    return {
        "workflow": _workflow_to_dict(workflow),
        "step": _step_to_dict(step),
        "preview": plan_result["preview"],
        "plan": plan_result["plan"],
        "target": plan_result["target"],
        "approval": approval["approval"],
        "verification": _verification_to_dict(verification_row),
        "action": action_data,
        "result": runtime_result,
        "paused": workflow.status in {"已暂停", "等待关键节点确认"},
    }


def pause_workflow(db: Session, workflow_id: str, reason: str | None = None) -> dict:
    workflow = db.get(ComputerWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    workflow.status = "已暂停"
    if reason:
        workflow.stop_reason = reason
    db.commit()
    db.refresh(workflow)
    return {"workflow": _workflow_to_dict(workflow)}


def resume_workflow(db: Session, workflow_id: str, *, current_application: str | None = None, current_window: str | None = None, current_screenshot_hash: str | None = None, trace_id: str | None = None) -> dict:
    workflow = db.get(ComputerWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    next_step = _next_step(db, workflow)
    if not next_step:
        workflow.status = "已完成"
        workflow.finished_at = utcnow()
        db.commit()
        db.refresh(workflow)
        return {"workflow": _workflow_to_dict(workflow), "steps": []}
    return execute_step(db, workflow_id, next_step.sequence_number, current_application=current_application, current_window=current_window, current_screenshot_hash=current_screenshot_hash, trace_id=trace_id)


def cancel_workflow(db: Session, workflow_id: str, reason: str | None = None, trace_id: str | None = None) -> dict:
    workflow = db.get(ComputerWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    workflow.status = "已取消"
    workflow.stop_reason = reason or "工作流已取消"
    workflow.finished_at = utcnow()
    db.commit()
    db.refresh(workflow)
    return {"workflow": _workflow_to_dict(workflow)}


def approve_workflow_checkpoint(db: Session, checkpoint_id: str, *, approved_by: int | None, trace_id: str | None) -> dict:
    checkpoint = db.get(ComputerWorkflowCheckpoint, checkpoint_id)
    if not checkpoint:
        raise HTTPException(status_code=404, detail="关键节点不存在")
    checkpoint = approve_checkpoint(db, checkpoint, approved_by=approved_by, trace_id=trace_id)
    workflow = db.get(ComputerWorkflow, checkpoint.workflow_id)
    if workflow and workflow.status == "等待关键节点确认":
        workflow.status = "已批准"
    step = db.get(ComputerWorkflowStep, checkpoint.step_id) if checkpoint.step_id else None
    if step:
        step.status = "已批准"
    db.commit()
    db.refresh(checkpoint)
    if workflow:
        db.refresh(workflow)
    if step:
        db.refresh(step)
    return {"checkpoint": _checkpoint_to_dict(checkpoint), "workflow": _workflow_to_dict(workflow) if workflow else None}


def reject_workflow_checkpoint(db: Session, checkpoint_id: str, *, approved_by: int | None, reason: str | None, trace_id: str | None) -> dict:
    checkpoint = db.get(ComputerWorkflowCheckpoint, checkpoint_id)
    if not checkpoint:
        raise HTTPException(status_code=404, detail="关键节点不存在")
    checkpoint = reject_checkpoint(db, checkpoint, approved_by=approved_by, reason=reason, trace_id=trace_id)
    workflow = db.get(ComputerWorkflow, checkpoint.workflow_id)
    if workflow:
        workflow.status = "已终止"
        workflow.stop_reason = reason or "关键节点被拒绝"
        workflow.finished_at = utcnow()
        step = db.get(ComputerWorkflowStep, checkpoint.step_id) if checkpoint.step_id else None
        if step:
            step.status = "已取消"
    db.commit()
    db.refresh(checkpoint)
    if workflow:
        db.refresh(workflow)
    return {"checkpoint": _checkpoint_to_dict(checkpoint), "workflow": _workflow_to_dict(workflow) if workflow else None}


def workflow_audit(db: Session, workflow_id: str) -> dict:
    workflow = db.get(ComputerWorkflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    steps = db.query(ComputerWorkflowStep).filter(ComputerWorkflowStep.workflow_id == workflow_id).order_by(ComputerWorkflowStep.sequence_number.asc()).all()
    approvals = db.query(ComputerWorkflowApproval).filter(ComputerWorkflowApproval.workflow_id == workflow_id).order_by(ComputerWorkflowApproval.created_at.asc()).all()
    checkpoints = db.query(ComputerWorkflowCheckpoint).filter(ComputerWorkflowCheckpoint.workflow_id == workflow_id).order_by(ComputerWorkflowCheckpoint.created_at.asc()).all()
    verifications = db.query(ComputerWorkflowVerification).filter(ComputerWorkflowVerification.workflow_id == workflow_id).order_by(ComputerWorkflowVerification.created_at.asc()).all()
    recoveries = db.query(ComputerWorkflowRecovery).filter(ComputerWorkflowRecovery.workflow_id == workflow_id).order_by(ComputerWorkflowRecovery.created_at.asc()).all()
    return {
        "workflow_id": workflow_id,
        "events": summarize_workflow_audit(workflow, steps, approvals, checkpoints, verifications, recoveries),
    }
