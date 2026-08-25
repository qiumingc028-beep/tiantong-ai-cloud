from __future__ import annotations

import json
import statistics
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from ..agent_runtime.executors.computer.actions.models import (
    ComputerActionApproval,
    ComputerActionPlan,
    ComputerActionTarget,
    ComputerActionVerification,
)
from ..agent_runtime.executors.computer.models import ComputerAction, ComputerSession
from ..agent_runtime.workflows.computer.models import (
    ComputerWorkflow,
    ComputerWorkflowCheckpoint,
    ComputerWorkflowRecovery,
    ComputerWorkflowStep,
    ComputerWorkflowVerification,
)
from ..config import get_settings
from ..device_center.models import Device, DeviceObservationEvent, DeviceObservationSession, DeviceSecurityEvent
from ..models import AiEmployee, TaskCenterTask
from ..skills_engine.models import Skill
from .constants import ALERT_DEFAULT_RULES, BREAKER_STATUSES, DEVICE_HEALTH_GRADES, INCIDENT_SEVERITIES, INCIDENT_STATUSES, QUALITY_GRADES, RISK_GRADES
from .exceptions import ObservabilityNotFoundError
from .models import (
    AlertEvent,
    AlertRule,
    AnomalyEvent,
    CircuitBreaker,
    DeviceHealthScore,
    DeviceRuntimeMetric,
    EmployeeExecutionMetric,
    ExecutionQualityScore,
    ExecutionReplayIndex,
    ExecutionRiskScore,
    ExecutionRuntimeMetric,
    SecurityIncident,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _seconds_since(dt: datetime | None) -> int:
    normalized = _ensure_utc(dt)
    if normalized is None:
        return 0
    return max(0, int((utcnow() - normalized).total_seconds()))


def _json_loads(value: str | None, default: Any):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    k = (len(values) - 1) * percentile
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return int(round(values[f] * (c - k) + values[c] * (k - f)))


def _human_grade_from_score(score: int) -> str:
    if score >= 90:
        return "优秀"
    if score >= 80:
        return "良好"
    if score >= 65:
        return "合格"
    if score >= 50:
        return "需改进"
    return "不合格"


def _risk_grade_from_score(score: int) -> str:
    if score >= 90:
        return "极高"
    if score >= 70:
        return "高"
    if score >= 40:
        return "中"
    return "低"


def _device_health_grade(score: int) -> str:
    if score >= 90:
        return "健康"
    if score >= 75:
        return "注意"
    if score >= 55:
        return "风险"
    return "不可用"


def _scope_row_key(scope_type: str, scope_id: str) -> tuple[str, str]:
    return scope_type, scope_id


def ensure_default_alert_rules(db: Session) -> list[AlertRule]:
    created: list[AlertRule] = []
    for data in ALERT_DEFAULT_RULES:
        rule = db.query(AlertRule).filter(AlertRule.rule_code == data["rule_code"]).one_or_none()
        if rule:
            continue
        rule = AlertRule(
            rule_id=uuid.uuid4().hex,
            chinese_name=data["中文名称"],
            rule_code=data["rule_code"],
            metric_name=data["metric_name"],
            condition=data["condition"],
            threshold=str(data["threshold"]),
            duration_seconds=int(data["duration_seconds"]),
            severity=data["severity"],
            action=data["action"],
            enabled=bool(data["enabled"]),
            environment=data["environment"],
        )
        db.add(rule)
        created.append(rule)
    if created:
        db.flush()
    return created


def _query_count(query) -> int:
    return int(query.count() or 0)


def _latest_runtime_metric(db: Session, device_id: str) -> DeviceRuntimeMetric | None:
    return (
        db.query(DeviceRuntimeMetric)
        .filter(DeviceRuntimeMetric.device_id == device_id)
        .order_by(DeviceRuntimeMetric.captured_at.desc(), DeviceRuntimeMetric.created_at.desc())
        .first()
    )


def _upsert_device_runtime_metric(db: Session, device: Device) -> DeviceRuntimeMetric:
    metric = _latest_runtime_metric(db, device.device_id)
    observation_count = _query_count(db.query(DeviceObservationSession).filter(DeviceObservationSession.device_id == device.device_id))
    active_workflow_count = _query_count(
        db.query(ComputerWorkflow).filter(
            ComputerWorkflow.device_id == device.device_id,
            ComputerWorkflow.status.in_(["执行中", "已暂停", "等待关键节点确认", "已批准"]),
        )
    )
    recent_error_count = _query_count(db.query(DeviceSecurityEvent).filter(DeviceSecurityEvent.device_id == device.device_id))
    auth_failure_count = _query_count(db.query(DeviceSecurityEvent).filter(DeviceSecurityEvent.device_id == device.device_id, DeviceSecurityEvent.event_code.like("%AUTH%")))
    replay_block_count = _query_count(db.query(DeviceSecurityEvent).filter(DeviceSecurityEvent.device_id == device.device_id, DeviceSecurityEvent.event_code.like("%REPLAY%")))
    emergency_stop_count = _query_count(db.query(DeviceSecurityEvent).filter(DeviceSecurityEvent.device_id == device.device_id, DeviceSecurityEvent.event_code.like("%EMERGENCY_STOP%")))
    last_screenshot_at = (
        db.query(func.max(DeviceObservationSession.started_at))
        .filter(DeviceObservationSession.device_id == device.device_id)
        .scalar()
    )
    heartbeat_age = 0
    if device.last_seen_at:
        heartbeat_age = _seconds_since(device.last_seen_at)
    cpu_usage = min(100, 15 + observation_count * 5 + active_workflow_count * 7 + auth_failure_count * 8)
    memory_usage = min(100, 20 + active_workflow_count * 8 + recent_error_count * 3)
    disk_free = max(0, 500_000_000 - recent_error_count * 10_000_000)
    request_failure_rate = min(100, auth_failure_count * 10 + replay_block_count * 12)
    if metric is None:
        metric = DeviceRuntimeMetric(
            metric_id=uuid.uuid4().hex,
            device_id=device.device_id,
            online_status=device.status,
            last_heartbeat_at=device.last_seen_at,
            agent_version=device.agent_version,
            operating_system=device.operating_system,
            cpu_usage_percent=cpu_usage,
            memory_usage_percent=memory_usage,
            disk_free_bytes=disk_free,
            agent_process_status="运行中" if device.enabled and device.revoked_at is None else "已停止",
            current_session_count=observation_count,
            current_workflow_count=active_workflow_count,
            recent_error_count=recent_error_count,
            recent_screenshot_at=last_screenshot_at,
            network_latency_ms=min(1000, 40 + heartbeat_age),
            request_failure_rate=request_failure_rate,
            auth_failure_count=auth_failure_count,
            replay_block_count=replay_block_count,
            emergency_stop_count=emergency_stop_count,
            trace_id=device.certificate_fingerprint,
            captured_at=utcnow(),
        )
        db.add(metric)
    else:
        metric.online_status = device.status
        metric.last_heartbeat_at = device.last_seen_at
        metric.agent_version = device.agent_version
        metric.operating_system = device.operating_system
        metric.cpu_usage_percent = cpu_usage
        metric.memory_usage_percent = memory_usage
        metric.disk_free_bytes = disk_free
        metric.agent_process_status = "运行中" if device.enabled and device.revoked_at is None else "已停止"
        metric.current_session_count = observation_count
        metric.current_workflow_count = active_workflow_count
        metric.recent_error_count = recent_error_count
        metric.recent_screenshot_at = last_screenshot_at
        metric.network_latency_ms = min(1000, 40 + heartbeat_age)
        metric.request_failure_rate = request_failure_rate
        metric.auth_failure_count = auth_failure_count
        metric.replay_block_count = replay_block_count
        metric.emergency_stop_count = emergency_stop_count
        metric.trace_id = device.certificate_fingerprint
        metric.captured_at = utcnow()
    return metric


def collect_device_metrics(db: Session, device_id: str | None = None) -> list[DeviceRuntimeMetric]:
    query = db.query(Device)
    if device_id:
        query = query.filter(Device.device_id == device_id)
    devices = query.order_by(Device.created_at.asc()).all()
    metrics = [_upsert_device_runtime_metric(db, device) for device in devices]
    db.flush()
    return metrics


def _session_actions(session_id: str) -> list[ComputerAction]:
    return []


def _compute_duration_values(rows: list[Any]) -> list[int]:
    durations: list[int] = []
    for row in rows:
        if getattr(row, "duration_ms", None) is not None:
            durations.append(int(row.duration_ms or 0))
            continue
        started = getattr(row, "started_at", None)
        finished = getattr(row, "finished_at", None)
        if started and finished:
            durations.append(max(0, int((finished - started).total_seconds() * 1000)))
    return durations


def _workflow_execution_metrics(db: Session, workflow: ComputerWorkflow) -> dict[str, Any]:
    steps = db.query(ComputerWorkflowStep).filter(ComputerWorkflowStep.workflow_id == workflow.workflow_id).order_by(ComputerWorkflowStep.sequence_number.asc()).all()
    approvals = db.query(ComputerWorkflowCheckpoint).filter(ComputerWorkflowCheckpoint.workflow_id == workflow.workflow_id).all()
    verifications = db.query(ComputerWorkflowVerification).filter(ComputerWorkflowVerification.workflow_id == workflow.workflow_id).all()
    recoveries = db.query(ComputerWorkflowRecovery).filter(ComputerWorkflowRecovery.workflow_id == workflow.workflow_id).all()
    durations = _compute_duration_values(steps)
    total_count = len(steps)
    success_count = sum(1 for step in steps if step.status == "已完成")
    failure_count = sum(1 for step in steps if step.status == "已失败")
    canceled_count = sum(1 for step in steps if step.status in {"已取消", "已跳过"})
    timeout_count = 1 if workflow.status == "已超时" else 0
    retry_count = sum(1 for recovery in recoveries if recovery.status == "已完成")
    approval_waits = [
        max(0, int((row.approved_at - row.created_at).total_seconds() * 1000))
        for row in db.query(ComputerWorkflowCheckpoint).filter(
            ComputerWorkflowCheckpoint.workflow_id == workflow.workflow_id,
            ComputerWorkflowCheckpoint.approved_at.is_not(None),
        )
    ]
    checkpoint_waits = [
        max(0, int((row.approved_at - row.created_at).total_seconds() * 1000))
        for row in db.query(ComputerWorkflowCheckpoint).filter(
            ComputerWorkflowCheckpoint.workflow_id == workflow.workflow_id,
            ComputerWorkflowCheckpoint.approved_at.is_not(None),
        )
    ]
    verification_fail_count = sum(1 for row in verifications if row.verification_status not in {"结果符合预期", "结果部分符合"})
    page_change_count = sum(1 for step in steps if step.action_type in {"单击", "输入普通文本", "按允许的快捷键"})
    window_change_count = len({step.target_window for step in steps if step.target_window})
    sensitive_block_count = sum(1 for step in steps if "密码" in (step.input_summary or "") or "验证码" in (step.input_summary or ""))
    emergency_stop_count = 1 if workflow.stop_reason and "紧急停止" in workflow.stop_reason else 0
    takeover_count = sum(1 for row in recoveries if row.recovery_type in {"人工接管", "manual_handoff"})
    budget_exceeded_count = 1 if workflow.stop_reason and "预算" in workflow.stop_reason else 0
    avg_duration_ms = int(sum(durations) / len(durations)) if durations else 0
    p50 = _percentile(durations, 0.5) if durations else 0
    p95 = _percentile(durations, 0.95) if durations else 0
    single_step_failure_rate = int(round((failure_count / total_count) * 100)) if total_count else 0
    workflow_completion_rate = int(round((success_count / total_count) * 100)) if total_count else 0
    return {
        "total_count": total_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "canceled_count": canceled_count,
        "timeout_count": timeout_count,
        "avg_duration_ms": avg_duration_ms,
        "p50_duration_ms": p50,
        "p95_duration_ms": p95,
        "retry_count": retry_count,
        "approval_wait_ms": int(sum(approval_waits) / len(approval_waits)) if approval_waits else 0,
        "checkpoint_wait_ms": int(sum(checkpoint_waits) / len(checkpoint_waits)) if checkpoint_waits else 0,
        "verification_fail_count": verification_fail_count,
        "page_change_count": page_change_count,
        "window_change_count": window_change_count,
        "sensitive_block_count": sensitive_block_count,
        "emergency_stop_count": emergency_stop_count,
        "takeover_count": takeover_count,
        "budget_exceeded_count": budget_exceeded_count,
        "single_step_failure_rate": single_step_failure_rate,
        "workflow_completion_rate": workflow_completion_rate,
    }


def _session_execution_metrics(db: Session, session: ComputerSession) -> dict[str, Any]:
    actions = db.query(ComputerAction).filter(ComputerAction.session_id == session.session_id).order_by(ComputerAction.sequence_number.asc()).all()
    durations = _compute_duration_values(actions)
    total_count = len(actions)
    success_count = sum(1 for action in actions if not action.error_code and action.result)
    failure_count = sum(1 for action in actions if action.error_code)
    canceled_count = sum(1 for action in actions if action.action_type == "取消任务")
    timeout_count = 1 if session.status == "已超时" else 0
    retry_count = sum(1 for action in actions if action.error_code and "RETRY" in (action.error_code or ""))
    approval_wait_ms = 0
    checkpoint_wait_ms = 0
    verification_fail_count = sum(1 for action in actions if action.result and "验证失败" in action.result)
    page_change_count = sum(1 for action in actions if action.action_type in {"单击", "输入普通文本", "按允许的快捷键"})
    window_change_count = len({action.target_window for action in actions if action.target_window})
    sensitive_block_count = sum(1 for action in actions if "密码" in (action.input_summary or "") or "验证码" in (action.input_summary or ""))
    emergency_stop_count = 1 if session.takeover_status in {"本地停止", "人工接管"} else 0
    takeover_count = sum(1 for action in actions if action.action_type == "取消任务")
    budget_exceeded_count = 1 if session.status == "已超时" else 0
    avg_duration_ms = int(sum(durations) / len(durations)) if durations else 0
    p50 = _percentile(durations, 0.5) if durations else 0
    p95 = _percentile(durations, 0.95) if durations else 0
    single_step_failure_rate = int(round((failure_count / total_count) * 100)) if total_count else 0
    workflow_completion_rate = int(round((success_count / total_count) * 100)) if total_count else 0
    return {
        "total_count": total_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "canceled_count": canceled_count,
        "timeout_count": timeout_count,
        "avg_duration_ms": avg_duration_ms,
        "p50_duration_ms": p50,
        "p95_duration_ms": p95,
        "retry_count": retry_count,
        "approval_wait_ms": approval_wait_ms,
        "checkpoint_wait_ms": checkpoint_wait_ms,
        "verification_fail_count": verification_fail_count,
        "page_change_count": page_change_count,
        "window_change_count": window_change_count,
        "sensitive_block_count": sensitive_block_count,
        "emergency_stop_count": emergency_stop_count,
        "takeover_count": takeover_count,
        "budget_exceeded_count": budget_exceeded_count,
        "single_step_failure_rate": single_step_failure_rate,
        "workflow_completion_rate": workflow_completion_rate,
    }


def _plan_execution_metrics(db: Session, plan: ComputerActionPlan) -> dict[str, Any]:
    targets = db.query(ComputerActionTarget).filter(ComputerActionTarget.plan_id == plan.plan_id).all()
    approvals = db.query(ComputerActionApproval).filter(ComputerActionApproval.plan_id == plan.plan_id).all()
    verifications = db.query(ComputerActionVerification).filter(ComputerActionVerification.plan_id == plan.plan_id).all()
    durations = _compute_duration_values(verifications)
    total_count = len(targets) or 1
    success_count = sum(1 for row in verifications if row.verification_status == "结果符合预期")
    failure_count = sum(1 for row in verifications if row.verification_status == "结果不符合")
    canceled_count = 0
    timeout_count = 0
    retry_count = 0
    approval_wait_ms = sum(
        max(0, int((row.approved_at - row.created_at).total_seconds() * 1000))
        for row in approvals
        if row.approved_at
    )
    checkpoint_wait_ms = 0
    verification_fail_count = sum(1 for row in verifications if row.verification_status not in {"结果符合预期", "结果部分符合"})
    page_change_count = sum(1 for row in targets if row.action_type in {"单击", "输入普通文本", "按允许的快捷键"})
    window_change_count = len({row.expected_window for row in targets if row.expected_window})
    sensitive_block_count = sum(1 for row in targets if "密码" in (row.input_text_summary or "") or "验证码" in (row.input_text_summary or ""))
    emergency_stop_count = 0
    takeover_count = 0
    budget_exceeded_count = 0
    avg_duration_ms = int(sum(durations) / len(durations)) if durations else 0
    p50 = _percentile(durations, 0.5) if durations else 0
    p95 = _percentile(durations, 0.95) if durations else 0
    single_step_failure_rate = int(round((failure_count / total_count) * 100)) if total_count else 0
    workflow_completion_rate = int(round((success_count / total_count) * 100)) if total_count else 0
    return {
        "total_count": total_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "canceled_count": canceled_count,
        "timeout_count": timeout_count,
        "avg_duration_ms": avg_duration_ms,
        "p50_duration_ms": p50,
        "p95_duration_ms": p95,
        "retry_count": retry_count,
        "approval_wait_ms": int(approval_wait_ms),
        "checkpoint_wait_ms": checkpoint_wait_ms,
        "verification_fail_count": verification_fail_count,
        "page_change_count": page_change_count,
        "window_change_count": window_change_count,
        "sensitive_block_count": sensitive_block_count,
        "emergency_stop_count": emergency_stop_count,
        "takeover_count": takeover_count,
        "budget_exceeded_count": budget_exceeded_count,
        "single_step_failure_rate": single_step_failure_rate,
        "workflow_completion_rate": workflow_completion_rate,
    }


def _upsert_metric_row(db: Session, model, key_fields: dict[str, Any], values: dict[str, Any]):
    query = db.query(model)
    for key, value in key_fields.items():
        query = query.filter(getattr(model, key) == value)
    row = query.order_by(desc(getattr(model, "updated_at", model.created_at))).first()
    if row is None:
        row = model(**key_fields, **values)
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return row


def collect_execution_metrics(db: Session) -> list[ExecutionRuntimeMetric]:
    rows: list[ExecutionRuntimeMetric] = []
    workflows = db.query(ComputerWorkflow).order_by(ComputerWorkflow.created_at.asc()).all()
    for workflow in workflows:
        metrics = _workflow_execution_metrics(db, workflow)
        row = _upsert_metric_row(
            db,
            ExecutionRuntimeMetric,
            {"scope_type": "workflow", "scope_id": workflow.workflow_id},
            {
                "metric_id": uuid.uuid4().hex if not db.query(ExecutionRuntimeMetric).filter(ExecutionRuntimeMetric.scope_type == "workflow", ExecutionRuntimeMetric.scope_id == workflow.workflow_id).first() else db.query(ExecutionRuntimeMetric).filter(ExecutionRuntimeMetric.scope_type == "workflow", ExecutionRuntimeMetric.scope_id == workflow.workflow_id).first().metric_id,
                "execution_id": workflow.workflow_id,
                "task_id": workflow.task_id,
                "employee_id": workflow.employee_id,
                "skill_id": workflow.skill_id,
                "session_id": workflow.session_id,
                "workflow_id": workflow.workflow_id,
                **metrics,
                "trace_id": workflow.trace_id,
                "captured_at": utcnow(),
            },
        )
        rows.append(row)

    sessions = db.query(ComputerSession).order_by(ComputerSession.created_at.asc()).all()
    for session in sessions:
        metrics = _session_execution_metrics(db, session)
        row = _upsert_metric_row(
            db,
            ExecutionRuntimeMetric,
            {"scope_type": "session", "scope_id": session.session_id},
            {
                "metric_id": uuid.uuid4().hex if not db.query(ExecutionRuntimeMetric).filter(ExecutionRuntimeMetric.scope_type == "session", ExecutionRuntimeMetric.scope_id == session.session_id).first() else db.query(ExecutionRuntimeMetric).filter(ExecutionRuntimeMetric.scope_type == "session", ExecutionRuntimeMetric.scope_id == session.session_id).first().metric_id,
                "execution_id": str(session.execution_id or session.session_id),
                "task_id": session.task_id,
                "employee_id": session.employee_id,
                "skill_id": session.skill_id,
                "session_id": session.session_id,
                "workflow_id": None,
                **metrics,
                "trace_id": session.trace_id,
                "captured_at": utcnow(),
            },
        )
        rows.append(row)

    plans = db.query(ComputerActionPlan).order_by(ComputerActionPlan.created_at.asc()).all()
    for plan in plans:
        metrics = _plan_execution_metrics(db, plan)
        row = _upsert_metric_row(
            db,
            ExecutionRuntimeMetric,
            {"scope_type": "plan", "scope_id": plan.plan_id},
            {
                "metric_id": uuid.uuid4().hex if not db.query(ExecutionRuntimeMetric).filter(ExecutionRuntimeMetric.scope_type == "plan", ExecutionRuntimeMetric.scope_id == plan.plan_id).first() else db.query(ExecutionRuntimeMetric).filter(ExecutionRuntimeMetric.scope_type == "plan", ExecutionRuntimeMetric.scope_id == plan.plan_id).first().metric_id,
                "execution_id": plan.plan_id,
                "task_id": plan.task_id,
                "employee_id": plan.employee_id,
                "skill_id": plan.skill_id,
                "session_id": plan.session_id,
                "workflow_id": None,
                **metrics,
                "trace_id": plan.trace_id,
                "captured_at": utcnow(),
            },
        )
        rows.append(row)

    db.flush()
    return rows


def _quality_from_metrics(metrics: dict[str, Any]) -> tuple[int, list[str], list[str], list[str]]:
    score = 100
    reasons: list[str] = []
    suggestions: list[str] = []
    dimensions = {
        "任务完成": 25,
        "动作验证": 20,
        "步骤准确": 20,
        "耗时": 15,
        "审批等待": 10,
        "异常情况": 10,
    }
    success_count = metrics["success_count"]
    total_count = max(1, metrics["total_count"])
    completion_rate = int(round(success_count / total_count * 100))
    dimension_scores = {
        "任务完成": completion_rate,
        "动作验证": max(0, 100 - metrics["verification_fail_count"] * 20),
        "步骤准确": max(0, 100 - metrics["failure_count"] * 20 - metrics["canceled_count"] * 10),
        "耗时": max(0, 100 - min(60, metrics["avg_duration_ms"] // 1000)),
        "审批等待": max(0, 100 - min(50, metrics["approval_wait_ms"] // 1000)),
        "异常情况": max(0, 100 - (metrics["emergency_stop_count"] * 20 + metrics["budget_exceeded_count"] * 20 + metrics["sensitive_block_count"] * 25)),
    }
    score = int(round(sum(dimension_scores[k] * v for k, v in dimensions.items()) / sum(dimensions.values())))
    if metrics["failure_count"]:
        reasons.append(f"失败步骤 {metrics['failure_count']} 个")
        suggestions.append("减少失败步骤并在关键节点前加强校验")
    if metrics["verification_fail_count"]:
        reasons.append(f"验证失败 {metrics['verification_fail_count']} 次")
        suggestions.append("提高执行后的结果验证质量")
    if metrics["approval_wait_ms"] > 120000:
        reasons.append("审批等待时间较长")
        suggestions.append("优化审批响应时间")
    if metrics["avg_duration_ms"] > 60000:
        reasons.append("平均执行耗时偏高")
        suggestions.append("拆解步骤并降低单步复杂度")
    if metrics["budget_exceeded_count"]:
        reasons.append("出现预算超限")
        suggestions.append("收紧工作流预算")
    return score, reasons, suggestions, [f"{k}:{v}" for k, v in dimension_scores.items()]


def _risk_from_metrics(metrics: dict[str, Any], base_score: int = 0) -> tuple[int, list[str], list[str], list[str]]:
    score = base_score
    reasons: list[str] = []
    suggestions: list[str] = []
    dimensions = {
        "失败率": min(30, metrics["single_step_failure_rate"] // 2),
        "验证失败": min(25, metrics["verification_fail_count"] * 12),
        "敏感拦截": min(30, metrics["sensitive_block_count"] * 20),
        "预算超限": min(20, metrics["budget_exceeded_count"] * 20),
        "接管次数": min(15, metrics["takeover_count"] * 10),
        "紧急停止": min(30, metrics["emergency_stop_count"] * 30),
        "耗时": min(15, metrics["avg_duration_ms"] // 5000),
    }
    score += sum(dimensions.values())
    if metrics["failure_count"]:
        reasons.append(f"失败步骤 {metrics['failure_count']} 个")
    if metrics["verification_fail_count"]:
        reasons.append(f"验证失败 {metrics['verification_fail_count']} 次")
    if metrics["sensitive_block_count"]:
        reasons.append("出现敏感拦截")
    if metrics["budget_exceeded_count"]:
        reasons.append("预算超限")
    if metrics["takeover_count"]:
        reasons.append("出现人工接管")
    if metrics["emergency_stop_count"]:
        reasons.append("发生紧急停止")
    if score >= 90:
        suggestions.append("终止当前执行并进行人工复核")
    elif score >= 70:
        suggestions.append("增加关键节点审批并缩短执行范围")
    elif score >= 40:
        suggestions.append("保持监控并关注异常趋势")
    else:
        suggestions.append("风险较低，维持现有策略")
    return min(score, 100), reasons, suggestions, [f"{k}:{v}" for k, v in dimensions.items()]


def _score_row_update(db: Session, model, key_fields: dict[str, Any], values: dict[str, Any]):
    query = db.query(model)
    for key, value in key_fields.items():
        query = query.filter(getattr(model, key) == value)
    row = query.first()
    if row is None:
        row = model(**key_fields, **values)
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return row


def collect_quality_scores(db: Session) -> list[ExecutionQualityScore]:
    rows: list[ExecutionQualityScore] = []
    for workflow in db.query(ComputerWorkflow).order_by(ComputerWorkflow.created_at.asc()).all():
        metrics = _workflow_execution_metrics(db, workflow)
        score, reasons, suggestions, dimension_pairs = _quality_from_metrics(metrics)
        row = _score_row_update(
            db,
            ExecutionQualityScore,
            {"scope_type": "workflow", "scope_id": workflow.workflow_id},
            {
                "score_id": uuid.uuid4().hex if not db.query(ExecutionQualityScore).filter(ExecutionQualityScore.scope_type == "workflow", ExecutionQualityScore.scope_id == workflow.workflow_id).first() else db.query(ExecutionQualityScore).filter(ExecutionQualityScore.scope_type == "workflow", ExecutionQualityScore.scope_id == workflow.workflow_id).first().score_id,
                "execution_id": workflow.workflow_id,
                "task_id": workflow.task_id,
                "employee_id": workflow.employee_id,
                "skill_id": workflow.skill_id,
                "workflow_id": workflow.workflow_id,
                "session_id": workflow.session_id,
                "score": score,
                "grade": _human_grade_from_score(score),
                "dimension_scores_json": _json_dumps(dimension_pairs),
                "deduction_reasons_json": _json_dumps(reasons),
                "improvement_suggestions_json": _json_dumps(suggestions),
                "explanation": "；".join(reasons) if reasons else "执行质量正常",
                "trace_id": workflow.trace_id,
            },
        )
        rows.append(row)

    for session in db.query(ComputerSession).order_by(ComputerSession.created_at.asc()).all():
        metrics = _session_execution_metrics(db, session)
        score, reasons, suggestions, dimension_pairs = _quality_from_metrics(metrics)
        row = _score_row_update(
            db,
            ExecutionQualityScore,
            {"scope_type": "session", "scope_id": session.session_id},
            {
                "score_id": uuid.uuid4().hex if not db.query(ExecutionQualityScore).filter(ExecutionQualityScore.scope_type == "session", ExecutionQualityScore.scope_id == session.session_id).first() else db.query(ExecutionQualityScore).filter(ExecutionQualityScore.scope_type == "session", ExecutionQualityScore.scope_id == session.session_id).first().score_id,
                "execution_id": str(session.execution_id or session.session_id),
                "task_id": session.task_id,
                "employee_id": session.employee_id,
                "skill_id": session.skill_id,
                "workflow_id": None,
                "session_id": session.session_id,
                "score": score,
                "grade": _human_grade_from_score(score),
                "dimension_scores_json": _json_dumps(dimension_pairs),
                "deduction_reasons_json": _json_dumps(reasons),
                "improvement_suggestions_json": _json_dumps(suggestions),
                "explanation": "；".join(reasons) if reasons else "执行质量正常",
                "trace_id": session.trace_id,
            },
        )
        rows.append(row)

    db.flush()
    return rows


def collect_risk_scores(db: Session) -> list[ExecutionRiskScore]:
    rows: list[ExecutionRiskScore] = []
    for workflow in db.query(ComputerWorkflow).order_by(ComputerWorkflow.created_at.asc()).all():
        metrics = _workflow_execution_metrics(db, workflow)
        base = 10
        if workflow.risk_level == "中低风险":
            base += 10
        elif workflow.risk_level == "中风险":
            base += 20
        elif workflow.risk_level == "高风险":
            base += 35
        elif workflow.risk_level == "极高风险":
            base += 50
        score, reasons, suggestions, dimension_pairs = _risk_from_metrics(metrics, base)
        row = _score_row_update(
            db,
            ExecutionRiskScore,
            {"scope_type": "workflow", "scope_id": workflow.workflow_id},
            {
                "score_id": uuid.uuid4().hex if not db.query(ExecutionRiskScore).filter(ExecutionRiskScore.scope_type == "workflow", ExecutionRiskScore.scope_id == workflow.workflow_id).first() else db.query(ExecutionRiskScore).filter(ExecutionRiskScore.scope_type == "workflow", ExecutionRiskScore.scope_id == workflow.workflow_id).first().score_id,
                "execution_id": workflow.workflow_id,
                "task_id": workflow.task_id,
                "employee_id": workflow.employee_id,
                "skill_id": workflow.skill_id,
                "workflow_id": workflow.workflow_id,
                "session_id": workflow.session_id,
                "score": score,
                "grade": _risk_grade_from_score(score),
                "dimension_scores_json": _json_dumps(dimension_pairs),
                "deduction_reasons_json": _json_dumps(reasons),
                "improvement_suggestions_json": _json_dumps(suggestions),
                "explanation": "；".join(reasons) if reasons else "风险正常",
                "trace_id": workflow.trace_id,
            },
        )
        rows.append(row)

    for session in db.query(ComputerSession).order_by(ComputerSession.created_at.asc()).all():
        metrics = _session_execution_metrics(db, session)
        base = 10
        if session.risk_level == "中低风险":
            base += 10
        elif session.risk_level == "中风险":
            base += 20
        elif session.risk_level == "高风险":
            base += 35
        elif session.risk_level == "极高风险":
            base += 50
        score, reasons, suggestions, dimension_pairs = _risk_from_metrics(metrics, base)
        row = _score_row_update(
            db,
            ExecutionRiskScore,
            {"scope_type": "session", "scope_id": session.session_id},
            {
                "score_id": uuid.uuid4().hex if not db.query(ExecutionRiskScore).filter(ExecutionRiskScore.scope_type == "session", ExecutionRiskScore.scope_id == session.session_id).first() else db.query(ExecutionRiskScore).filter(ExecutionRiskScore.scope_type == "session", ExecutionRiskScore.scope_id == session.session_id).first().score_id,
                "execution_id": str(session.execution_id or session.session_id),
                "task_id": session.task_id,
                "employee_id": session.employee_id,
                "skill_id": session.skill_id,
                "workflow_id": None,
                "session_id": session.session_id,
                "score": score,
                "grade": _risk_grade_from_score(score),
                "dimension_scores_json": _json_dumps(dimension_pairs),
                "deduction_reasons_json": _json_dumps(reasons),
                "improvement_suggestions_json": _json_dumps(suggestions),
                "explanation": "；".join(reasons) if reasons else "风险正常",
                "trace_id": session.trace_id,
            },
        )
        rows.append(row)

    db.flush()
    return rows


def _device_health_from_metric(metric: DeviceRuntimeMetric | None) -> tuple[int, str, dict[str, int], list[str]]:
    if metric is None:
        return 100, "健康", {"在线稳定性": 100, "心跳成功率": 100, "CPU/内存": 100, "磁盘空间": 100, "网络稳定性": 100, "认证失败": 100, "安全事件": 100, "会话失败": 100, "本地紧急停止": 100, "最近更新时间": 100}, ["暂无设备指标"]
    dimensions = {
        "在线稳定性": 100 if metric.online_status not in {"离线", "已禁用", "已撤销"} else 20,
        "心跳成功率": max(0, 100 - min(80, _seconds_since(metric.last_heartbeat_at) // 10 if metric.last_heartbeat_at else 80)),
        "CPU/内存": max(0, 100 - int((metric.cpu_usage_percent or 0) * 0.5) - int((metric.memory_usage_percent or 0) * 0.5)),
        "磁盘空间": 100 if (metric.disk_free_bytes or 0) > 100_000_000 else 50,
        "网络稳定性": max(0, 100 - int(metric.network_latency_ms or 0) // 10 - int(metric.request_failure_rate or 0)),
        "认证失败": max(0, 100 - (metric.auth_failure_count * 25)),
        "安全事件": max(0, 100 - (metric.recent_error_count * 10)),
        "会话失败": max(0, 100 - (metric.current_session_count * 2)),
        "本地紧急停止": max(0, 100 - (metric.emergency_stop_count * 40)),
        "最近更新时间": 100,
    }
    score = int(round(sum(dimensions.values()) / len(dimensions)))
    score = max(0, min(score, 100))
    reasons = []
    if metric.online_status in {"离线", "已禁用", "已撤销"}:
        reasons.append("设备当前不在线或已被禁用")
    if metric.auth_failure_count:
        reasons.append("存在认证失败")
    if metric.replay_block_count:
        reasons.append("存在重放拦截")
    if metric.emergency_stop_count:
        reasons.append("存在本地紧急停止")
    return score, _device_health_grade(score), dimensions, reasons or ["设备状态正常"]


def collect_device_health_scores(db: Session) -> list[DeviceHealthScore]:
    rows: list[DeviceHealthScore] = []
    for metric in db.query(DeviceRuntimeMetric).order_by(DeviceRuntimeMetric.captured_at.desc()).all():
        score, grade, dimensions, reasons = _device_health_from_metric(metric)
        row = db.query(DeviceHealthScore).filter(DeviceHealthScore.device_id == metric.device_id).one_or_none()
        if row is None:
            row = DeviceHealthScore(
                health_score_id=uuid.uuid4().hex,
                device_id=metric.device_id or "",
                score=score,
                grade=grade,
                dimension_scores_json=_json_dumps(dimensions),
                reason_summary_json=_json_dumps(reasons),
                computed_at=utcnow(),
                trace_id=metric.trace_id,
            )
            db.add(row)
        else:
            row.score = score
            row.grade = grade
            row.dimension_scores_json = _json_dumps(dimensions)
            row.reason_summary_json = _json_dumps(reasons)
            row.computed_at = utcnow()
            row.trace_id = metric.trace_id
        rows.append(row)
    db.flush()
    return rows


def collect_employee_metrics(db: Session) -> list[EmployeeExecutionMetric]:
    rows: list[EmployeeExecutionMetric] = []
    employees = db.query(AiEmployee).all()
    for employee in employees:
        workflows = db.query(ComputerWorkflow).filter(ComputerWorkflow.employee_id == employee.id).all()
        sessions = db.query(ComputerSession).filter(ComputerSession.employee_id == employee.id).all()
        qualities = db.query(ExecutionQualityScore).filter(ExecutionQualityScore.employee_id == employee.id).all()
        risks = db.query(ExecutionRiskScore).filter(ExecutionRiskScore.employee_id == employee.id).all()
        total_tasks = len(workflows) + len(sessions)
        success_count = sum(1 for workflow in workflows if workflow.status == "已完成") + sum(1 for session in sessions if session.status == "已完成")
        success_rate = int(round((success_count / total_tasks) * 100)) if total_tasks else 0
        avg_quality = int(round(sum(row.score for row in qualities) / len(qualities))) if qualities else 0
        avg_risk = int(round(sum(row.score for row in risks) / len(risks))) if risks else 0
        durations = [
            max(0, int((workflow.finished_at - workflow.started_at).total_seconds() * 1000))
            for workflow in workflows
            if workflow.started_at and workflow.finished_at
        ] + [
            max(0, int((session.ended_at - session.started_at).total_seconds() * 1000))
            for session in sessions
            if session.started_at and session.ended_at
        ]
        avg_duration_ms = int(round(sum(durations) / len(durations))) if durations else 0
        verification_fail_rate = 0
        takeover_rate = int(round((sum(1 for session in sessions if session.takeover_status in {"人工接管", "等待人工接管"}) / total_tasks) * 100)) if total_tasks else 0
        security_incident_count = _query_count(db.query(SecurityIncident).filter(SecurityIncident.employee_id == employee.id))
        budget_exceeded_count = sum(1 for workflow in workflows if workflow.status == "已超时")
        canceled_count = sum(1 for workflow in workflows if workflow.status == "已取消") + sum(1 for session in sessions if session.status == "已取消")
        consecutive_failures = sum(1 for workflow in workflows if workflow.status == "已失败")
        last_execution_at = max(
            [workflow.finished_at for workflow in workflows if workflow.finished_at] +
            [session.ended_at for session in sessions if session.ended_at] or [None]
        )
        row = db.query(EmployeeExecutionMetric).filter(EmployeeExecutionMetric.employee_code == employee.employee_code).one_or_none()
        if row is None:
            row = EmployeeExecutionMetric(
                metric_id=uuid.uuid4().hex,
                employee_code=employee.employee_code,
                employee_name=employee.employee_name,
                total_tasks=total_tasks,
                success_count=success_count,
                success_rate=success_rate,
                avg_quality_score=avg_quality,
                avg_risk_score=avg_risk,
                avg_duration_ms=avg_duration_ms,
                verification_fail_rate=verification_fail_rate,
                takeover_rate=takeover_rate,
                security_incident_count=security_incident_count,
                budget_exceeded_count=budget_exceeded_count,
                canceled_count=canceled_count,
                consecutive_failures=consecutive_failures,
                last_execution_at=last_execution_at,
                trace_id=employee.employee_code,
            )
            db.add(row)
        else:
            row.employee_name = employee.employee_name
            row.total_tasks = total_tasks
            row.success_count = success_count
            row.success_rate = success_rate
            row.avg_quality_score = avg_quality
            row.avg_risk_score = avg_risk
            row.avg_duration_ms = avg_duration_ms
            row.verification_fail_rate = verification_fail_rate
            row.takeover_rate = takeover_rate
            row.security_incident_count = security_incident_count
            row.budget_exceeded_count = budget_exceeded_count
            row.canceled_count = canceled_count
            row.consecutive_failures = consecutive_failures
            row.last_execution_at = last_execution_at
        rows.append(row)
    db.flush()
    return rows


def _incident_key(code: str) -> str:
    return code.lower().replace(" ", "_")


def _get_or_create_incident(db: Session, *, incident_code: str, incident_type: str, severity: str, title: str, description: str, device_id: str | None = None, employee_id: int | None = None, task_id: int | None = None, execution_id: str | None = None, session_id: str | None = None, workflow_id: str | None = None, action_id: str | None = None, detected_by: str = "rule", evidence_references: list[str] | None = None, risk_score: int = 0, automatic_action: str | None = None, trace_id: str | None = None) -> SecurityIncident:
    incident = db.query(SecurityIncident).filter(SecurityIncident.incident_code == incident_code).one_or_none()
    if incident is None:
        incident = SecurityIncident(
            incident_id=uuid.uuid4().hex,
            incident_code=incident_code,
            incident_type=incident_type,
            severity=severity,
            status="新发现",
            device_id=device_id,
            employee_id=employee_id,
            task_id=task_id,
            execution_id=execution_id,
            session_id=session_id,
            workflow_id=workflow_id,
            action_id=action_id,
            title=title,
            description=description,
            detected_by=detected_by,
            evidence_references_json=_json_dumps(evidence_references or []),
            risk_score=risk_score,
            automatic_action=automatic_action,
            trace_id=trace_id,
        )
        db.add(incident)
    else:
        incident.title = title
        incident.description = description
        incident.device_id = device_id or incident.device_id
        incident.employee_id = employee_id or incident.employee_id
        incident.task_id = task_id or incident.task_id
        incident.execution_id = execution_id or incident.execution_id
        incident.session_id = session_id or incident.session_id
        incident.workflow_id = workflow_id or incident.workflow_id
        incident.action_id = action_id or incident.action_id
        incident.detected_by = detected_by
        incident.evidence_references_json = _json_dumps(evidence_references or _json_loads(incident.evidence_references_json, []))
        incident.risk_score = risk_score
        incident.automatic_action = automatic_action
        incident.trace_id = trace_id or incident.trace_id
        if incident.status in {"已解决", "已关闭"}:
            incident.status = "待确认"
    return incident


def _rule_matches(rule: AlertRule, value: Any) -> bool:
    try:
        threshold = int(rule.threshold)
    except Exception:
        threshold = rule.threshold
    if rule.condition == "equals":
        return str(value) == str(threshold)
    if rule.condition == "gte":
        return int(value) >= int(threshold)
    if rule.condition == "lte":
        return int(value) <= int(threshold)
    if rule.condition == "contains":
        return str(threshold) in str(value)
    return False


def _metric_lookup(overview: dict[str, Any], metric_name: str) -> Any:
    return overview.get(metric_name)


def evaluate_alerts_and_anomalies(db: Session) -> dict[str, list[Any]]:
    created_alerts: list[AlertEvent] = []
    created_incidents: list[SecurityIncident] = []
    created_anomalies: list[AnomalyEvent] = []

    overview = build_overview(db)
    rules = db.query(AlertRule).filter(AlertRule.enabled.is_(True)).all()
    for rule in rules:
        value = _metric_lookup(overview, rule.metric_name)
        if value is None:
            continue
        if not _rule_matches(rule, value):
            continue
        incident_code = f"ALERT_{rule.rule_code.upper()}"
        incident = _get_or_create_incident(
            db,
            incident_code=incident_code,
            incident_type="告警规则触发",
            severity=rule.severity,
            title=f"{rule.chinese_name}触发",
            description=f"指标 {rule.metric_name} 命中规则 {rule.condition} {rule.threshold}",
            evidence_references=[f"metric:{rule.metric_name}"],
            risk_score=int(overview.get("max_risk_score") or 0),
            automatic_action=rule.action,
            trace_id="observability-alert",
        )
        alert = AlertEvent(
            alert_event_id=uuid.uuid4().hex,
            rule_id=rule.rule_id,
            incident_id=incident.incident_id,
            status="已触发",
            title=f"{rule.chinese_name}触发",
            message=f"指标 {rule.metric_name} 命中规则 {rule.condition} {rule.threshold}",
            severity=rule.severity,
            action=rule.action,
            trace_id="observability-alert",
        )
        db.add(alert)
        created_alerts.append(alert)
        created_incidents.append(incident)
        anomaly = AnomalyEvent(
            anomaly_id=uuid.uuid4().hex,
            metric_name=rule.metric_name,
            entity_type="system",
            entity_id=rule.rule_code,
            rule_code=rule.rule_code,
            severity=rule.severity,
            status="新发现",
            title=f"{rule.chinese_name}异常",
            description=f"规则 {rule.rule_code} 已触发",
            trace_id="observability-alert",
            evidence_references_json=_json_dumps([f"alert:{rule.rule_code}"]),
        )
        db.add(anomaly)
        created_anomalies.append(anomaly)
    db.flush()
    return {"alerts": created_alerts, "incidents": created_incidents, "anomalies": created_anomalies}


def maybe_auto_pause(db: Session, overview: dict[str, Any] | None = None) -> list[SecurityIncident]:
    settings = get_settings()
    if not settings.AUTOMATIC_PAUSE_ENABLED:
        return []
    overview = overview or build_overview(db)
    incidents: list[SecurityIncident] = []
    if int(overview.get("max_risk_score") or 0) >= 90:
        for workflow in db.query(ComputerWorkflow).filter(ComputerWorkflow.status.in_(["执行中", "等待关键节点确认"])).all():
            workflow.status = "已暂停"
            workflow.stop_reason = "高风险自动暂停"
        for session in db.query(ComputerSession).filter(ComputerSession.status.in_(["执行中", "等待接管", "已创建"])).all():
            session.status = "已暂停"
            session.takeover_status = "等待人工接管"
        incident = _get_or_create_incident(
            db,
            incident_code="AUTO_PAUSE_RISK_90",
            incident_type="高风险自动暂停",
            severity="高",
            title="极高风险自动熔断",
            description="风险分数达到极高，已自动暂停相关会话与工作流。",
            evidence_references=["metric:max_risk_score"],
            risk_score=int(overview.get("max_risk_score") or 0),
            automatic_action="暂停会话/工作流",
            trace_id="observability-auto-pause",
        )
        incidents.append(incident)
    elif int(overview.get("max_risk_score") or 0) >= 70:
        for workflow in db.query(ComputerWorkflow).filter(ComputerWorkflow.status.in_(["执行中", "等待关键节点确认"])).all():
            workflow.status = "已暂停"
            workflow.stop_reason = "高风险自动暂停"
        incident = _get_or_create_incident(
            db,
            incident_code="AUTO_PAUSE_RISK_70",
            incident_type="高风险自动暂停",
            severity="中",
            title="高风险自动暂停",
            description="风险分数达到高，已自动暂停当前工作流。",
            evidence_references=["metric:max_risk_score"],
            risk_score=int(overview.get("max_risk_score") or 0),
            automatic_action="暂停工作流",
            trace_id="observability-auto-pause",
        )
        incidents.append(incident)
    db.flush()
    return incidents


def collect_all(db: Session) -> dict[str, Any]:
    ensure_default_alert_rules(db)
    device_metrics = collect_device_metrics(db)
    execution_metrics = collect_execution_metrics(db)
    quality_scores = collect_quality_scores(db)
    risk_scores = collect_risk_scores(db)
    device_health_scores = collect_device_health_scores(db)
    employee_metrics = collect_employee_metrics(db)
    replay_indexes = refresh_execution_replay_indexes(db)
    alert_pack = evaluate_alerts_and_anomalies(db)
    incidents = alert_pack["incidents"]
    maybe_auto_pause(db, build_overview(db))
    db.commit()
    return {
        "device_metrics": device_metrics,
        "execution_metrics": execution_metrics,
        "quality_scores": quality_scores,
        "risk_scores": risk_scores,
        "device_health_scores": device_health_scores,
        "employee_metrics": employee_metrics,
        "replay_indexes": replay_indexes,
        "alerts": alert_pack["alerts"],
        "incidents": incidents,
    }


def refresh_execution_replay_indexes(db: Session) -> list[ExecutionReplayIndex]:
    rows: list[ExecutionReplayIndex] = []
    for workflow in db.query(ComputerWorkflow).order_by(ComputerWorkflow.created_at.asc()).all():
        steps = db.query(ComputerWorkflowStep).filter(ComputerWorkflowStep.workflow_id == workflow.workflow_id).order_by(ComputerWorkflowStep.sequence_number.asc()).all()
        checkpoints = db.query(ComputerWorkflowCheckpoint).filter(ComputerWorkflowCheckpoint.workflow_id == workflow.workflow_id).all()
        verifications = db.query(ComputerWorkflowVerification).filter(ComputerWorkflowVerification.workflow_id == workflow.workflow_id).all()
        recoveries = db.query(ComputerWorkflowRecovery).filter(ComputerWorkflowRecovery.workflow_id == workflow.workflow_id).all()
        summary = {
            "workflow": {
                "workflow_id": workflow.workflow_id,
                "goal": workflow.goal,
                "status": workflow.status,
                "risk_level": workflow.risk_level,
                "approval_status": workflow.approval_status,
            },
            "steps": [
                {
                    "step_id": row.step_id,
                    "sequence_number": row.sequence_number,
                    "action_type": row.action_type,
                    "status": row.status,
                    "risk_level": row.risk_level,
                }
                for row in steps
            ],
            "approvals": [
                {
                    "checkpoint_id": row.checkpoint_id,
                    "approval_status": row.approval_status,
                    "checkpoint_type": row.checkpoint_type,
                }
                for row in checkpoints
            ],
            "verifications": [
                {"verification_id": row.verification_id, "status": row.verification_status}
                for row in verifications
            ],
            "recoveries": [
                {"recovery_id": row.recovery_id, "status": row.status}
                for row in recoveries
            ],
        }
        row = db.query(ExecutionReplayIndex).filter(ExecutionReplayIndex.workflow_id == workflow.workflow_id).one_or_none()
        if row is None:
            row = ExecutionReplayIndex(
                replay_id=uuid.uuid4().hex,
                workflow_id=workflow.workflow_id,
                task_id=workflow.task_id,
                execution_id=workflow.session_id,
                session_id=workflow.session_id,
                step_count=len(steps),
                goal=workflow.goal,
                summary_json=_json_dumps(summary),
                available=True,
                trace_id=workflow.trace_id,
            )
            db.add(row)
        else:
            row.task_id = workflow.task_id
            row.execution_id = workflow.session_id
            row.session_id = workflow.session_id
            row.step_count = len(steps)
            row.goal = workflow.goal
            row.summary_json = _json_dumps(summary)
            row.available = True
            row.trace_id = workflow.trace_id
        rows.append(row)
    db.flush()
    return rows


def build_overview(db: Session) -> dict[str, Any]:
    devices = db.query(Device).all()
    workflows = db.query(ComputerWorkflow).all()
    sessions = db.query(ComputerSession).all()
    execution_scores = db.query(ExecutionQualityScore).all()
    risk_scores = db.query(ExecutionRiskScore).all()
    incidents = db.query(SecurityIncident).all()
    breakers = db.query(CircuitBreaker).all()
    alerts = db.query(AlertEvent).all()
    online_devices = sum(1 for device in devices if device.status not in {"离线", "已禁用", "已撤销"} and device.enabled)
    running_workflows = sum(1 for workflow in workflows if workflow.status in {"执行中", "已批准", "等待关键节点确认", "已暂停"})
    today = utcnow().date()
    today_executions = sum(1 for workflow in workflows if workflow.created_at and workflow.created_at.date() == today)
    today_success = sum(1 for workflow in workflows if workflow.finished_at and workflow.finished_at.date() == today and workflow.status == "已完成")
    today_success_rate = int(round((today_success / today_executions) * 100)) if today_executions else 0
    avg_quality = int(round(sum(row.score for row in execution_scores) / len(execution_scores))) if execution_scores else 0
    current_high_risk = sum(1 for row in risk_scores if row.score >= 70)
    unresolved_incidents = sum(1 for incident in incidents if incident.status not in {"已解决", "已关闭"})
    triggered_breakers = sum(1 for breaker in breakers if breaker.status in {"已熔断", "等待恢复"})
    latest_alerts = [
        {
            "alert_event_id": row.alert_event_id,
            "title": row.title,
            "severity": row.severity,
            "status": row.status,
            "triggered_at": row.triggered_at.isoformat() if row.triggered_at else None,
        }
        for row in db.query(AlertEvent).order_by(AlertEvent.triggered_at.desc()).limit(5).all()
    ]
    return {
        "online_test_devices": online_devices,
        "running_workflows": running_workflows,
        "today_executions": today_executions,
        "today_success_rate": today_success_rate,
        "average_quality_score": avg_quality,
        "current_high_risk": current_high_risk,
        "unhandled_security_incidents": unresolved_incidents,
        "triggered_breakers": triggered_breakers,
        "latest_alerts": latest_alerts,
        "device_count": len(devices),
        "session_count": len(sessions),
        "workflow_count": len(workflows),
        "max_risk_score": max([row.score for row in risk_scores], default=0),
        "max_quality_score": max([row.score for row in execution_scores], default=0),
        "average_risk_score": int(round(sum(row.score for row in risk_scores) / len(risk_scores))) if risk_scores else 0,
        "incident_count": len(incidents),
    }


def _metric_view(metric) -> dict[str, Any]:
    return {
        "metric_id": metric.metric_id,
        "scope_type": getattr(metric, "scope_type", "device"),
        "scope_id": getattr(metric, "scope_id", getattr(metric, "device_id", "")),
        "captured_at": metric.captured_at.isoformat() if getattr(metric, "captured_at", None) else None,
    }


def get_observability_overview(db: Session) -> dict[str, Any]:
    return build_overview(db)


def list_devices_view(db: Session, device_id: str | None = None) -> list[dict[str, Any]]:
    collect_device_metrics(db, device_id=device_id)
    collect_device_health_scores(db)
    devices = db.query(Device).order_by(Device.created_at.asc()).all()
    payload: list[dict[str, Any]] = []
    for device in devices:
        metric = _latest_runtime_metric(db, device.device_id)
        health = db.query(DeviceHealthScore).filter(DeviceHealthScore.device_id == device.device_id).one_or_none()
        payload.append(
            {
                "device_id": device.device_id,
                "device_code": device.device_code,
                "chinese_name": device.chinese_name,
                "device_type": device.device_type,
                "operating_system": device.operating_system,
                "architecture": device.architecture,
                "agent_version": device.agent_version,
                "status": device.status,
                "trust_level": device.trust_level,
                "environment_type": device.environment_type,
                "online_status": metric.online_status if metric else device.status,
                "health_score": health.score if health else (metric and 100) or 100,
                "health_grade": health.grade if health else "健康",
                "cpu_usage_percent": metric.cpu_usage_percent if metric else 0,
                "memory_usage_percent": metric.memory_usage_percent if metric else 0,
                "disk_free_bytes": metric.disk_free_bytes if metric else 0,
                "network_latency_ms": metric.network_latency_ms if metric else 0,
                "current_session_count": metric.current_session_count if metric else 0,
                "current_workflow_count": metric.current_workflow_count if metric else 0,
                "recent_error_count": metric.recent_error_count if metric else 0,
                "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
                "last_screenshot_at": metric.recent_screenshot_at.isoformat() if metric and metric.recent_screenshot_at else None,
                "last_ip_hash": device.last_ip_hash,
                "trace_id": device.certificate_fingerprint,
            }
        )
    return payload if not device_id else [row for row in payload if row["device_id"] == device_id]


def get_device_view(db: Session, device_id: str) -> dict[str, Any]:
    device = db.get(Device, device_id)
    if not device:
        raise ObservabilityNotFoundError("设备不存在")
    metric = _latest_runtime_metric(db, device.device_id)
    health = db.query(DeviceHealthScore).filter(DeviceHealthScore.device_id == device.device_id).one_or_none()
    return {
        "device": {
            "device_id": device.device_id,
            "device_code": device.device_code,
            "chinese_name": device.chinese_name,
            "device_type": device.device_type,
            "operating_system": device.operating_system,
            "architecture": device.architecture,
            "agent_version": device.agent_version,
            "status": device.status,
            "trust_level": device.trust_level,
            "environment_type": device.environment_type,
            "owner_id": device.owner_id,
            "registered_by": device.registered_by,
            "approved_by": device.approved_by,
            "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
            "last_ip_hash": device.last_ip_hash,
            "certificate_fingerprint": device.certificate_fingerprint,
            "capabilities": _json_loads(device.capabilities_json, []),
            "enabled": device.enabled,
            "revoked_at": device.revoked_at.isoformat() if device.revoked_at else None,
            "created_at": device.created_at.isoformat() if device.created_at else None,
            "updated_at": device.updated_at.isoformat() if device.updated_at else None,
        },
        "runtime_metric": _serialize_metric(metric),
        "health_score": _serialize_health_score(health),
        "observations": [
            {
                "observation_id": row.observation_id,
                "status": row.status,
                "screenshot_count": row.screenshot_count,
                "max_screenshots": row.max_screenshots,
                "trace_id": row.trace_id,
            }
            for row in db.query(DeviceObservationSession).filter(DeviceObservationSession.device_id == device_id).order_by(DeviceObservationSession.created_at.desc()).all()
        ],
        "security_events": [
            {
                "security_event_id": row.security_event_id,
                "event_code": row.event_code,
                "risk_level": row.risk_level,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in db.query(DeviceSecurityEvent).filter(DeviceSecurityEvent.device_id == device_id).order_by(DeviceSecurityEvent.created_at.desc()).all()
        ],
    }


def _serialize_metric(metric: DeviceRuntimeMetric | None) -> dict[str, Any] | None:
    if metric is None:
        return None
    return {
        "metric_id": metric.metric_id,
        "device_id": metric.device_id,
        "online_status": metric.online_status,
        "last_heartbeat_at": metric.last_heartbeat_at.isoformat() if metric.last_heartbeat_at else None,
        "agent_version": metric.agent_version,
        "operating_system": metric.operating_system,
        "cpu_usage_percent": metric.cpu_usage_percent,
        "memory_usage_percent": metric.memory_usage_percent,
        "disk_free_bytes": metric.disk_free_bytes,
        "agent_process_status": metric.agent_process_status,
        "current_session_count": metric.current_session_count,
        "current_workflow_count": metric.current_workflow_count,
        "recent_error_count": metric.recent_error_count,
        "recent_screenshot_at": metric.recent_screenshot_at.isoformat() if metric.recent_screenshot_at else None,
        "network_latency_ms": metric.network_latency_ms,
        "request_failure_rate": metric.request_failure_rate,
        "auth_failure_count": metric.auth_failure_count,
        "replay_block_count": metric.replay_block_count,
        "emergency_stop_count": metric.emergency_stop_count,
        "trace_id": metric.trace_id,
        "captured_at": metric.captured_at.isoformat() if metric.captured_at else None,
    }


def _serialize_quality_score(row: ExecutionQualityScore) -> dict[str, Any]:
    return {
        "score_id": row.score_id,
        "scope_type": row.scope_type,
        "scope_id": row.scope_id,
        "execution_id": row.execution_id,
        "task_id": row.task_id,
        "employee_id": row.employee_id,
        "skill_id": row.skill_id,
        "workflow_id": row.workflow_id,
        "session_id": row.session_id,
        "score": row.score,
        "grade": row.grade,
        "dimension_scores": _json_loads(row.dimension_scores_json, {}),
        "deduction_reasons": _json_loads(row.deduction_reasons_json, []),
        "improvement_suggestions": _json_loads(row.improvement_suggestions_json, []),
        "explanation": row.explanation,
        "trace_id": row.trace_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if getattr(row, "updated_at", None) else None,
    }


def _serialize_risk_score(row: ExecutionRiskScore) -> dict[str, Any]:
    return {
        "score_id": row.score_id,
        "scope_type": row.scope_type,
        "scope_id": row.scope_id,
        "execution_id": row.execution_id,
        "task_id": row.task_id,
        "employee_id": row.employee_id,
        "skill_id": row.skill_id,
        "workflow_id": row.workflow_id,
        "session_id": row.session_id,
        "score": row.score,
        "grade": row.grade,
        "dimension_scores": _json_loads(row.dimension_scores_json, {}),
        "deduction_reasons": _json_loads(row.deduction_reasons_json, []),
        "improvement_suggestions": _json_loads(row.improvement_suggestions_json, []),
        "explanation": row.explanation,
        "trace_id": row.trace_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if getattr(row, "updated_at", None) else None,
    }


def _serialize_health_score(row: DeviceHealthScore | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "health_score_id": row.health_score_id,
        "device_id": row.device_id,
        "score": row.score,
        "grade": row.grade,
        "dimension_scores": _json_loads(row.dimension_scores_json, {}),
        "reason_summary": _json_loads(row.reason_summary_json, []),
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        "trace_id": row.trace_id,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_executions_view(db: Session, execution_id: str | None = None) -> list[dict[str, Any]]:
    collect_execution_metrics(db)
    collect_quality_scores(db)
    collect_risk_scores(db)
    if execution_id:
        rows = db.query(ExecutionRuntimeMetric).filter(ExecutionRuntimeMetric.execution_id == execution_id).order_by(ExecutionRuntimeMetric.created_at.desc()).all()
    else:
        rows = db.query(ExecutionRuntimeMetric).order_by(ExecutionRuntimeMetric.created_at.desc()).all()
    return [_serialize_runtime_metric(row) for row in rows]


def _serialize_runtime_metric(row: ExecutionRuntimeMetric) -> dict[str, Any]:
    return {
        "metric_id": row.metric_id,
        "scope_type": row.scope_type,
        "scope_id": row.scope_id,
        "execution_id": row.execution_id,
        "task_id": row.task_id,
        "employee_id": row.employee_id,
        "skill_id": row.skill_id,
        "session_id": row.session_id,
        "workflow_id": row.workflow_id,
        "total_count": row.total_count,
        "success_count": row.success_count,
        "failure_count": row.failure_count,
        "canceled_count": row.canceled_count,
        "timeout_count": row.timeout_count,
        "avg_duration_ms": row.avg_duration_ms,
        "p50_duration_ms": row.p50_duration_ms,
        "p95_duration_ms": row.p95_duration_ms,
        "retry_count": row.retry_count,
        "approval_wait_ms": row.approval_wait_ms,
        "checkpoint_wait_ms": row.checkpoint_wait_ms,
        "verification_fail_count": row.verification_fail_count,
        "page_change_count": row.page_change_count,
        "window_change_count": row.window_change_count,
        "sensitive_block_count": row.sensitive_block_count,
        "emergency_stop_count": row.emergency_stop_count,
        "takeover_count": row.takeover_count,
        "budget_exceeded_count": row.budget_exceeded_count,
        "single_step_failure_rate": row.single_step_failure_rate,
        "workflow_completion_rate": row.workflow_completion_rate,
        "trace_id": row.trace_id,
        "captured_at": row.captured_at.isoformat() if row.captured_at else None,
    }


def get_execution_view(db: Session, execution_id: str) -> dict[str, Any]:
    metric = db.query(ExecutionRuntimeMetric).filter(ExecutionRuntimeMetric.execution_id == execution_id).order_by(ExecutionRuntimeMetric.created_at.desc()).first()
    if metric is None:
        collect_execution_metrics(db)
        metric = db.query(ExecutionRuntimeMetric).filter(ExecutionRuntimeMetric.execution_id == execution_id).order_by(ExecutionRuntimeMetric.created_at.desc()).first()
    if metric is None:
        raise ObservabilityNotFoundError("执行记录不存在")
    quality = db.query(ExecutionQualityScore).filter(ExecutionQualityScore.execution_id == execution_id).first()
    risk = db.query(ExecutionRiskScore).filter(ExecutionRiskScore.execution_id == execution_id).first()
    return {
        "execution": _serialize_runtime_metric(metric),
        "quality_score": _serialize_quality_score(quality) if quality else None,
        "risk_score": _serialize_risk_score(risk) if risk else None,
    }


def get_workflow_view(db: Session, workflow_id: str) -> dict[str, Any]:
    workflow = db.get(ComputerWorkflow, workflow_id)
    if not workflow:
        raise ObservabilityNotFoundError("工作流不存在")
    collect_execution_metrics(db)
    collect_quality_scores(db)
    collect_risk_scores(db)
    collect_device_metrics(db, device_id=workflow.device_id)
    collect_device_health_scores(db)
    replay = db.query(ExecutionReplayIndex).filter(ExecutionReplayIndex.workflow_id == workflow_id).first()
    if replay is None:
        refresh_execution_replay_indexes(db)
        replay = db.query(ExecutionReplayIndex).filter(ExecutionReplayIndex.workflow_id == workflow_id).first()
    return {
        "workflow": {
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
            "started_at": workflow.started_at.isoformat() if workflow.started_at else None,
            "expires_at": workflow.expires_at.isoformat() if workflow.expires_at else None,
            "finished_at": workflow.finished_at.isoformat() if workflow.finished_at else None,
            "stop_reason": workflow.stop_reason,
            "trace_id": workflow.trace_id,
        },
        "steps": [
            {
                "step_id": row.step_id,
                "sequence_number": row.sequence_number,
                "action_type": row.action_type,
                "target_application": row.target_application,
                "target_window": row.target_window,
                "target_control": row.target_control,
                "input_summary": row.input_summary,
                "expected_result": row.expected_result,
                "risk_level": row.risk_level,
                "approval_required": row.approval_required,
                "checkpoint_required": row.checkpoint_required,
                "status": row.status,
            }
            for row in db.query(ComputerWorkflowStep).filter(ComputerWorkflowStep.workflow_id == workflow_id).order_by(ComputerWorkflowStep.sequence_number.asc()).all()
        ],
        "approvals": [
            {
                "approval_id": row.checkpoint_id,
                "approval_scope": row.checkpoint_type,
                "approval_status": row.approval_status,
                "approved_by": row.approved_by,
                "approved_at": row.approved_at.isoformat() if row.approved_at else None,
                "reject_reason": row.reason,
                "trace_id": row.trace_id,
            }
            for row in db.query(ComputerWorkflowCheckpoint).filter(ComputerWorkflowCheckpoint.workflow_id == workflow_id).all()
        ],
        "replay_index": {
            "replay_id": replay.replay_id if replay else None,
            "available": replay.available if replay else False,
            "step_count": replay.step_count if replay else 0,
            "summary": _json_loads(replay.summary_json, {}) if replay else {},
        },
    }


def list_quality_scores_view(db: Session) -> list[dict[str, Any]]:
    collect_quality_scores(db)
    return [_serialize_quality_score(row) for row in db.query(ExecutionQualityScore).order_by(ExecutionQualityScore.created_at.desc()).all()]


def list_risk_scores_view(db: Session) -> list[dict[str, Any]]:
    collect_risk_scores(db)
    return [_serialize_risk_score(row) for row in db.query(ExecutionRiskScore).order_by(ExecutionRiskScore.created_at.desc()).all()]


def list_incidents_view(db: Session) -> list[dict[str, Any]]:
    return [serialize_incident(row) for row in db.query(SecurityIncident).order_by(SecurityIncident.detected_at.desc()).all()]


def get_incident_view(db: Session, incident_id: str) -> dict[str, Any]:
    incident = db.get(SecurityIncident, incident_id)
    if not incident:
        raise ObservabilityNotFoundError("安全事件不存在")
    return serialize_incident(incident)


def serialize_incident(incident: SecurityIncident) -> dict[str, Any]:
    return {
        "incident_id": incident.incident_id,
        "incident_code": incident.incident_code,
        "incident_type": incident.incident_type,
        "severity": incident.severity,
        "status": incident.status,
        "device_id": incident.device_id,
        "employee_id": incident.employee_id,
        "task_id": incident.task_id,
        "execution_id": incident.execution_id,
        "session_id": incident.session_id,
        "workflow_id": incident.workflow_id,
        "action_id": incident.action_id,
        "title": incident.title,
        "description": incident.description,
        "detected_at": incident.detected_at.isoformat() if incident.detected_at else None,
        "detected_by": incident.detected_by,
        "evidence_references": _json_loads(incident.evidence_references_json, []),
        "risk_score": incident.risk_score,
        "automatic_action": incident.automatic_action,
        "assigned_to": incident.assigned_to,
        "acknowledged_by": incident.acknowledged_by,
        "acknowledged_at": incident.acknowledged_at.isoformat() if incident.acknowledged_at else None,
        "resolved_by": incident.resolved_by,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        "resolution_summary": incident.resolution_summary,
        "trace_id": incident.trace_id,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
        "updated_at": incident.updated_at.isoformat() if incident.updated_at else None,
    }


def acknowledge_incident(db: Session, incident_id: str, *, acknowledged_by: str, comment: str | None = None) -> dict[str, Any]:
    incident = db.get(SecurityIncident, incident_id)
    if not incident:
        raise ObservabilityNotFoundError("安全事件不存在")
    incident.status = "处理中"
    incident.acknowledged_by = acknowledged_by
    incident.acknowledged_at = utcnow()
    if comment:
        incident.description = f"{incident.description or ''}\n处理备注：{comment}".strip()
    db.commit()
    db.refresh(incident)
    return serialize_incident(incident)


def resolve_incident(db: Session, incident_id: str, *, resolved_by: str, resolution_summary: str | None = None) -> dict[str, Any]:
    incident = db.get(SecurityIncident, incident_id)
    if not incident:
        raise ObservabilityNotFoundError("安全事件不存在")
    incident.status = "已解决"
    incident.resolved_by = resolved_by
    incident.resolved_at = utcnow()
    incident.resolution_summary = resolution_summary
    db.commit()
    db.refresh(incident)
    return serialize_incident(incident)


def list_alert_rules_view(db: Session) -> list[dict[str, Any]]:
    ensure_default_alert_rules(db)
    db.commit()
    rows = db.query(AlertRule).order_by(AlertRule.updated_at.desc()).all()
    return [
        {
            "rule_id": row.rule_id,
            "中文名称": row.chinese_name,
            "rule_code": row.rule_code,
            "metric_name": row.metric_name,
            "condition": row.condition,
            "threshold": row.threshold,
            "duration_seconds": row.duration_seconds,
            "severity": row.severity,
            "action": row.action,
            "enabled": row.enabled,
            "environment": row.environment,
            "created_by": row.created_by,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


def create_alert_rule_view(db: Session, payload: dict[str, Any], created_by: int | None = None) -> dict[str, Any]:
    rule = AlertRule(
        rule_id=uuid.uuid4().hex,
        chinese_name=payload["中文名称"],
        rule_code=payload["rule_code"],
        metric_name=payload["metric_name"],
        condition=payload["condition"],
        threshold=str(payload["threshold"]),
        duration_seconds=int(payload["duration_seconds"]),
        severity=payload["severity"],
        action=payload["action"],
        enabled=bool(payload.get("enabled", True)),
        environment=payload.get("environment", "test"),
        created_by=created_by,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {
        "rule_id": rule.rule_id,
        "中文名称": rule.chinese_name,
        "rule_code": rule.rule_code,
        "metric_name": rule.metric_name,
        "condition": rule.condition,
        "threshold": rule.threshold,
        "duration_seconds": rule.duration_seconds,
        "severity": rule.severity,
        "action": rule.action,
        "enabled": rule.enabled,
        "environment": rule.environment,
        "created_by": rule.created_by,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


def patch_alert_rule_view(db: Session, rule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise ObservabilityNotFoundError("告警规则不存在")
    for key, value in payload.items():
        if value is None:
            continue
        if key == "中文名称":
            rule.chinese_name = value
        elif key == "metric_name":
            rule.metric_name = value
        elif key == "condition":
            rule.condition = value
        elif key == "threshold":
            rule.threshold = str(value)
        elif key == "duration_seconds":
            rule.duration_seconds = int(value)
        elif key == "severity":
            rule.severity = value
        elif key == "action":
            rule.action = value
        elif key == "enabled":
            rule.enabled = bool(value)
        elif key == "environment":
            rule.environment = value
    db.commit()
    db.refresh(rule)
    return {
        "rule_id": rule.rule_id,
        "中文名称": rule.chinese_name,
        "rule_code": rule.rule_code,
        "metric_name": rule.metric_name,
        "condition": rule.condition,
        "threshold": rule.threshold,
        "duration_seconds": rule.duration_seconds,
        "severity": rule.severity,
        "action": rule.action,
        "enabled": rule.enabled,
        "environment": rule.environment,
        "created_by": rule.created_by,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


def reset_circuit_breaker_view(db: Session, breaker_id: str, *, reset_by: str | None = None) -> dict[str, Any]:
    breaker = db.get(CircuitBreaker, breaker_id)
    if not breaker:
        raise ObservabilityNotFoundError("熔断器不存在")
    breaker.status = "正常"
    breaker.reset_at = utcnow()
    breaker.reason = "人工恢复"
    breaker.manual_reset_required = True
    db.commit()
    db.refresh(breaker)
    return {
        "breaker_id": breaker.breaker_id,
        "breaker_scope": breaker.breaker_scope,
        "breaker_key": breaker.breaker_key,
        "status": breaker.status,
        "reason": breaker.reason,
        "risk_score": breaker.risk_score,
        "reset_at": breaker.reset_at.isoformat() if breaker.reset_at else None,
        "updated_at": breaker.updated_at.isoformat() if breaker.updated_at else None,
    }


def get_replay_view(db: Session, workflow_id: str) -> dict[str, Any]:
    replay = db.query(ExecutionReplayIndex).filter(ExecutionReplayIndex.workflow_id == workflow_id).first()
    if replay is None:
        refresh_execution_replay_indexes(db)
        replay = db.query(ExecutionReplayIndex).filter(ExecutionReplayIndex.workflow_id == workflow_id).first()
    if replay is None:
        raise ObservabilityNotFoundError("回放索引不存在")
    return {
        "replay_id": replay.replay_id,
        "workflow_id": replay.workflow_id,
        "task_id": replay.task_id,
        "execution_id": replay.execution_id,
        "session_id": replay.session_id,
        "step_count": replay.step_count,
        "goal": replay.goal,
        "summary": _json_loads(replay.summary_json, {}),
        "available": replay.available,
        "trace_id": replay.trace_id,
        "created_at": replay.created_at.isoformat() if replay.created_at else None,
        "updated_at": replay.updated_at.isoformat() if replay.updated_at else None,
    }


def health_view(db: Session) -> dict[str, Any]:
    overview = build_overview(db)
    return {
        "status": "healthy",
        "feature_flags": {
            "EXECUTION_OBSERVABILITY_ENABLED": get_settings().EXECUTION_OBSERVABILITY_ENABLED,
            "DEVICE_METRICS_ENABLED": get_settings().DEVICE_METRICS_ENABLED,
            "EXECUTION_QUALITY_SCORING_ENABLED": get_settings().EXECUTION_QUALITY_SCORING_ENABLED,
            "EXECUTION_RISK_SCORING_ENABLED": get_settings().EXECUTION_RISK_SCORING_ENABLED,
            "ANOMALY_DETECTION_ENABLED": get_settings().ANOMALY_DETECTION_ENABLED,
            "SECURITY_INCIDENT_CENTER_ENABLED": get_settings().SECURITY_INCIDENT_CENTER_ENABLED,
            "ALERT_RULES_ENABLED": get_settings().ALERT_RULES_ENABLED,
            "AUTOMATIC_PAUSE_ENABLED": get_settings().AUTOMATIC_PAUSE_ENABLED,
            "CIRCUIT_BREAKER_ENABLED": get_settings().CIRCUIT_BREAKER_ENABLED,
            "EXECUTION_REPLAY_ENABLED": get_settings().EXECUTION_REPLAY_ENABLED,
            "EMPLOYEE_PERFORMANCE_METRICS_ENABLED": get_settings().EMPLOYEE_PERFORMANCE_METRICS_ENABLED,
        },
        "overview": overview,
    }


def find_or_create_breaker(db: Session, breaker_scope: str, breaker_key: str, *, trace_id: str | None = None) -> CircuitBreaker:
    breaker = (
        db.query(CircuitBreaker)
        .filter(CircuitBreaker.breaker_scope == breaker_scope, CircuitBreaker.breaker_key == breaker_key)
        .one_or_none()
    )
    if breaker is None:
        breaker = CircuitBreaker(
            breaker_id=uuid.uuid4().hex,
            breaker_scope=breaker_scope,
            breaker_key=breaker_key,
            status="正常",
            reason="初始创建",
            manual_reset_required=True,
            trace_id=trace_id,
        )
        db.add(breaker)
        db.flush()
    return breaker


def trigger_breaker(db: Session, breaker_scope: str, breaker_key: str, *, risk_score: int, reason: str, trace_id: str | None = None, manual_reset_required: bool = True) -> CircuitBreaker:
    breaker = find_or_create_breaker(db, breaker_scope, breaker_key, trace_id=trace_id)
    breaker.status = "已熔断" if risk_score >= 90 else "警告"
    breaker.reason = reason
    breaker.trigger_count += 1
    breaker.risk_score = max(breaker.risk_score, risk_score)
    breaker.triggered_at = utcnow()
    breaker.manual_reset_required = manual_reset_required
    breaker.trace_id = trace_id or breaker.trace_id
    db.flush()
    return breaker


def ensure_default_circuit_breakers(db: Session) -> list[CircuitBreaker]:
    scopes = [
        ("system", "device"),
        ("system", "employee"),
        ("system", "skill"),
        ("system", "capability"),
        ("system", "session"),
        ("system", "workflow"),
        ("system", "application"),
    ]
    breakers: list[CircuitBreaker] = []
    for scope, key in scopes:
        breakers.append(find_or_create_breaker(db, scope, key))
    return breakers


def build_quality_and_risk_summary(db: Session) -> dict[str, Any]:
    quality = list_quality_scores_view(db)
    risk = list_risk_scores_view(db)
    return {
        "quality_scores": quality,
        "risk_scores": risk,
        "quality_summary": {
            "average": int(round(sum(item["score"] for item in quality) / len(quality))) if quality else 0,
            "best": max((item["score"] for item in quality), default=0),
            "worst": min((item["score"] for item in quality), default=0),
        },
        "risk_summary": {
            "average": int(round(sum(item["score"] for item in risk) / len(risk))) if risk else 0,
            "highest": max((item["score"] for item in risk), default=0),
            "high_count": sum(1 for item in risk if item["score"] >= 70),
            "extreme_count": sum(1 for item in risk if item["score"] >= 90),
        },
    }
