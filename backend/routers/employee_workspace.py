from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..employee_workspace import build_employee_home
from ..deploy_models import DeployRecord
from ..models import AiEmployee, TaskCenterAuditLog, TaskCenterTask
from ..orchestrator_models import OrchestratorAnalysisRecord, OrchestratorTaskLink


router = APIRouter(prefix="/api/employee-workspace")

PRIVILEGED_ROLES = {"owner", "admin"}
WORKSPACE_STATUSES = {
    "standby",
    "running",
    "reviewing",
    "auditing",
    "deploying",
    "completed",
    "blocked",
    "pending_boss",
}
TASK_STATUS_TO_WORKSPACE = {
    "created": "standby",
    "pending": "standby",
    "assigned": "standby",
    "in_progress": "running",
    "running": "running",
    "submitted": "reviewing",
    "result_submitted": "reviewing",
    "reviewing": "reviewing",
    "audited": "completed",
    "accepted": "completed",
    "completed": "completed",
    "summarized": "completed",
    "rejected": "blocked",
    "failed": "blocked",
    "blocked": "blocked",
}
TASK_PROGRESS = {
    "created": 0,
    "pending": 0,
    "assigned": 0,
    "in_progress": 50,
    "running": 50,
    "submitted": 75,
    "result_submitted": 75,
    "reviewing": 75,
    "audited": 100,
    "accepted": 100,
    "completed": 100,
    "summarized": 100,
    "rejected": 20,
    "failed": 20,
    "blocked": 20,
}
BLOCKER_REASONS = {
    "rejected": "任务被驳回",
    "failed": "任务失败",
    "blocked": "任务阻塞",
}
NEXT_SUGGESTIONS = {
    "created": "等待老板确认或分配",
    "pending": "等待处理",
    "assigned": "等待开始任务",
    "in_progress": "继续执行任务",
    "running": "继续执行任务",
    "submitted": "等待天检验收",
    "result_submitted": "等待天检验收",
    "reviewing": "验收中",
    "audited": "等待最终确认",
    "accepted": "任务已完成",
    "completed": "任务已完成",
    "summarized": "任务已完成",
    "rejected": "需要修复后重新提交",
    "failed": "需要排查失败原因",
    "blocked": "需要处理阻塞原因",
}
REVIEW_STATUSES = {"submitted", "result_submitted", "reviewing"}
AUDIT_STATUSES = {"accepted"}
BOSS_CONFIRM_STATUSES = {"created"}
DEPLOY_PENDING_STATUSES = {"initialized", "pending", "running", "failed", "error"}
DEPLOYING_STATUSES = {"initialized", "pending", "running"}


@router.get("/overview")
def get_employee_workspace_overview(request: Request, db: Session = Depends(get_db)):
    require_employee_workspace_user(request, db)
    return build_employee_workspace_overview(db)


@router.get("/employees/{employee_code}/home")
def get_employee_workspace_home(employee_code: str, request: Request, db: Session = Depends(get_db)):
    require_employee_home_access(request, db, employee_code)
    return build_employee_home(db, employee_code)


def require_employee_workspace_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in PRIVILEGED_ROLES:
        raise HTTPException(status_code=403, detail="no employee workspace permission")
    return user


def require_employee_home_access(request: Request, db: Session, employee_code: str):
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role in PRIVILEGED_ROLES:
        return user
    if user.username == employee_code:
        return user
    raise HTTPException(status_code=403, detail="no employee workspace permission")


