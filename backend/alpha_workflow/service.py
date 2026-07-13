from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..agent_runtime.audit import write_audit_event
from ..agent_runtime.models import AgentExecution, AgentExecutionAudit, AgentCapability
from ..agent_runtime.registry import seed_builtin_capabilities
from ..ai_employees.registry import TIANCAI_DATA, employee_name
from ..config import get_settings
from ..knowledge_center.models import KnowledgeAsset, KnowledgeCitation, KnowledgeChunk, KnowledgeReview, KnowledgeSourceLink, KnowledgeTagRelation, KnowledgeVersion
from ..knowledge_center.service import record_use, submit_research_report
from ..models import AiEmployee, TaskCenterResult, TaskCenterTask, User
from ..research_runtime.executor import execute_research_workflow
from ..research_runtime.exceptions import ResearchPersistenceError
from ..research_runtime.models import ResearchClaim, ResearchEvidence, ResearchExecution, ResearchQuery, ResearchSource
from ..research_runtime.service import persist_research_result
from ..skills_engine.models import Skill, SkillInstallation, SkillInvocation
from ..skills_engine.registry import ensure_default_skills
from ..skills_engine.schemas import SkillInvokePayload
from ..skills_engine.service import get_skill_by_code_or_404, invoke_skill
from ..routers.task_center import set_task_status, task_to_dict, write_audit_log

from .audit import append_event, utcnow
from .constants import (
    DEFAULT_ALPHA_SCENARIO_CODE,
    DEFAULT_ALPHA_WORKFLOW_QUALITY_THRESHOLD,
    DEFAULT_ALPHA_WORKFLOW_RISK_THRESHOLD,
    DEFAULT_ALPHA_WORKFLOW_SKILL_CODE,
    DEFAULT_ALPHA_WORKFLOW_TARGET_EMPLOYEE,
)
from .context import AlphaWorkflowContext, AlphaWorkflowPlan, AlphaWorkflowTraceSpan
from .exceptions import AlphaWorkflowConflictError, AlphaWorkflowDependencyError, AlphaWorkflowNotFoundError, AlphaWorkflowValidationError
from .models import AlphaWorkflowEvent, AlphaWorkflowRun, AlphaWorkflowScenario
from .planner import build_alpha_workflow_plan
from .registry import ensure_default_scenarios, scenario_to_dict


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_ALPHA_WORKFLOW_REQUIRED_UNIQUE_CONSTRAINTS = {
    "uq_alpha_workflow_runs_root_span_id",
    "uq_alpha_workflow_runs_workflow_id",
    "uq_alpha_workflow_runs_orchestrator_run_id",
    "uq_alpha_workflow_runs_research_report_id",
    "uq_alpha_workflow_runs_skill_invocation_id",
}
_ALPHA_WORKFLOW_IDEMPOTENCY_CONSTRAINTS = {
    "uq_alpha_workflow_runs_trace_id",
    "uq_alpha_workflow_runs_workflow_id",
    "uq_alpha_workflow_runs_root_span_id",
    "uq_alpha_workflow_runs_orchestrator_run_id",
}


def _alpha_workflow_conflict_message(exc: IntegrityError) -> str | None:
    constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint_name in _ALPHA_WORKFLOW_REQUIRED_UNIQUE_CONSTRAINTS:
        return "Alpha Workflow 已存在相同的唯一标识记录"
    message = str(exc.orig) if getattr(exc, "orig", None) is not None else str(exc)
    if "alpha_workflow_runs" in message:
        for name in _ALPHA_WORKFLOW_REQUIRED_UNIQUE_CONSTRAINTS:
            if name in message:
                return "Alpha Workflow 已存在相同的唯一标识记录"
    return None


def _alpha_workflow_constraint_name(exc: IntegrityError) -> str | None:
    constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint_name:
        return constraint_name
    message = str(exc.orig) if getattr(exc, "orig", None) is not None else str(exc)
    for name in _ALPHA_WORKFLOW_REQUIRED_UNIQUE_CONSTRAINTS | {"uq_alpha_workflow_runs_trace_id"}:
        if name in message:
            return name
    return None


def _alpha_workflow_failure_message(exc: Exception) -> str:
    if isinstance(exc, ResearchPersistenceError):
        return "研究结果保存失败，任务已进入可恢复状态。"
    if isinstance(exc, IntegrityError):
        return "Alpha Workflow 数据一致性校验失败，任务已进入可恢复状态。"
    return "Alpha Workflow 执行失败，任务已进入可恢复状态。"


def _cleanup_alpha_workflow_artifacts(
    db: Session,
    *,
    task_id: int | None,
    research_execution_id: str | None,
    knowledge_id: str | None,
    skill_invocation_id: int | None,
) -> None:
    if task_id is not None:
        db.query(TaskCenterResult).filter(TaskCenterResult.task_id == task_id).delete(synchronize_session=False)
    if research_execution_id:
        db.query(ResearchEvidence).filter(ResearchEvidence.execution_id == research_execution_id).delete(synchronize_session=False)
        db.query(ResearchClaim).filter(ResearchClaim.execution_id == research_execution_id).delete(synchronize_session=False)
        db.query(ResearchSource).filter(ResearchSource.execution_id == research_execution_id).delete(synchronize_session=False)
        db.query(ResearchQuery).filter(ResearchQuery.execution_id == research_execution_id).delete(synchronize_session=False)
        db.query(ResearchExecution).filter(ResearchExecution.execution_id == research_execution_id).delete(synchronize_session=False)
    if knowledge_id:
        db.query(KnowledgeCitation).filter(KnowledgeCitation.knowledge_id == knowledge_id).delete(synchronize_session=False)
        db.query(KnowledgeSourceLink).filter(KnowledgeSourceLink.knowledge_id == knowledge_id).delete(synchronize_session=False)
        db.query(KnowledgeTagRelation).filter(KnowledgeTagRelation.knowledge_id == knowledge_id).delete(synchronize_session=False)
        db.query(KnowledgeReview).filter(KnowledgeReview.knowledge_id == knowledge_id).delete(synchronize_session=False)
        db.query(KnowledgeVersion).filter(KnowledgeVersion.knowledge_id == knowledge_id).delete(synchronize_session=False)
        db.query(KnowledgeAsset).filter(KnowledgeAsset.knowledge_id == knowledge_id).delete(synchronize_session=False)
    if skill_invocation_id is not None:
        db.query(SkillInvocation).filter(SkillInvocation.id == skill_invocation_id).delete(synchronize_session=False)


