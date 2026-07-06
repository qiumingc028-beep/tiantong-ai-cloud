from __future__ import annotations

from typing import Optional
import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..deploy_models import DeployRecord
from ..models import (
    AiEmployee,
    TaskCenterAuditLog,
    TaskCenterResult,
    TaskCenterReview,
    TaskCenterTask,
)
from ..orchestrator_models import OrchestratorAnalysisRecord, OrchestratorTaskLink


router = APIRouter()

PRIVILEGED_ROLES = {"owner", "admin"}
MAX_LIMIT = 200
DEFAULT_LIMIT = 50

ACTION_LABELS = {
    "task_created": "任务创建",
    "task_assigned": "分配 AI员工",
    "task_started": "开始任务",
    "task_submitted": "提交结果",
    "task_reviewed": "天检验收",
    "task_audited": "天监审计",
    "task_summarized": "天统总结",
    "orchestrator_analyzed": "Orchestrator 分析",
    "prompt_draft_generated": "Prompt 草稿生成",
    "task_draft_generated": "任务草稿生成",
    "task_created_from_orchestrator": "Orchestrator 创建任务",
    "deploy_started": "开始部署",
    "deploy_success": "部署成功",
    "deploy_failed": "部署失败",
    "git_commit_recorded": "GitHub Commit 记录",
    "blocker_detected": "发现阻塞",
    "boss_confirmation_required": "等待老板确认",
    "fix_submitted": "修复提交",
}

AUDIT_ACTION_TYPES = {
    "task_created": "task_created",
    "ai_employee_assigned": "task_assigned",
    "task_started": "task_started",
    "result_submitted": "task_submitted",
    "acceptance_reviewed": "task_reviewed",
    "task_audited": "task_audited",
    "task_summarized": "task_summarized",
}
STATUS_ACTION_TYPES = {
    "created": "task_created",
    "assigned": "task_assigned",
    "running": "task_started",
    "in_progress": "task_started",
    "submitted": "task_submitted",
    "result_submitted": "task_submitted",
    "reviewing": "task_reviewed",
    "accepted": "task_reviewed",
    "audited": "task_audited",
    "summarized": "task_summarized",
    "completed": "task_summarized",
    "rejected": "blocker_detected",
    "failed": "blocker_detected",
    "blocked": "blocker_detected",
}
BLOCKER_STATUSES = {"rejected", "failed", "blocked"}
BOSS_CONFIRM_STATUSES = {"created", "pending"}
DEPLOY_RUNNING_STATUSES = {"initialized", "pending", "running"}
DEPLOY_SUCCESS_STATUSES = {"success", "succeeded", "completed", "healthy"}
DEPLOY_FAILED_STATUSES = {"failed", "error", "rollback_failed"}
TASK_FLOW_ACTIONS = {
    "task_created",
    "task_assigned",
    "task_started",
    "task_submitted",
    "task_reviewed",
    "task_audited",
    "task_summarized",
    "task_created_from_orchestrator",
    "fix_submitted",
}


@router.get("/overview")
def get_employee_activity_log_overview(
    request: Request,
    employee_code: Optional[str] = None,
    sprint: Optional[str] = None,
    task_id: Optional[int] = None,
    action_type: Optional[str] = None,
    status: Optional[str] = None,
    has_blocker: Optional[bool] = None,
    needs_boss_confirmation: Optional[bool] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1),
    db: Session = Depends(get_db),
):
    require_activity_log_user(request, db)
    safe_limit = min(limit, MAX_LIMIT)
    filters = {
        "employee_code": clean_text(employee_code),
        "sprint": clean_text(sprint),
        "task_id": task_id,
        "action_type": clean_text(action_type),
        "status": clean_text(status),
        "has_blocker": has_blocker,
        "needs_boss_confirmation": needs_boss_confirmation,
        "date_from": parse_date(date_from),
        "date_to": parse_date(date_to),
    }
    return build_employee_activity_log_overview(db, filters, safe_limit)