def build_employee_workspace_overview(db: Session):
    employees = (
        db.query(AiEmployee)
        .filter(AiEmployee.is_legacy.is_(False))
        .order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc())
        .all()
    )
    tasks = db.query(TaskCenterTask).order_by(TaskCenterTask.id.desc()).all()
    latest_tasks = latest_task_by_employee(tasks)
    latest_orchestrator = latest_orchestrator_by_employee(db)
    latest_deploy = db.query(DeployRecord).order_by(DeployRecord.id.desc()).first()

    employee_rows = [
        employee_to_workspace_row(
            employee,
            latest_tasks.get(employee.employee_code),
            latest_orchestrator.get(employee.employee_code),
            latest_deploy,
        )
        for employee in employees
    ]

    blockers = [blocker_item(row) for row in employee_rows if row["has_blocker"]]
    pending_reviews = [task_pending_item(task, "review") for task in tasks if task.status in REVIEW_STATUSES]
    pending_audits = [task_pending_item(task, "audit") for task in tasks if task.status in AUDIT_STATUSES]
    pending_deploys = deploy_pending_items(latest_deploy)
    recent_actions = build_recent_actions(db, tasks)

    return {
        "summary": build_summary(db, employee_rows, tasks, pending_reviews, pending_audits, pending_deploys),
        "employees": employee_rows,
        "blockers": blockers,
        "pending_reviews": pending_reviews,
        "pending_audits": pending_audits,
        "pending_deploys": pending_deploys,
        "recent_actions": recent_actions,
    }


def latest_task_by_employee(tasks: list[TaskCenterTask]) -> dict[str, TaskCenterTask]:
    latest: dict[str, TaskCenterTask] = {}
    for task in tasks:
        code = task.assigned_ai_employee_code
        if not code or code in latest:
            continue
        latest[code] = task
    return latest


def latest_orchestrator_by_employee(db: Session) -> dict[str, OrchestratorAnalysisRecord]:
    rows = db.query(OrchestratorAnalysisRecord).order_by(OrchestratorAnalysisRecord.id.desc()).limit(200).all()
    latest: dict[str, OrchestratorAnalysisRecord] = {}
    for row in rows:
        for code in [row.recommended_codex, row.detected_employee_code]:
            if code and code not in latest:
                latest[code] = row
    return latest


def employee_to_workspace_row(
    employee: AiEmployee,
    task: TaskCenterTask | None,
    analysis: OrchestratorAnalysisRecord | None,
    deploy: DeployRecord | None,
):
    has_blocker = task_has_blocker(task) if task else bool(analysis and (analysis.has_blocker or analysis.needs_fix))
    employee_deploy = deploy if deploy and deploy.operator == employee.employee_code else None
    status = resolve_workspace_status(task, analysis, employee_deploy, has_blocker)
    current_task = task.title if task else None
    sprint = (analysis.detected_sprint if analysis else None) or "Sprint 7"
    stage = (analysis.detected_stage if analysis else None) or stage_from_task(task)
    last_updated_at = latest_iso([task.updated_at if task else None, analysis.created_at if analysis else None, employee_deploy.updated_at if employee_deploy else None])
    return {
        "employee_name": employee.employee_name,
        "employee_code": employee.employee_code,
        "department": employee.legion,
        "role": first_json_value(employee.task_types),
        "status": status,
        "current_task": current_task,
        "task_id": task.id if task else None,
        "sprint": sprint,
        "stage": stage,
        "progress_percent": progress_for_status(task.status if task else None, status),
        "last_action": resolve_last_action(task, analysis, employee_deploy),
        "last_updated_at": last_updated_at,
        "has_blocker": has_blocker,
        "blocker_reason": resolve_blocker_reason(task, analysis, has_blocker),
        "next_suggestion": resolve_next_suggestion(status, task, analysis),
        "needs_boss_confirmation": bool(task and task.status in BOSS_CONFIRM_STATUSES),
        "review_status": review_status_for_task(task),
        "audit_status": audit_status_for_task(task),
        "deploy_status": employee_deploy.status if employee_deploy else None,
        "recent_orchestrator_source": orchestrator_source(analysis),
        "recent_git_commit": git_commit_summary(employee_deploy, employee.employee_code),
    }


def resolve_workspace_status(
    task: TaskCenterTask | None,
    analysis: OrchestratorAnalysisRecord | None,
    deploy: DeployRecord | None,
    has_blocker: bool,
) -> str:
    if has_blocker:
        return "blocked"
    if task:
        return TASK_STATUS_TO_WORKSPACE.get(task.status, "standby")
    if deploy and deploy.status in DEPLOYING_STATUSES:
        return "deploying"
    if analysis and analysis.completion_status == "completed":
        return "completed"
    return "standby"