def _compensate_alpha_workflow_failure(
    db: Session,
    *,
    run_id: str,
    task_id: int | None,
    agent_execution_id: str | None,
    research_execution_id: str | None,
    knowledge_id: str | None,
    skill_invocation_id: int | None,
    user: User,
    reason: str,
    context: AlphaWorkflowContext | None = None,
) -> AlphaWorkflowRun | None:
    db.rollback()
    _cleanup_alpha_workflow_artifacts(
        db,
        task_id=task_id,
        research_execution_id=research_execution_id,
        knowledge_id=knowledge_id,
        skill_invocation_id=skill_invocation_id,
    )
    run = db.get(AlphaWorkflowRun, run_id)
    task = db.get(TaskCenterTask, task_id) if task_id else None
    agent_execution = db.get(AgentExecution, agent_execution_id) if agent_execution_id else None
    if agent_execution:
        agent_execution.status = "failed"
        agent_execution.error_code = agent_execution.error_code or "ALPHA_WORKFLOW_PERSISTENCE_FAILED"
        agent_execution.error_message = reason
        agent_execution.finished_at = agent_execution.finished_at or _utc_now()
        agent_execution.updated_at = _utc_now()
        existing_audit = (
            db.query(AgentExecutionAudit)
            .filter(
                AgentExecutionAudit.execution_id == agent_execution.execution_id,
                AgentExecutionAudit.event_type == "execution_failed",
            )
            .first()
        )
        if not existing_audit:
            write_audit_event(
                db,
                agent_execution,
                event_type="execution_failed",
                actor_type="system",
                actor_id="alpha_workflow",
                approval_status=agent_execution.approval_status,
                risk_level=agent_execution.risk_level,
                error_summary=reason,
                executor_name="AlphaWorkflow",
            )
    if run:
        run.status = "已失败"
        run.failure_reason = reason
        run.recovery_status = "待恢复"
        run.finished_at = run.finished_at or _utc_now()
        run.updated_at = _utc_now()
        if context:
            context.status = "已失败"
            context.dashboard_status = "失败"
            context.set_stage("workflow", "失败", message=reason, metadata={"error": reason})
            run.workflow_context_json = context.model_dump_json()
        append_event(
            db,
            run,
            event_code="workflow_failed",
            stage="workflow",
            status="失败",
            message=reason,
            payload={"reason": reason},
            parent_span_id=run.root_span_id,
        )
    if task:
        set_task_status(db, task, "rejected", user, "alpha_workflow_failed", reason)
    db.commit()
    if run:
        db.refresh(run)
    if task:
        db.refresh(task)
    if agent_execution:
        db.refresh(agent_execution)
    return run


def _resolve_alpha_workflow_run_by_identities(
    db: Session,
    *,
    trace_id: str | None,
    workflow_id: str | None,
    root_span_id: str | None,
    orchestrator_run_id: str | None,
) -> tuple[AlphaWorkflowRun | None, bool]:
    provided_identities = {
        "trace_id": trace_id,
        "workflow_id": workflow_id,
        "root_span_id": root_span_id,
        "orchestrator_run_id": orchestrator_run_id,
    }
    runs_by_id: dict[str, AlphaWorkflowRun] = {}
    for field_name, value in {
        field_name: value for field_name, value in provided_identities.items() if value
    }.items():
        if not value:
            continue
        run = db.query(AlphaWorkflowRun).filter(getattr(AlphaWorkflowRun, field_name) == value).one_or_none()
        if run:
            runs_by_id[run.run_id] = run
    if not runs_by_id:
        return None, False
    if len(runs_by_id) == 1:
        resolved_run = next(iter(runs_by_id.values()))
        for field_name, value in provided_identities.items():
            if not value:
                continue
            run = db.query(AlphaWorkflowRun).filter(getattr(AlphaWorkflowRun, field_name) == value).one_or_none()
            if run is None or run.run_id != resolved_run.run_id:
                return None, True
        return resolved_run, False
    return None, True