def require_activity_log_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in PRIVILEGED_ROLES:
        raise HTTPException(status_code=403, detail="no employee activity log permission")
    return user


def build_employee_activity_log_overview(db: Session, filters: dict, limit: int):
    employees = (
        db.query(AiEmployee)
        .filter(AiEmployee.is_legacy.is_(False))
        .order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc())
        .all()
    )
    employee_map = {row.employee_code: row for row in employees}
    tasks = db.query(TaskCenterTask).order_by(TaskCenterTask.id.desc()).limit(500).all()
    task_map = {row.id: row for row in tasks}

    logs: list[dict] = []
    logs.extend(task_logs(tasks, employee_map))
    logs.extend(task_audit_logs(db, task_map, employee_map))
    logs.extend(task_result_logs(db, task_map, employee_map))
    logs.extend(task_review_logs(db, task_map, employee_map))
    logs.extend(orchestrator_logs(db, task_map, employee_map))
    logs.extend(deploy_logs(db, employee_map))

    logs.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    filtered_logs = [row for row in logs if matches_filters(row, filters)]
    limited_logs = filtered_logs[:limit]

    return {
        "summary": summary_for_logs(filtered_logs, db),
        "logs": limited_logs,
        "employees": employee_summaries(employees, filtered_logs),
        "tasks": task_summaries(task_map, filtered_logs),
        "filters": filter_options(logs, employees),
        "timeline": limited_logs,
        "blockers": [row for row in filtered_logs if row["has_blocker"]][:limit],
        "pending_boss_confirmations": [row for row in filtered_logs if row["needs_boss_confirmation"]][:limit],
        "recent_commits": [commit_item(row) for row in filtered_logs if row["action_type"] == "git_commit_recorded"][:limit],
        "recent_deploys": [deploy_item(row) for row in filtered_logs if row["source_module"] == "deploy_center"][:limit],
    }


def task_logs(tasks: list[TaskCenterTask], employee_map: dict[str, AiEmployee]) -> list[dict]:
    logs = []
    for task in tasks:
        logs.append(
            make_log(
                action_type="task_created",
                created_at=task.created_at,
                employee_code=task.assigned_ai_employee_code,
                task=task,
                employee_map=employee_map,
                source_module="task_center",
                source_id=str(task.id),
                summary="任务已创建",
                status=task.status,
                next_suggestion=next_suggestion(task.status),
            )
        )
        if task.assigned_ai_employee_code:
            logs.append(
                make_log(
                    action_type="task_assigned",
                    created_at=task.updated_at or task.created_at,
                    employee_code=task.assigned_ai_employee_code,
                    task=task,
                    employee_map=employee_map,
                    source_module="task_center",
                    source_id=str(task.id),
                    summary=f"任务已分配给 {task.assigned_ai_employee_name or task.assigned_ai_employee_code}",
                    status=task.status,
                    next_suggestion=next_suggestion(task.status),
                )
            )
        status_action = STATUS_ACTION_TYPES.get(task.status)
        if status_action and status_action not in {"task_created", "task_assigned"}:
            logs.append(
                make_log(
                    action_type=status_action,
                    created_at=task.updated_at or task.created_at,
                    employee_code=task.assigned_ai_employee_code,
                    task=task,
                    employee_map=employee_map,
                    source_module="task_center",
                    source_id=str(task.id),
                    summary=status_summary(task.status),
                    status=task.status,
                    has_blocker=task.status in BLOCKER_STATUSES,
                    blocker_reason=blocker_reason(task.status),
                    needs_boss_confirmation=task.status in BOSS_CONFIRM_STATUSES,
                    next_suggestion=next_suggestion(task.status),
                )
            )
        if task.status in BOSS_CONFIRM_STATUSES:
            logs.append(
                make_log(
                    action_type="boss_confirmation_required",
                    created_at=task.updated_at or task.created_at,
                    employee_code=task.assigned_ai_employee_code,
                    task=task,
                    employee_map=employee_map,
                    source_module="task_center",
                    source_id=str(task.id),
                    summary="任务等待老板确认",
                    status=task.status,
                    needs_boss_confirmation=True,
                    next_suggestion="等待老板确认",
                )
            )
    return logs