def stage_from_task(task: TaskCenterTask | None) -> str | None:
    if not task:
        return None
    return {
        "created": "planning",
        "pending": "planning",
        "split": "planning",
        "assigned": "execution",
        "in_progress": "execution",
        "running": "execution",
        "submitted": "testing",
        "result_submitted": "testing",
        "reviewing": "testing",
        "accepted": "audit",
        "audited": "summary",
        "completed": "completed",
        "summarized": "completed",
        "rejected": "fix",
        "failed": "fix",
        "blocked": "fix",
    }.get(task.status)


def progress_for_status(task_status: str | None, workspace_status: str) -> int:
    return TASK_PROGRESS.get(task_status or "", 0)


def resolve_last_action(task: TaskCenterTask | None, analysis: OrchestratorAnalysisRecord | None, deploy: DeployRecord | None) -> str:
    candidates = [
        (task.updated_at if task else None, f"任务状态：{task.status}" if task else None),
        (analysis.created_at if analysis else None, f"Orchestrator 建议：{analysis.recommended_action or '暂无'}" if analysis else None),
        (deploy.updated_at if deploy else None, f"部署状态：{deploy.status}" if deploy else None),
    ]
    latest = max((item for item in candidates if item[0] and item[1]), default=None, key=lambda item: item[0])
    return latest[1] if latest else "暂无"


def resolve_blocker_reason(task: TaskCenterTask | None, analysis: OrchestratorAnalysisRecord | None, has_blocker: bool) -> str | None:
    if not has_blocker:
        return None
    if task and task.status in BLOCKER_REASONS:
        return BLOCKER_REASONS[task.status]
    if analysis and analysis.has_blocker:
        flags = parse_json_list(analysis.safety_flags_json)
        return "、".join(flags) if flags else "Orchestrator 检测到阻断"
    if analysis and analysis.needs_fix:
        return "Orchestrator 建议修复"
    return "存在阻塞"


def resolve_next_suggestion(status: str, task: TaskCenterTask | None, analysis: OrchestratorAnalysisRecord | None) -> str:
    if task:
        return NEXT_SUGGESTIONS.get(task.status, "等待处理")
    if status == "auditing":
        return "等待天监审计"
    if status == "deploying":
        return "等待天盾部署"
    if status == "running":
        return "继续执行当前任务"
    if status == "completed":
        return analysis.recommended_action if analysis and analysis.recommended_action else "等待下一步安排"
    return "等待任务"


def review_status_for_task(task: TaskCenterTask | None) -> str | None:
    if not task:
        return None
    if task.status in REVIEW_STATUSES:
        return "pending"
    if task.status in {"accepted", "audited", "completed", "summarized"}:
        return "accepted"
    if task.status == "rejected":
        return "rejected"
    return None


def audit_status_for_task(task: TaskCenterTask | None) -> str | None:
    if not task:
        return None
    if task.status == "accepted":
        return "pending"
    if task.status in {"audited", "completed", "summarized"}:
        return "audited"
    return None


def task_has_blocker(task: TaskCenterTask | None) -> bool:
    return bool(task and task.status in BLOCKER_REASONS)


def orchestrator_source(analysis: OrchestratorAnalysisRecord | None) -> dict | None:
    if not analysis:
        return None
    return {
        "analysis_id": analysis.id,
        "detected_employee_name": analysis.detected_employee_name,
        "detected_sprint": analysis.detected_sprint,
        "detected_stage": analysis.detected_stage,
        "completion_status": analysis.completion_status,
        "recommended_codex": analysis.recommended_codex,
        "recommended_action": analysis.recommended_action,
        "has_blocker": analysis.has_blocker,
        "needs_fix": analysis.needs_fix,
        "safety_flags": parse_json_list(analysis.safety_flags_json),
        "created_at": iso(analysis.created_at),
    }


def git_commit_summary(deploy: DeployRecord | None, employee_code: str) -> dict | None:
    if not deploy or deploy.operator != employee_code or not deploy.commit_hash:
        return None
    return {
        "commit_hash": deploy.commit_hash,
        "branch": deploy.branch,
        "created_at": iso(deploy.created_at),
    }