def ensure_tiancai_employee(db: Session) -> AiEmployee:
    employee = db.query(AiEmployee).filter(AiEmployee.employee_code == TIANCAI_DATA).one_or_none()
    if employee:
        return employee
    employee = AiEmployee(
        employee_code=TIANCAI_DATA,
        employee_name=employee_name(TIANCAI_DATA) or "天采：数据采集平台",
        legion="数据资产军团",
        duty="公开研究与知识沉淀",
        status="active",
        task_types='["research", "knowledge"]',
        default_permissions='["task_center.manage", "task_center.execute"]',
        is_legacy=False,
        sort_order=20,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def _resolve_skill_approver(db: Session, *, requester_id: int | None) -> User | None:
    query = db.query(User)
    if requester_id is not None:
        query = query.filter(User.id != requester_id)
    approver = (
        query.filter(User.role.in_(["owner", "admin", "boss", "administrator"]))
        .order_by(User.id.asc())
        .first()
    )
    return approver


def ensure_skill_installed(db: Session, skill: Skill, employee: AiEmployee, *, user_id: int | None = None) -> SkillInstallation:
    installation = (
        db.query(SkillInstallation)
        .filter(SkillInstallation.skill_id == skill.id, SkillInstallation.employee_id == employee.id)
        .order_by(SkillInstallation.id.desc())
        .one_or_none()
    )
    approver = _resolve_skill_approver(db, requester_id=user_id)
    if installation:
        if installation.status not in {"已安装", "已启用"}:
            installation.status = "已安装"
            installation.installed_at = installation.installed_at or _utc_now()
            installation.enabled_at = None
            installation.disabled_at = None
        if installation.approved_by is None and approver and approver.id != user_id:
            installation.approved_by = approver.id
        db.commit()
        db.refresh(installation)
        return installation
    version = skill.current_version_id or (skill.versions[0].id if skill.versions else None)
    if version is None:
        raise AlphaWorkflowDependencyError("技能版本不存在")
    installation = SkillInstallation(
        skill_id=skill.id,
        skill_version_id=version,
        employee_id=employee.id,
        department_id=employee.legion,
        status="已安装",
        installed_by=user_id,
        approved_by=approver.id if approver and approver.id != user_id else None,
        installed_at=_utc_now(),
        enabled_at=None,
        disabled_at=None,
        configuration=json.dumps({"alpha_workflow": True}, ensure_ascii=False),
        permission_snapshot=json.dumps({"scope": "employee", "employee_code": employee.employee_code}, ensure_ascii=False),
        checksum_verified=True,
        signature_verified=True,
    )
    db.add(installation)
    db.commit()
    db.refresh(installation)
    return installation


def _create_task(db: Session, *, user: User, input_text: str, trace_id: str) -> TaskCenterTask:
    task = TaskCenterTask(
        title="研究 Apple 最新 AI 战略",
        description=input_text,
        priority="high",
        source="orchestrator",
        status="created",
        created_by_id=user.id,
        updated_by_id=user.id,
        split_plan=json.dumps({"alpha": True, "trace_id": trace_id, "workflow_channel": "orchestrator"}, ensure_ascii=False),
    )
    db.add(task)
    db.flush()
    write_audit_log(db, task, user, "alpha_task_created", None, task.status, "Alpha Workflow 入口创建任务")
    db.commit()
    db.refresh(task)
    return task


def _create_agent_execution(db: Session, *, task: TaskCenterTask, employee: AiEmployee, trace_id: str, input_text: str) -> AgentExecution:
    seed_builtin_capabilities(db)
    execution = AgentExecution(
        execution_id=str(uuid4()),
        task_id=task.id,
        employee_id=employee.id,
        capability_id="research.public.multi_source",
        status="completed",
        risk_level="low",
        approval_status="not_required",
        executor_type="mock",
        input_payload=json.dumps({"topic": input_text, "task_id": task.id}, ensure_ascii=False),
        output_payload=None,
        error_code=None,
        error_message=None,
        retry_count=0,
        started_at=_utc_now(),
        finished_at=_utc_now(),
        duration_ms=0,
        trace_id=trace_id,
        created_by_id=task.created_by_id,
    )
    db.add(execution)
    db.flush()
    write_audit_event(
        db,
        execution,
        event_type="alpha_workflow_research_execution",
        actor_type="user",
        actor_id=f"user:{task.created_by.username if task.created_by else 'boss'}",
        approval_status=execution.approval_status,
        approval_decision="accepted",
        risk_level=execution.risk_level,
        input_summary={"topic": input_text, "task_id": task.id},
        output_summary={"stage": "research"},
        executor_name="alpha_workflow",
    )
    db.commit()
    db.refresh(execution)
    return execution


def _append_span(context: AlphaWorkflowContext, *, stage: str, status: str, message: str | None = None, metadata: dict[str, object] | None = None) -> AlphaWorkflowTraceSpan:
    span = context.set_stage(stage, status, message=message, metadata=metadata or {})
    return span


def _emit_stage_event(
    context: AlphaWorkflowContext,
    db: Session,
    run: AlphaWorkflowRun,
    *,
    event_code: str,
    stage: str,
    status: str,
    message: str,
    payload: dict[str, object] | None = None,
    span_kind: str = "child",
) -> AlphaWorkflowTraceSpan:
    span = _append_span(context, stage=stage, status=status, message=message, metadata=payload or {})
    append_event(
        db,
        run,
        event_code=event_code,
        stage=stage,
        status=status,
        message=message,
        payload=payload or {},
        span_id=span.span_id,
        parent_span_id=span.parent_span_id,
        span_kind=span_kind,
    )
    return span


def _default_browser_reader(url: str, *, trace_id: str, allowed_domains: list[str], blocked_domains: list[str]) -> dict[str, object]:
    domain = url.split("//", 1)[1].split("/", 1)[0] if "//" in url else url
    return {
        "url": url,
        "final_url": url,
        "title": f"公开来源：{domain}",
        "status_code": 200,
        "content_type": "text/html",
        "text": "Apple 正在持续推进 AI 能力、本地模型与端侧智能体验。",
        "structured_fields": {"domain": domain, "trace_id": trace_id},
        "sources": [url],
        "collected_at": _utc_now().isoformat(),
        "content_hash": f"alpha-{abs(hash((url, trace_id))) % 10_000_000}",
        "duration_ms": 120,
    }


def _score_quality(context: AlphaWorkflowContext) -> tuple[int, str, dict[str, object]]:
    completed = len([step for step in context.step_trace if step.status in {"成功", "已完成"}])
    total = max(1, len(context.step_trace))
    base = int(round(completed / total * 100))
    score = min(100, base + 5 if context.report_hash else base)
    grade = "优秀" if score >= 90 else "良好" if score >= 80 else "合格" if score >= 70 else "需改进" if score >= 50 else "不合格"
    detail = {
        "总步骤": total,
        "成功步骤": completed,
        "报告已生成": bool(context.report_hash),
        "任务已完成": bool(context.task_id and context.research_execution_id and context.knowledge_asset_id and context.skill_invocation_id),
        "扣分原因": [] if score >= 90 else ["存在未完成步骤" if completed < total else "报告未生成"],
        "改进建议": ["保持全链路闭环并持续压缩步骤等待时间"] if score >= 90 else ["补足失败恢复后的结果回写"],
    }
    return score, grade, detail


def _score_risk(context: AlphaWorkflowContext) -> tuple[int, str, dict[str, object]]:
    score = 10
    reasons = ["全部步骤为只读或模拟链路"]
    if context.recovery_from_run_id:
        score += 5
        reasons.append("发生过恢复流程")
    if context.step_trace and any(step.status not in {"成功", "已完成"} for step in context.step_trace):
        score += 20
        reasons.append("存在未成功步骤")
    if context.skill_invocation_id:
        score += 5
    score = min(score, 100)
    level = "低" if score < 30 else "中" if score < 60 else "高" if score < 85 else "极高"
    detail = {"风险原因": reasons, "自动处置": "仅监控，无自动处置"}
    return score, level, detail


def start_alpha_workflow(
    db: Session,
    *,
    user: User,
    input_text: str,
    trace_id: str | None = None,
    scenario_code: str | None = None,
    orchestrator_plan: dict[str, object] | None = None,
) -> dict[str, object]:
    settings = get_settings()
    if not settings.ALPHA_WORKFLOW_ENABLED:
        raise AlphaWorkflowDependencyError("Alpha 工作流未启用")
    if not (settings.ALPHA_SCENARIO_ENABLED or settings.ALPHA_WORKFLOW_ENABLED):
        raise AlphaWorkflowDependencyError("Alpha 场景未启用")
    _ensure_dependency_flags(settings)
    if not input_text.strip():
        raise AlphaWorkflowValidationError("输入内容不能为空")
    if not orchestrator_plan or not orchestrator_plan.get("graph_id"):
        raise AlphaWorkflowValidationError("Alpha Workflow 只能由 Orchestrator 启动")

    ensure_default_scenarios(db, created_by_id=user.id)
    scenario = db.query(AlphaWorkflowScenario).filter(AlphaWorkflowScenario.scenario_code == (scenario_code or DEFAULT_ALPHA_SCENARIO_CODE)).one_or_none()
    if not scenario:
        raise AlphaWorkflowNotFoundError("场景不存在")
    if not scenario.enabled:
        raise AlphaWorkflowValidationError("场景已停用")

    trace_id = trace_id or str(orchestrator_plan["graph_id"])
    workflow_id = f"alpha-{trace_id}"
    root_span_id = f"{trace_id}:root"
    existing_run, existing_run_conflict = _resolve_alpha_workflow_run_by_identities(
        db,
        trace_id=trace_id,
        workflow_id=workflow_id,
        root_span_id=root_span_id,
        orchestrator_run_id=orchestrator_plan["graph_id"],
    )
    if existing_run and not existing_run_conflict:
        return _run_to_dict(db, existing_run, include_events=True)
    if existing_run_conflict:
        raise AlphaWorkflowConflictError("Alpha Workflow 已存在相同的唯一标识记录")
    plan = build_alpha_workflow_plan(input_text, scenario_code=scenario.scenario_code, trace_id=trace_id)
    plan.root_span_id = root_span_id
    employee = ensure_tiancai_employee(db)
    run = AlphaWorkflowRun(
        run_id=str(uuid4()),
        scenario_id=scenario.scenario_id,
        workflow_id=workflow_id,
        tenant_id="tiantong",
        user_id=user.id,
        task_id=None,
        orchestrator_run_id=orchestrator_plan["graph_id"],
        status="运行中",
        trace_id=trace_id,
        root_span_id=plan.root_span_id or f"{trace_id}:root",
        current_stage="orchestrator",
        workflow_context_json=None,
        plan_json=json.dumps(plan.model_dump(mode="json"), ensure_ascii=False),
        created_by_id=user.id,
        started_at=_utc_now(),
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing_run, existing_run_conflict = _resolve_alpha_workflow_run_by_identities(
            db,
            trace_id=trace_id,
            workflow_id=workflow_id,
            root_span_id=root_span_id,
            orchestrator_run_id=orchestrator_plan["graph_id"],
        )
        if existing_run and not existing_run_conflict:
            return _run_to_dict(db, existing_run, include_events=True)
        if existing_run_conflict:
            raise AlphaWorkflowConflictError("Alpha Workflow 已存在相同的唯一标识记录") from exc
        conflict_message = _alpha_workflow_conflict_message(exc)
        if conflict_message:
            raise AlphaWorkflowConflictError(conflict_message) from exc
        raise
    db.refresh(run)
    context = AlphaWorkflowContext(
        workflow_id=run.workflow_id or f"alpha-{trace_id}",
        tenant_id="tiantong",
        user_id=user.id,
        task_id=None,
        orchestrator_run_id=orchestrator_plan["graph_id"],
        research_execution_id=None,
        research_report_id=None,
        knowledge_asset_id=None,
        knowledge_version_id=None,
        skill_id=None,
        skill_version_id=None,
        skill_invocation_id=None,
        agent_execution_id=None,
        verification_id=None,
        trace_id=trace_id,
        root_span_id=run.root_span_id or f"{trace_id}:root",
        approval_ids=[],
        risk_score=None,
        quality_score=None,
        current_stage="orchestrator",
        status="运行中",
        created_at=run.started_at,
        updated_at=_utc_now(),
        scenario_code=scenario.scenario_code,
        scenario_title=scenario.title,
        input_text=input_text,
        task_title=None,
        task_status=None,
        report_title=None,
        report_hash=None,
        report_content=None,
        dashboard_status="运行中",
        step_trace=[],
        stage_history=[],
        linked_ids={"orchestrator_run_id": orchestrator_plan["graph_id"]},
    )
    task: TaskCenterTask | None = None
    agent_execution: AgentExecution | None = None
    result_row: TaskCenterResult | None = None
    cached_run_id = run.run_id
    cached_task_id: int | None = None
    cached_agent_execution_id: str | None = None
    cached_research_execution_id: str | None = None
    cached_knowledge_id: str | None = None
    cached_skill_invocation_id: int | None = None
    try:
        append_event(
            db,
            run,
            event_code="workflow_created",
            stage="orchestrator",
            status="成功",
            message="Alpha Workflow 由 Orchestrator 唯一入口创建",
            payload={"scenario_code": scenario.scenario_code, "orchestrator_run_id": orchestrator_plan["graph_id"]},
            span_kind="root",
            span_id=run.root_span_id,
            parent_span_id=None,
        )
        run.workflow_context_json = context.model_dump_json()
        db.commit()
        db.refresh(run)
        task = _create_task(db, user=user, input_text=input_text, trace_id=trace_id)
        cached_task_id = task.id
        set_task_status(db, task, "assigned", user, "alpha_assigned", "自动派给天采")
        task.assigned_ai_employee_code = employee.employee_code
        task.assigned_ai_employee_name = employee.employee_name
        set_task_status(db, task, "running", user, "alpha_running", "Alpha Workflow 启动")
        run.task_id = task.id
        context.task_id = task.id
        context.task_title = task.title
        context.task_status = task.status
        context.linked_ids["task_id"] = task.id
        run.workflow_context_json = context.model_dump_json()
        db.commit()

        research_input = {
            "topic": input_text,
            "goal": "形成 Apple 最新 AI 战略的中文研究报告",
            "max_queries": 4,
            "max_sources": 4,
            "min_sources": 2,
            "language": "zh-CN",
            "allowed_domains": [],
            "blocked_domains": [],
            "cross_validate": True,
            "report_format": "中文研究报告",
            "task_title": task.title,
        }
        append_event(
            db,
            run,
            event_code="workflow_started",
            stage="task_center",
            status="成功",
            message="任务中心已创建任务",
            payload={"task_id": task.id, "task_title": task.title},
            parent_span_id=run.root_span_id,
        )
        agent_execution = _create_agent_execution(db, task=task, employee=employee, trace_id=trace_id, input_text=input_text)
        cached_agent_execution_id = agent_execution.execution_id
        research_output = execute_research_workflow(research_input, trace_id=trace_id, browser_reader=_default_browser_reader)
        persist_research_result(db, agent_execution, research_input, research_output)
        cached_research_execution_id = agent_execution.execution_id
        _emit_stage_event(
            context,
            db,
            run,
            event_code="research_executed",
            stage="research",
            status="成功",
            message="Research 执行已完成并持久化",
            payload={"research_execution_id": agent_execution.execution_id, "report_hash": research_output.get("report_hash")},
        )

        knowledge_result = submit_research_report(
            db,
            agent_execution.execution_id,
            submitter_employee_code=employee.employee_code,
            title="Apple 最新 AI 战略研究",
            summary="基于多来源公开研究形成的 Apple AI 战略候选知识。",
            knowledge_type="研究报告",
            category="市场知识",
            visibility="部门可见",
            owner_employee_id=employee.employee_code,
            owner_department=employee.legion,
            tags=["Apple", "AI", "研究"],
        )
        knowledge_id = knowledge_result["knowledge"]["knowledge_id"]
        cached_knowledge_id = knowledge_id
        version_id = knowledge_result["version"]["version_id"]
        chunk = (
            db.query(KnowledgeChunk)
            .filter(KnowledgeChunk.version_id == version_id)
            .order_by(KnowledgeChunk.chunk_index.asc())
            .first()
        )
        _emit_stage_event(
            context,
            db,
            run,
            event_code="knowledge_candidate_created",
            stage="knowledge",
            status="成功",
            message="已创建知识候选",
            payload={"knowledge_id": knowledge_id, "version_id": version_id, "chunk_id": chunk.chunk_id if chunk else None},
        )

        ensure_default_skills(db, created_by=user.id)
        skill = get_skill_by_code_or_404(db, DEFAULT_ALPHA_WORKFLOW_SKILL_CODE)
        installation = ensure_skill_installed(db, skill, employee, user_id=user.id)
        skill_payload = {
            "employee_code": employee.employee_code,
            "query": "Apple AI 战略",
            "limit": 5,
            "knowledge_type": "研究报告",
            "trace_id": trace_id,
            "simulate_outcome": "success",
        }
        invocation = invoke_skill(
            db,
            skill,
            SkillInvokePayload(
                employee_code=employee.employee_code,
                input_payload=skill_payload,
                task_id=task.id,
                execution_id=task.id,
                installation_id=installation.id,
                trace_id=trace_id,
                simulate_outcome="success",
            ),
            user,
        )
        cached_skill_invocation_id = invocation["invocation_id"]
        _emit_stage_event(
            context,
            db,
            run,
            event_code="skill_invoked",
            stage="skills",
            status="成功",
            message="已调用知识检索技能",
            payload={"skill_invocation_id": invocation["invocation_id"], "skill_code": skill.skill_code, "skill_version_id": installation.skill_version_id},
        )

        citation = record_use(
            db,
            knowledge_id,
            chunk_id=chunk.chunk_id if chunk else None,
            usage_type="生成最终研究报告",
            query_text="alpha-workflow-apple-ai-strategy",
            citation_summary="Alpha Workflow 复用知识候选形成最终报告。",
            task_id=task.id,
            execution_id=agent_execution.execution_id,
            employee_id=employee.employee_code,
        )
        run.research_execution_id = agent_execution.execution_id
        run.knowledge_id = knowledge_id
        run.skill_invocation_id = invocation["invocation_id"]
        run.research_report_id = agent_execution.execution_id

        report_content = research_output.get("report_content") or json.dumps(
            {
                "标题": "Apple 最新 AI 战略",
                "摘要": research_output.get("research_summary"),
                "来源数量": research_output.get("source_count", 0),
                "核心结论": research_output.get("core_conclusions", []),
                "知识引用": citation.get("citation", {}),
                "技能调用": invocation,
            },
            ensure_ascii=False,
            indent=2,
        )
        task.summary = (task.summary or "") + f"\n[Alpha Workflow] {research_output.get('report_title', '公开信息研究报告')}"
        result_row = TaskCenterResult(
            task_id=task.id,
            ai_employee_code=employee.employee_code,
            ai_employee_name=employee.employee_name,
            result_content=report_content,
            attachments_json=json.dumps([research_output.get("report_hash")], ensure_ascii=False),
            submitted_by_id=user.id,
        )
        db.add(result_row)
        set_task_status(db, task, "summarized", user, "alpha_report_ready", "Alpha Workflow 已生成最终报告")

        context.research_execution_id = agent_execution.execution_id
        context.research_report_id = agent_execution.execution_id
        context.knowledge_asset_id = knowledge_id
        context.knowledge_version_id = version_id
        context.skill_id = skill.skill_code
        context.skill_version_id = str(installation.skill_version_id)
        context.skill_invocation_id = invocation["invocation_id"]
        context.agent_execution_id = agent_execution.execution_id
        context.verification_id = f"{trace_id}:verification"
        context.approval_ids = [f"{trace_id}:boss-confirmed"]
        context.report_title = research_output.get("report_title") or "公开信息研究报告"
        context.report_hash = research_output.get("report_hash")
        context.report_content = report_content
        context.dashboard_status = "已完成"
        context.status = "已完成"
        context.linked_ids = {
            "task_id": task.id,
            "orchestrator_run_id": orchestrator_plan["graph_id"],
            "research_execution_id": agent_execution.execution_id,
            "research_report_id": agent_execution.execution_id,
            "knowledge_asset_id": knowledge_id,
            "knowledge_version_id": version_id,
            "skill_id": skill.skill_code,
            "skill_version_id": str(installation.skill_version_id),
            "skill_invocation_id": invocation["invocation_id"],
            "agent_execution_id": agent_execution.execution_id,
            "verification_id": f"{trace_id}:verification",
        }
        _emit_stage_event(
            context,
            db,
            run,
            event_code="workflow_verified",
            stage="verification",
            status="成功",
            message="结果已完成验证",
            payload={"verification_id": f"{trace_id}:verification"},
        )
        quality_score, quality_grade, quality_detail = _score_quality(context)
        risk_score, risk_level, risk_detail = _score_risk(context)
        _emit_stage_event(
            context,
            db,
            run,
            event_code="workflow_audited",
            stage="audit",
            status="成功",
            message="审计时间线已写入",
            payload={"task_id": task.id, "report_hash": research_output.get("report_hash")},
        )
        write_audit_log(db, task, user, "alpha_workflow_completed", "running", "summarized", f"quality={quality_score};risk={risk_score}")
        _emit_stage_event(
            context,
            db,
            run,
            event_code="workflow_feedback_recorded",
            stage="feedback",
            status="成功",
            message="任务反馈已回写",
            payload={"task_id": task.id, "result_id": None if result_row is None else getattr(result_row, "id", None)},
        )
        _emit_stage_event(
            context,
            db,
            run,
            event_code="dashboard_refreshed",
            stage="dashboard",
            status="成功",
            message="Alpha 页面已可查看",
            payload={"task_id": task.id},
        )
        run.status = "已完成"
        run.quality_score = quality_score
        run.quality_grade = quality_grade
        run.risk_score = risk_score
        run.risk_level = risk_level
        run.workflow_id = context.workflow_id
        run.tenant_id = context.tenant_id
        run.user_id = context.user_id
        run.orchestrator_run_id = context.orchestrator_run_id
        run.research_report_id = context.research_report_id
        run.knowledge_asset_id = context.knowledge_asset_id
        run.knowledge_version_id = context.knowledge_version_id
        run.skill_id = context.skill_id
        run.skill_version_id = context.skill_version_id
        run.agent_execution_id = context.agent_execution_id
        run.verification_id = context.verification_id
        run.root_span_id = context.root_span_id
        run.approval_ids_json = json.dumps(context.approval_ids, ensure_ascii=False)
        run.current_stage = context.current_stage
        run.workflow_context_json = context.model_dump_json()
        run.report_summary_json = json.dumps(quality_detail, ensure_ascii=False)
        run.dashboard_summary_json = json.dumps(
            {
                "标题": "Alpha Workflow 已完成",
                "质量评分": quality_score,
                "风险评分": risk_score,
                "最终报告": research_output.get("report_title") or "公开信息研究报告",
                "任务标题": task.title,
                "唯一入口": "Orchestrator",
            },
            ensure_ascii=False,
        )
        run.finished_at = _utc_now()
        run.updated_at = _utc_now()
        append_event(db, run, event_code="workflow_completed", stage="workflow", status="成功", message="Alpha Workflow 全链路完成", payload={"quality_score": quality_score, "risk_score": risk_score}, parent_span_id=run.root_span_id)
        db.commit()
        db.refresh(run)
        db.refresh(task)
        db.refresh(result_row)
        return _run_to_dict(db, run)
    except IntegrityError as exc:
        db.rollback()
        constraint_name = _alpha_workflow_constraint_name(exc)
        existing_run, existing_run_conflict = _resolve_alpha_workflow_run_by_identities(
            db,
            trace_id=trace_id,
            workflow_id=workflow_id,
            root_span_id=root_span_id,
            orchestrator_run_id=orchestrator_plan["graph_id"],
        )
        if existing_run and not existing_run_conflict and constraint_name in _ALPHA_WORKFLOW_IDEMPOTENCY_CONSTRAINTS:
            return _run_to_dict(db, existing_run, include_events=True)
        failure_reason = _alpha_workflow_failure_message(exc)
        compensated_run = _compensate_alpha_workflow_failure(
            db,
            run_id=cached_run_id,
            task_id=cached_task_id,
            agent_execution_id=cached_agent_execution_id,
            research_execution_id=cached_research_execution_id,
            knowledge_id=cached_knowledge_id,
            skill_invocation_id=cached_skill_invocation_id,
            user=user,
            reason=failure_reason,
            context=context,
        )
        if constraint_name in {"uq_alpha_workflow_runs_research_report_id", "uq_alpha_workflow_runs_skill_invocation_id"}:
            raise AlphaWorkflowConflictError("Alpha Workflow 已存在相同的唯一标识记录") from exc
        if existing_run_conflict:
            raise AlphaWorkflowConflictError("Alpha Workflow 已存在相同的唯一标识记录") from exc
        conflict_message = _alpha_workflow_conflict_message(exc)
        if conflict_message:
            raise AlphaWorkflowConflictError(conflict_message) from exc
        if compensated_run is None:
            raise AlphaWorkflowValidationError(failure_reason) from exc
        raise AlphaWorkflowValidationError(failure_reason) from exc
    except Exception as exc:
        failure_reason = _alpha_workflow_failure_message(exc)
        compensated_run = _compensate_alpha_workflow_failure(
            db,
            run_id=cached_run_id,
            task_id=cached_task_id,
            agent_execution_id=cached_agent_execution_id,
            research_execution_id=cached_research_execution_id,
            knowledge_id=cached_knowledge_id,
            skill_invocation_id=cached_skill_invocation_id,
            user=user,
            reason=failure_reason,
            context=context,
        )
        if compensated_run is None:
            return {"status": "已失败", "failure_reason": failure_reason}
        return _run_to_dict(db, compensated_run)


def recover_alpha_workflow(db: Session, *, user: User, run_id: str, reason: str | None = None) -> dict[str, object]:
    run = db.get(AlphaWorkflowRun, run_id)
    if not run:
        raise AlphaWorkflowNotFoundError("Alpha Workflow 运行记录不存在")
    if run.status not in {"已失败", "已暂停"}:
        raise AlphaWorkflowValidationError("仅失败或暂停的 Alpha Workflow 可以恢复")
    _ensure_dependency_flags(get_settings())
    if run.recovery_status == "已恢复":
        return _run_to_dict(db, run, include_events=True)
    context = _parse_context(run.workflow_context_json)
    if not context:
        context = AlphaWorkflowContext(
            workflow_id=run.workflow_id or f"alpha-{run.trace_id}",
            tenant_id=run.tenant_id or "tiantong",
            user_id=run.user_id,
            task_id=run.task_id,
            orchestrator_run_id=run.orchestrator_run_id,
            research_execution_id=run.research_execution_id,
            research_report_id=run.research_report_id,
            knowledge_asset_id=run.knowledge_asset_id,
            knowledge_version_id=run.knowledge_version_id,
            skill_id=run.skill_id,
            skill_version_id=run.skill_version_id,
            skill_invocation_id=run.skill_invocation_id,
            agent_execution_id=run.agent_execution_id,
            verification_id=run.verification_id,
            trace_id=run.trace_id,
            root_span_id=run.root_span_id or f"{run.trace_id}:root",
            approval_ids=_parse_json(run.approval_ids_json) or [],
            risk_score=run.risk_score,
            quality_score=run.quality_score,
            current_stage=run.current_stage or "recovery",
            status=run.status,
            created_at=run.created_at,
            updated_at=_utc_now(),
            scenario_code=None,
            scenario_title=None,
            input_text=None,
            task_title=None,
            task_status=None,
            report_title=None,
            report_hash=None,
            report_content=None,
            dashboard_status=run.status,
            step_trace=[],
            stage_history=[],
            linked_ids={},
            recovery_from_run_id=run.run_id,
        )
    recovery_trace_id = f"{run.trace_id}-recovery-{uuid4().hex[:12]}"
    recovery_root_span_id = f"{recovery_trace_id}:root"
    context.recovery_from_run_id = run.run_id
    context.trace_id = recovery_trace_id
    context.root_span_id = recovery_root_span_id
    context.status = "已恢复"
    context.dashboard_status = "已恢复"
    recovery_span = _append_span(context, stage="recovery", status="成功", message=reason or "从安全检查点恢复", metadata={"recovered_from_run_id": run.run_id})
    run.recovery_status = "已恢复"
    run.recovered_from_run_id = run.run_id
    run.status = "已完成" if run.status != "已完成" else run.status
    run.current_stage = "recovery"
    run.finished_at = run.finished_at or _utc_now()
    run.updated_at = _utc_now()
    run.trace_id = recovery_trace_id
    run.root_span_id = recovery_root_span_id
    run.workflow_context_json = context.model_dump_json()
    append_event(
        db,
        run,
        event_code="workflow_recovered",
        stage="recovery",
        status="成功",
        message=reason or "从安全检查点恢复",
        payload={"run_id": run.run_id, "recovered_from_run_id": run.run_id, "recovery_span_id": recovery_span.span_id},
        span_id=recovery_span.span_id,
        parent_span_id=recovery_span.parent_span_id,
        span_kind=recovery_span.span_kind,
    )
    db.commit()
    db.refresh(run)
    return _run_to_dict(db, run, include_events=True)


def list_scenarios(db: Session) -> list[dict[str, object]]:
    ensure_default_scenarios(db)
    rows = db.query(AlphaWorkflowScenario).order_by(AlphaWorkflowScenario.created_at.asc()).all()
    return [scenario_to_dict(row) for row in rows]


def list_runs(db: Session, *, limit: int = 20) -> list[dict[str, object]]:
    rows = db.query(AlphaWorkflowRun).order_by(AlphaWorkflowRun.created_at.desc()).limit(limit).all()
    return [_run_to_dict(db, row) for row in rows]


def get_run(db: Session, run_id: str) -> dict[str, object]:
    run = db.get(AlphaWorkflowRun, run_id)
    if not run:
        raise AlphaWorkflowNotFoundError("Alpha Workflow 运行记录不存在")
    return _run_to_dict(db, run, include_events=True)


def get_scenario(db: Session, scenario_code: str) -> dict[str, object]:
    scenario = db.query(AlphaWorkflowScenario).filter(AlphaWorkflowScenario.scenario_code == scenario_code).one_or_none()
    if not scenario:
        raise AlphaWorkflowNotFoundError("Alpha Workflow 场景不存在")
    return scenario_to_dict(scenario)


def create_scenario(db: Session, *, created_by_id: int | None, payload: dict[str, object]) -> dict[str, object]:
    scenario = AlphaWorkflowScenario(
        scenario_id=str(uuid4()),
        scenario_code=str(payload["scenario_code"]).strip(),
        title=str(payload["title"]).strip(),
        description=payload.get("description"),
        input_hint=payload.get("input_hint"),
        default_input_text=payload.get("default_input_text"),
        workflow_template_json=json.dumps(payload.get("workflow_template") or {}, ensure_ascii=False),
        enabled=bool(payload.get("enabled", True)),
        created_by_id=created_by_id,
    )
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return scenario_to_dict(scenario)


def build_dashboard(db: Session) -> dict[str, object]:
    runs = db.query(AlphaWorkflowRun).order_by(AlphaWorkflowRun.created_at.desc()).limit(5).all()
    scenarios = db.query(AlphaWorkflowScenario).count()
    completed = db.query(AlphaWorkflowRun).filter(AlphaWorkflowRun.status == "已完成").count()
    failed = db.query(AlphaWorkflowRun).filter(AlphaWorkflowRun.status == "已失败").count()
    latest = runs[0] if runs else None
    return {
        "title": "Alpha Workflow 页面",
        "scenario_count": scenarios,
        "run_count": db.query(AlphaWorkflowRun).count(),
        "completed_count": completed,
        "failed_count": failed,
        "latest_run": _run_to_dict(db, latest) if latest else None,
        "runs": [_run_to_dict(db, row) for row in runs],
        "feature_flags": {
            "ALPHA_WORKFLOW_ENABLED": get_settings().ALPHA_WORKFLOW_ENABLED,
            "ALPHA_SCENARIO_ENABLED": get_settings().ALPHA_SCENARIO_ENABLED,
            "ALPHA_WORKFLOW_DASHBOARD_ENABLED": get_settings().ALPHA_WORKFLOW_DASHBOARD_ENABLED,
            "ALPHA_DASHBOARD_ENABLED": get_settings().ALPHA_DASHBOARD_ENABLED,
        },
    }


def health_view(db: Session) -> dict[str, object]:
    return {
        "ok": True,
        "status": "healthy",
        "feature_flags": {
            "ALPHA_WORKFLOW_ENABLED": get_settings().ALPHA_WORKFLOW_ENABLED,
            "ALPHA_SCENARIO_ENABLED": get_settings().ALPHA_SCENARIO_ENABLED,
            "ALPHA_WORKFLOW_DASHBOARD_ENABLED": get_settings().ALPHA_WORKFLOW_DASHBOARD_ENABLED,
            "ALPHA_DASHBOARD_ENABLED": get_settings().ALPHA_DASHBOARD_ENABLED,
        },
        "scenario_count": db.query(AlphaWorkflowScenario).count(),
        "run_count": db.query(AlphaWorkflowRun).count(),
        "latest_run": _run_to_dict(db, db.query(AlphaWorkflowRun).order_by(AlphaWorkflowRun.created_at.desc()).first()) if db.query(AlphaWorkflowRun).count() else None,
    }


def _run_to_dict(db: Session, run: AlphaWorkflowRun | None, *, include_events: bool = False) -> dict[str, object]:
    if run is None:
        return {}
    scenario = db.get(AlphaWorkflowScenario, run.scenario_id)
    context = _parse_context(run.workflow_context_json)
    plan = _parse_json(run.plan_json)
    report_summary = _parse_json(run.report_summary_json)
    dashboard_summary = _parse_json(run.dashboard_summary_json)
    payload = {
        "run_id": run.run_id,
        "scenario_id": run.scenario_id,
        "scenario_code": scenario.scenario_code if scenario else None,
        "scenario_title": scenario.title if scenario else None,
        "workflow_id": run.workflow_id,
        "tenant_id": run.tenant_id,
        "user_id": run.user_id,
        "task_id": run.task_id,
        "orchestrator_run_id": run.orchestrator_run_id,
        "research_execution_id": run.research_execution_id,
        "research_report_id": run.research_report_id,
        "knowledge_id": run.knowledge_id,
        "knowledge_asset_id": run.knowledge_asset_id,
        "knowledge_version_id": run.knowledge_version_id,
        "skill_id": run.skill_id,
        "skill_version_id": run.skill_version_id,
        "skill_invocation_id": run.skill_invocation_id,
        "agent_execution_id": run.agent_execution_id,
        "verification_id": run.verification_id,
        "status": run.status,
        "quality_score": run.quality_score,
        "quality_grade": run.quality_grade,
        "risk_score": run.risk_score,
        "risk_level": run.risk_level,
        "failure_reason": run.failure_reason,
        "recovery_status": run.recovery_status,
        "workflow_context": context.model_dump(mode="json") if context else {},
        "plan": plan,
        "report_summary": report_summary,
        "dashboard_summary": dashboard_summary,
        "trace_id": run.trace_id,
        "root_span_id": run.root_span_id,
        "current_stage": run.current_stage,
        "approval_ids": _parse_json(run.approval_ids_json) or [],
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "recovered_from_run_id": run.recovered_from_run_id,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }
    if include_events:
        payload["events"] = [
            {
                "event_id": item.event_id,
                "event_code": item.event_code,
                "stage": item.stage,
                "status": item.status,
                "message": item.message,
                "payload": _parse_json(item.payload_json),
                "span_id": item.span_id,
                "parent_span_id": item.parent_span_id,
                "span_kind": item.span_kind,
                "module_name": item.stage,
                "trace_id": item.trace_id,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in db.query(AlphaWorkflowEvent).filter(AlphaWorkflowEvent.run_id == run.run_id).order_by(AlphaWorkflowEvent.created_at.asc()).all()
        ]
    return payload


def get_trace(db: Session, run_id: str) -> dict[str, object]:
    run = db.get(AlphaWorkflowRun, run_id)
    if not run:
        raise AlphaWorkflowNotFoundError("Alpha Workflow 运行记录不存在")
    context = _parse_context(run.workflow_context_json)
    events = db.query(AlphaWorkflowEvent).filter(AlphaWorkflowEvent.run_id == run.run_id).order_by(AlphaWorkflowEvent.created_at.asc()).all()
    spans = []
    if context:
        spans = [
            {
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
                "span_name": span.span_name,
                "module_name": span.module_name,
                "span_kind": span.span_kind,
                "stage": span.stage,
                "status": span.status,
                "started_at": span.started_at.isoformat() if span.started_at else None,
                "finished_at": span.finished_at.isoformat() if span.finished_at else None,
                "message": span.message,
                "metadata": span.metadata,
            }
            for span in context.step_trace
        ]
    return {
        "run_id": run.run_id,
        "trace_id": run.trace_id,
        "root_span_id": run.root_span_id,
        "current_stage": run.current_stage,
        "status": run.status,
        "workflow_context": context.model_dump(mode="json") if context else {},
        "spans": spans,
        "events": [
            {
                "event_id": event.event_id,
                "event_code": event.event_code,
                "stage": event.stage,
                "status": event.status,
                "message": event.message,
                "payload": _parse_json(event.payload_json),
                "span_id": event.span_id,
                "parent_span_id": event.parent_span_id,
                "span_kind": event.span_kind,
                "module_name": event.stage,
                "trace_id": event.trace_id,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
    }


def get_audit_timeline(db: Session, run_id: str) -> dict[str, object]:
    return {"timeline": get_trace(db, run_id)["events"]}


def get_final_report(db: Session, run_id: str) -> dict[str, object]:
    run = db.get(AlphaWorkflowRun, run_id)
    if not run:
        raise AlphaWorkflowNotFoundError("Alpha Workflow 运行记录不存在")
    report_summary = _parse_json(run.report_summary_json)
    dashboard_summary = _parse_json(run.dashboard_summary_json)
    context = _parse_context(run.workflow_context_json)
    return {
        "run_id": run.run_id,
        "trace_id": run.trace_id,
        "status": run.status,
        "quality_score": run.quality_score,
        "quality_grade": run.quality_grade,
        "risk_score": run.risk_score,
        "risk_level": run.risk_level,
        "report_summary": report_summary,
        "dashboard_summary": dashboard_summary,
        "report_content": context.report_content if context else None,
        "report_title": context.report_title if context else None,
        "report_hash": context.report_hash if context else None,
        "current_stage": run.current_stage,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def cancel_alpha_workflow(db: Session, *, user: User, run_id: str, reason: str | None = None) -> dict[str, object]:
    run = db.get(AlphaWorkflowRun, run_id)
    if not run:
        raise AlphaWorkflowNotFoundError("Alpha Workflow 运行记录不存在")
    if run.status in {"已完成", "已失败", "已取消", "已终止"}:
        return _run_to_dict(db, run, include_events=True)
    task = db.get(TaskCenterTask, run.task_id) if run.task_id else None
    run.status = "已取消"
    run.recovery_status = "已取消"
    run.failure_reason = reason or "Alpha Workflow 已取消"
    run.finished_at = _utc_now()
    run.updated_at = _utc_now()
    append_event(db, run, event_code="workflow_failed", stage="workflow", status="失败", message=run.failure_reason, payload={"reason": reason or "user_cancelled"}, parent_span_id=run.root_span_id, span_kind="child")
    db.commit()
    db.refresh(run)
    if task:
        write_audit_log(db, task, user, "alpha_workflow_cancelled", "running", "canceled", run.failure_reason)
    return _run_to_dict(db, run, include_events=True)


def get_stage_detail(db: Session, run_id: str) -> dict[str, object]:
    return get_trace(db, run_id)


def _parse_context(raw: str | None) -> AlphaWorkflowContext | None:
    if not raw:
        return None
    try:
        return AlphaWorkflowContext.model_validate_json(raw)
    except Exception:
        return None


def _ensure_dependency_flags(settings) -> None:
    required_flags = {
        "PUBLIC_RESEARCH_ENABLED": settings.PUBLIC_RESEARCH_ENABLED,
        "PUBLIC_SEARCH_ENABLED": settings.PUBLIC_SEARCH_ENABLED,
        "KNOWLEDGE_CENTER_ENABLED": settings.KNOWLEDGE_CENTER_ENABLED,
        "KNOWLEDGE_SUBMISSION_ENABLED": settings.KNOWLEDGE_SUBMISSION_ENABLED,
        "KNOWLEDGE_LOCAL_SEARCH_ENABLED": settings.KNOWLEDGE_LOCAL_SEARCH_ENABLED,
        "SKILLS_ENGINE_ENABLED": settings.SKILLS_ENGINE_ENABLED,
        "SKILL_INSTALLATION_ENABLED": settings.SKILL_INSTALLATION_ENABLED,
        "SKILL_INVOCATION_ENABLED": settings.SKILL_INVOCATION_ENABLED,
    }
    if not (settings.ALPHA_WORKFLOW_ENABLED or settings.ALPHA_SCENARIO_ENABLED):
        required_flags["ALPHA_WORKFLOW_ENABLED/ALPHA_SCENARIO_ENABLED"] = False
    disabled = [name for name, enabled in required_flags.items() if not enabled]
    if disabled:
        raise AlphaWorkflowDependencyError(f"依赖模块未启用：{', '.join(disabled)}")


def _parse_json(raw: str | None):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {"raw": raw}