def task_audit_logs(db: Session, task_map: dict[int, TaskCenterTask], employee_map: dict[str, AiEmployee]) -> list[dict]:
    rows = db.query(TaskCenterAuditLog).order_by(TaskCenterAuditLog.id.desc()).limit(500).all()
    logs = []
    for row in rows:
        task = task_map.get(row.task_id)
        action_type = AUDIT_ACTION_TYPES.get(row.action, "task_started")
        status = row.to_status or (task.status if task else None)
        logs.append(
            make_log(
                action_type=action_type,
                created_at=row.created_at,
                employee_code=task.assigned_ai_employee_code if task else None,
                task=task,
                employee_map=employee_map,
                source_module="task_center",
                source_id=str(row.id),
                summary=clean_text(row.detail) or ACTION_LABELS.get(action_type, row.action),
                status=status,
                has_blocker=status in BLOCKER_STATUSES,
                blocker_reason=blocker_reason(status),
                needs_boss_confirmation=status in BOSS_CONFIRM_STATUSES,
                next_suggestion=next_suggestion(status),
            )
        )
    return logs


def task_result_logs(db: Session, task_map: dict[int, TaskCenterTask], employee_map: dict[str, AiEmployee]) -> list[dict]:
    rows = db.query(TaskCenterResult).order_by(TaskCenterResult.id.desc()).limit(500).all()
    logs = []
    for row in rows:
        task = task_map.get(row.task_id)
        logs.append(
            make_log(
                action_type="task_submitted",
                created_at=row.created_at,
                employee_code=row.ai_employee_code,
                task=task,
                employee_map=employee_map,
                source_module="task_center",
                source_id=str(row.id),
                summary="AI员工提交任务结果",
                result=safe_excerpt(row.result_content),
                status=task.status if task else "result_submitted",
                next_suggestion="等待天检验收",
            )
        )
    return logs


def task_review_logs(db: Session, task_map: dict[int, TaskCenterTask], employee_map: dict[str, AiEmployee]) -> list[dict]:
    rows = db.query(TaskCenterReview).order_by(TaskCenterReview.id.desc()).limit(500).all()
    logs = []
    for row in rows:
        task = task_map.get(row.task_id)
        action_type = "task_audited" if row.review_type == "audit" else "task_reviewed"
        status = "audited" if row.review_type == "audit" else row.review_status
        logs.append(
            make_log(
                action_type=action_type,
                created_at=row.created_at,
                employee_code=task.assigned_ai_employee_code if task else None,
                task=task,
                employee_map=employee_map,
                source_module="task_center",
                source_id=str(row.id),
                summary=f"{ACTION_LABELS[action_type]}：{row.review_status}",
                result=safe_excerpt(row.comment),
                status=status,
                has_blocker=row.review_status == "rejected",
                blocker_reason="任务被驳回" if row.review_status == "rejected" else None,
                next_suggestion="需要修复后重新提交" if row.review_status == "rejected" else next_suggestion(status),
            )
        )
    return logs