def build_summary(
    db: Session,
    employees: list[dict],
    tasks: list[TaskCenterTask],
    pending_reviews: list[dict],
    pending_audits: list[dict],
    pending_deploys: list[dict],
):
    counts = {status: 0 for status in WORKSPACE_STATUSES}
    for row in employees:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "total_employees": len(employees),
        "standby_count": counts.get("standby", 0),
        "running_count": counts.get("running", 0),
        "reviewing_count": counts.get("reviewing", 0),
        "completed_count": counts.get("completed", 0),
        "blocked_count": counts.get("blocked", 0),
        "current_sprint": current_sprint(db) or "Sprint 7",
        "today_tasks": today_task_count(db),
        "pending_boss_confirmations": sum(1 for task in tasks if task.status in BOSS_CONFIRM_STATUSES),
        "pending_test_reviews": len(pending_reviews),
        "pending_audits": len(pending_audits),
        "pending_deploys": len(pending_deploys),
    }


def current_sprint(db: Session) -> str | None:
    latest = (
        db.query(OrchestratorAnalysisRecord.detected_sprint)
        .filter(OrchestratorAnalysisRecord.detected_sprint.isnot(None))
        .order_by(OrchestratorAnalysisRecord.id.desc())
        .first()
    )
    return latest[0] if latest else None


def today_task_count(db: Session) -> int:
    start = datetime.now(timezone.utc).date().isoformat()
    return db.query(func.count(TaskCenterTask.id)).filter(func.date(TaskCenterTask.created_at) == start).scalar() or 0


def blocker_item(row: dict) -> dict:
    return {
        "employee_code": row["employee_code"],
        "employee_name": row["employee_name"],
        "task_id": row["task_id"],
        "reason": row["blocker_reason"] or "存在阻塞",
        "source": "orchestrator" if row["recent_orchestrator_source"] else "task_center",
        "created_at": row["last_updated_at"],
    }


def task_pending_item(task: TaskCenterTask, pending_type: str) -> dict:
    return {
        "task_id": task.id,
        "title": task.title,
        "employee_code": task.assigned_ai_employee_code,
        "employee_name": task.assigned_ai_employee_name,
        "status": task.status,
        "priority": task.priority,
        "type": pending_type,
        "created_at": iso(task.created_at),
        "updated_at": iso(task.updated_at),
    }


def deploy_pending_items(deploy: DeployRecord | None) -> list[dict]:
    if not deploy or deploy.status not in DEPLOY_PENDING_STATUSES:
        return []
    return [
        {
            "deploy_id": deploy.id,
            "task_id": None,
            "title": deploy.deploy_version or "等待部署处理",
            "status": deploy.status,
            "environment": "production",
            "created_at": iso(deploy.created_at),
            "updated_at": iso(deploy.updated_at),
        }
    ]


def build_recent_actions(db: Session, tasks: list[TaskCenterTask]) -> list[dict]:
    actions = []
    audit_logs = db.query(TaskCenterAuditLog).order_by(TaskCenterAuditLog.id.desc()).limit(10).all()
    task_by_id = {task.id: task for task in tasks}
    for row in audit_logs:
        task = task_by_id.get(row.task_id)
        actions.append(
            {
                "type": "task_audit",
                "employee_code": task.assigned_ai_employee_code if task else None,
                "employee_name": task.assigned_ai_employee_name if task else None,
                "task_id": row.task_id,
                "title": row.action,
                "status": row.to_status,
                "at": iso(row.created_at),
            }
        )

    links = db.query(OrchestratorTaskLink).order_by(OrchestratorTaskLink.id.desc()).limit(10).all()
    for link in links:
        actions.append(
            {
                "type": "orchestrator_link",
                "employee_code": link.recommended_codex,
                "employee_name": None,
                "task_id": link.task_id,
                "title": "Orchestrator 来源链路",
                "status": link.link_type,
                "at": iso(link.created_at),
            }
        )

    actions.sort(key=lambda item: item["at"] or "", reverse=True)
    return actions[:12]


def first_json_value(value: str | None) -> str | None:
    data = parse_json_list(value)
    return str(data[0]) if data else None


def parse_json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        data = json.loads(value)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def latest_iso(values: list[datetime | None]) -> str | None:
    clean = [value for value in values if value]
    return iso(max(clean)) if clean else None


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