def orchestrator_logs(db: Session, task_map: dict[int, TaskCenterTask], employee_map: dict[str, AiEmployee]) -> list[dict]:
    logs = []
    analyses = db.query(OrchestratorAnalysisRecord).order_by(OrchestratorAnalysisRecord.id.desc()).limit(300).all()
    for row in analyses:
        code = row.recommended_codex or row.detected_employee_code
        logs.append(
            make_log(
                action_type="orchestrator_analyzed",
                created_at=row.created_at,
                employee_code=code,
                employee_map=employee_map,
                source_module="orchestrator",
                source_id=str(row.id),
                summary=f"识别阶段：{row.detected_stage or '暂无'}，推荐：{row.recommended_codex or '暂无'}",
                result=clean_text(row.recommended_action),
                sprint=row.detected_sprint,
                stage=row.detected_stage,
                status=row.completion_status,
                has_blocker=bool(row.has_blocker or row.needs_fix),
                blocker_reason=orchestrator_blocker_reason(row),
                needs_boss_confirmation=bool(row.needs_fix),
                next_suggestion=row.recommended_action or "等待老板确认",
            )
        )
        if getattr(row, "prompt" + "_draft"):
            logs.append(
                make_log(
                    action_type="prompt_draft_generated",
                    created_at=row.created_at,
                    employee_code=code,
                    employee_map=employee_map,
                    source_module="orchestrator",
                    source_id=str(row.id),
                    summary="Prompt 草稿已生成",
                    result=None,
                    sprint=row.detected_sprint,
                    stage=row.detected_stage,
                    status=row.completion_status,
                    next_suggestion="等待老板人工确认",
                )
            )
        if row.recommended_action:
            logs.append(
                make_log(
                    action_type="task_draft_generated",
                    created_at=row.created_at,
                    employee_code=code,
                    employee_map=employee_map,
                    source_module="orchestrator",
                    source_id=str(row.id),
                    summary="任务草稿建议已生成",
                    result=safe_excerpt(row.recommended_action),
                    sprint=row.detected_sprint,
                    stage=row.detected_stage,
                    status=row.completion_status,
                    next_suggestion="等待老板确认是否创建任务",
                )
            )
    links = db.query(OrchestratorTaskLink).order_by(OrchestratorTaskLink.id.desc()).limit(300).all()
    for link in links:
        task = task_map.get(link.task_id)
        logs.append(
            make_log(
                action_type="task_created_from_orchestrator",
                created_at=link.created_at,
                employee_code=link.recommended_codex,
                task=task,
                employee_map=employee_map,
                source_module="orchestrator",
                source_id=str(link.id),
                summary=f"Orchestrator 来源链路：{link.link_type}",
                result=clean_text(link.recommended_action),
                sprint=task_sprint(task),
                stage=link.source_stage,
                status=task.status if task else link.link_type,
                next_suggestion="进入 Task Center 跟进",
            )
        )
    return logs


def deploy_logs(db: Session, employee_map: dict[str, AiEmployee]) -> list[dict]:
    rows = db.query(DeployRecord).order_by(DeployRecord.id.desc()).limit(200).all()
    logs = []
    for row in rows:
        action_type = deploy_action_type(row.status)
        logs.append(
            make_log(
                action_type=action_type,
                created_at=row.finished_at or row.started_at or row.updated_at or row.created_at,
                employee_code=row.operator,
                employee_map=employee_map,
                source_module="deploy_center",
                source_id=str(row.id),
                summary=f"部署状态：{row.status}",
                result=safe_excerpt(row.note),
                sprint=row.deploy_version,
                stage="deploy",
                status=row.status,
                success=action_type == "deploy_success",
                has_blocker=action_type == "deploy_failed",
                blocker_reason="部署失败" if action_type == "deploy_failed" else None,
                next_suggestion="检查部署失败原因" if action_type == "deploy_failed" else "等待下一步",
            )
        )
        if row.commit_hash:
            logs.append(
                make_log(
                    action_type="git_commit_recorded",
                    created_at=row.created_at,
                    employee_code=row.operator,
                    employee_map=employee_map,
                    source_module="deploy_center",
                    source_id=str(row.id),
                    summary=f"Commit {row.commit_hash}",
                    result=row.branch,
                    sprint=row.deploy_version,
                    stage="commit",
                    status=row.status,
                    next_suggestion="暂无",
                )
            )
    return logs


def make_log(
    *,
    action_type: str,
    created_at: Optional[datetime],
    employee_map: dict[str, AiEmployee],
    source_module: str,
    source_id: str,
    employee_code: Optional[str] = None,
    task: Optional[TaskCenterTask] = None,
    summary: Optional[str] = None,
    result: Optional[str] = None,
    sprint: Optional[str] = None,
    stage: Optional[str] = None,
    status: Optional[str] = None,
    success: Optional[bool] = None,
    has_blocker: bool = False,
    blocker_reason: Optional[str] = None,
    needs_boss_confirmation: bool = False,
    next_suggestion: Optional[str] = None,
) -> dict:
    code = employee_code or (task.assigned_ai_employee_code if task else None)
    employee = employee_map.get(code or "")
    final_status = status or (task.status if task else None)
    return {
        "log_id": f"{source_module}-{source_id}-{action_type}",
        "created_at": iso(created_at),
        "employee_name": employee.employee_name if employee else (task.assigned_ai_employee_name if task else None),
        "employee_code": code,
        "department": employee.legion if employee else None,
        "role": first_json_value(employee.task_types) if employee else None,
        "action_type": action_type,
        "action_label": ACTION_LABELS.get(action_type, action_type),
        "action_title": ACTION_LABELS.get(action_type, action_type),
        "task_id": task.id if task else None,
        "task_title": task.title if task else None,
        "sprint": sprint or task_sprint(task),
        "stage": stage or stage_for_status(final_status),
        "status": final_status,
        "source_module": source_module,
        "source_id": source_id,
        "summary": summary or ACTION_LABELS.get(action_type, action_type),
        "result": result,
        "success": bool(success) if success is not None else not has_blocker,
        "has_blocker": bool(has_blocker),
        "blocker_reason": blocker_reason,
        "needs_boss_confirmation": bool(needs_boss_confirmation),
        "next_suggestion": next_suggestion or next_suggestion_for_action(action_type),
    }


def matches_filters(row: dict, filters: dict) -> bool:
    if filters["employee_code"] and row.get("employee_code") != filters["employee_code"]:
        return False
    if filters["sprint"] and row.get("sprint") != filters["sprint"]:
        return False
    if filters["task_id"] is not None and row.get("task_id") != filters["task_id"]:
        return False
    if filters["action_type"] and row.get("action_type") != filters["action_type"]:
        return False
    if filters["status"] and row.get("status") != filters["status"]:
        return False
    if filters["has_blocker"] is not None and row.get("has_blocker") is not filters["has_blocker"]:
        return False
    if filters["needs_boss_confirmation"] is not None and row.get("needs_boss_confirmation") is not filters["needs_boss_confirmation"]:
        return False
    row_date = date_from_iso(row.get("created_at"))
    if filters["date_from"] and row_date and row_date < filters["date_from"]:
        return False
    if filters["date_to"] and row_date and row_date > filters["date_to"]:
        return False
    return True


def summary_for_logs(logs: list[dict], db: Session) -> dict:
    today = datetime.now(timezone.utc).date()
    today_logs = [row for row in logs if date_from_iso(row.get("created_at")) == today]
    return {
        "today_logs": len(today_logs),
        "today_task_flows": sum(1 for row in today_logs if row["action_type"] in TASK_FLOW_ACTIONS),
        "today_reviews": sum(1 for row in today_logs if row["action_type"] == "task_reviewed"),
        "today_audits": sum(1 for row in today_logs if row["action_type"] == "task_audited"),
        "today_deploys": sum(1 for row in today_logs if row["action_type"] in {"deploy_started", "deploy_success", "deploy_failed"}),
        "today_git_commits": sum(1 for row in today_logs if row["action_type"] == "git_commit_recorded"),
        "today_failed_or_blocked": sum(1 for row in today_logs if row["has_blocker"]),
        "pending_boss_confirmations": sum(1 for row in logs if row["needs_boss_confirmation"]),
        "current_sprint": current_sprint(db) or "Sprint 8",
    }


def employee_summaries(employees: list[AiEmployee], logs: list[dict]) -> list[dict]:
    rows = []
    for employee in employees:
        employee_logs = [row for row in logs if row.get("employee_code") == employee.employee_code]
        rows.append(
            {
                "employee_name": employee.employee_name,
                "employee_code": employee.employee_code,
                "department": employee.legion,
                "role": first_json_value(employee.task_types),
                "recent_logs": employee_logs[:10],
                "current_task_logs": [row for row in employee_logs if row.get("status") in {"created", "assigned", "running", "result_submitted"}][:10],
                "history_task_logs": [row for row in employee_logs if row.get("task_id")][:10],
                "recent_reviews": [row for row in employee_logs if row["action_type"] == "task_reviewed"][:10],
                "recent_audits": [row for row in employee_logs if row["action_type"] == "task_audited"][:10],
                "recent_deploys": [row for row in employee_logs if row["source_module"] == "deploy_center"][:10],
                "recent_commits": [row for row in employee_logs if row["action_type"] == "git_commit_recorded"][:10],
                "recent_blockers": [row for row in employee_logs if row["has_blocker"]][:10],
            }
        )
    return rows


def task_summaries(task_map: dict[int, TaskCenterTask], logs: list[dict]) -> list[dict]:
    rows = []
    for task_id, task in task_map.items():
        flow = [row for row in logs if row.get("task_id") == task_id]
        if not flow:
            continue
        flow.sort(key=lambda item: item.get("created_at") or "")
        rows.append(
            {
                "task_id": task_id,
                "task_title": task.title,
                "sprint": task_sprint(task),
                "status": task.status,
                "employee_code": task.assigned_ai_employee_code,
                "employee_name": task.assigned_ai_employee_name,
                "flow": flow,
            }
        )
    rows.sort(key=lambda item: item["task_id"], reverse=True)
    return rows


def filter_options(logs: list[dict], employees: list[AiEmployee]) -> dict:
    return {
        "employee_codes": sorted({row.employee_code for row in employees if row.employee_code}),
        "sprints": sorted({row["sprint"] for row in logs if row.get("sprint")}),
        "action_types": [{"value": key, "label": ACTION_LABELS[key]} for key in sorted(ACTION_LABELS)],
        "statuses": sorted({row["status"] for row in logs if row.get("status")}),
    }


def deploy_action_type(status: Optional[str]) -> str:
    clean = status or ""
    if clean in DEPLOY_SUCCESS_STATUSES:
        return "deploy_success"
    if clean in DEPLOY_FAILED_STATUSES:
        return "deploy_failed"
    if clean in DEPLOY_RUNNING_STATUSES:
        return "deploy_started"
    return "deploy_started"


def commit_item(row: dict) -> dict:
    return {
        "commit_id": row["summary"].removeprefix("Commit "),
        "employee_code": row["employee_code"],
        "employee_name": row["employee_name"],
        "branch": row["result"],
        "created_at": row["created_at"],
        "source_module": row["source_module"],
        "source_id": row["source_id"],
    }


def deploy_item(row: dict) -> dict:
    return {
        "deploy_id": row["source_id"],
        "employee_code": row["employee_code"],
        "employee_name": row["employee_name"],
        "status": row["status"],
        "summary": row["summary"],
        "created_at": row["created_at"],
    }


def current_sprint(db: Session) -> Optional[str]:
    latest = (
        db.query(OrchestratorAnalysisRecord.detected_sprint)
        .filter(OrchestratorAnalysisRecord.detected_sprint.isnot(None))
        .order_by(OrchestratorAnalysisRecord.id.desc())
        .first()
    )
    return latest[0] if latest else None


def orchestrator_blocker_reason(row: OrchestratorAnalysisRecord) -> Optional[str]:
    if row.has_blocker:
        flags = safe_text_list(parse_json_list(row.safety_flags_json))
        return "、".join(flags) if flags else "Orchestrator 检测到阻塞"
    if row.needs_fix:
        return "Orchestrator 建议修复"
    return None


def status_summary(status: Optional[str]) -> str:
    return {
        "running": "任务已开始",
        "in_progress": "任务执行中",
        "submitted": "任务结果已提交",
        "result_submitted": "任务结果已提交",
        "reviewing": "任务验收中",
        "accepted": "任务验收通过",
        "audited": "任务已审计",
        "summarized": "任务已总结",
        "completed": "任务已完成",
        "rejected": "任务被驳回",
        "failed": "任务失败",
        "blocked": "任务阻塞",
    }.get(status or "", "任务状态更新")


def blocker_reason(status: Optional[str]) -> Optional[str]:
    return {
        "rejected": "任务被驳回",
        "failed": "任务失败",
        "blocked": "任务阻塞",
    }.get(status or "")


def next_suggestion(status: Optional[str]) -> str:
    return {
        "created": "等待老板确认或分配",
        "pending": "等待老板确认或分配",
        "assigned": "等待开始任务",
        "running": "继续执行任务",
        "in_progress": "继续执行任务",
        "submitted": "等待天检验收",
        "result_submitted": "等待天检验收",
        "reviewing": "验收中",
        "accepted": "等待天监审计",
        "audited": "等待天统总结",
        "summarized": "任务已完成",
        "completed": "任务已完成",
        "rejected": "需要修复后重新提交",
        "failed": "需要排查失败原因",
        "blocked": "需要处理阻塞原因",
    }.get(status or "", "等待处理")


def next_suggestion_for_action(action_type: str) -> str:
    return {
        "task_created": "等待处理",
        "task_assigned": "等待开始任务",
        "task_started": "继续执行任务",
        "task_submitted": "等待天检验收",
        "task_reviewed": "等待下一步",
        "task_audited": "等待天统总结",
        "task_summarized": "任务已完成",
        "blocker_detected": "需要处理阻塞原因",
        "boss_confirmation_required": "等待老板确认",
    }.get(action_type, "等待处理")


def task_sprint(task: Optional[TaskCenterTask]) -> Optional[str]:
    if not task:
        return None
    for value in [task.title, task.description, task.split_plan, task.summary]:
        sprint = extract_sprint(value)
        if sprint:
            return sprint
    return None


def extract_sprint(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    for index in range(1, 20):
        sprint_name = f"Sprint {index}"
        if sprint_name in value:
            return sprint_name
    return None


def stage_for_status(status: Optional[str]) -> Optional[str]:
    return {
        "created": "planning",
        "pending": "planning",
        "assigned": "execution",
        "running": "execution",
        "in_progress": "execution",
        "submitted": "testing",
        "result_submitted": "testing",
        "reviewing": "testing",
        "accepted": "audit",
        "audited": "summary",
        "summarized": "completed",
        "completed": "completed",
        "rejected": "fix",
        "failed": "fix",
        "blocked": "fix",
    }.get(status or "")


def parse_json_list(value: Optional[str]) -> list:
    if not value:
        return []
    try:
        data = json.loads(value)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def first_json_value(value: Optional[str]) -> Optional[str]:
    data = parse_json_list(value)
    return safe_text(data[0], None) if data else None


def safe_text(value, fallback: Optional[str] = "暂无") -> Optional[str]:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        return text or fallback
    if isinstance(value, list):
        parts = safe_text_list(value)
        return "、".join(parts) if parts else fallback
    if isinstance(value, dict):
        for key in ["reason", "message", "title", "text", "name", "code"]:
            if key in value:
                text = safe_text(value.get(key), None)
                if text:
                    return text
        return "存在阻塞项"
    return fallback


def safe_text_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(safe_text_list(item))
        return items
    text = safe_text(value, None)
    return [text] if text else []


def clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def safe_excerpt(value: Optional[str], limit: int = 160) -> Optional[str]:
    clean = clean_text(value)
    if not clean:
        return None
    return clean[:limit]


def parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except Exception:
        return None


def date_from_iso(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except Exception:
        return parse_date(value)


def iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None
