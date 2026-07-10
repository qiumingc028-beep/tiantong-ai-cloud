from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from .. import database
from ..database import get_db
from ..deploy_models import DeployRecord
from ..models import (
    AiEmployee,
    EmployeeLog,
    KnowledgeArticle,
    KnowledgeFile,
    PromptLibrary,
    SopLibrary,
    TaskCenterAuditLog,
    TaskCenterTask,
)


router = APIRouter(prefix="/api/enterprise-brain-console")

ALLOWED_ROLES = {"owner", "admin", "boss"}
CURRENT_SPRINT = "Sprint59"
ACTIVE_TASK_STATUSES = {"assigned", "running"}
PENDING_REVIEW_STATUSES = {"result_submitted", "accepted"}
BLOCKED_TASK_STATUSES = {"rejected", "failed", "blocked"}
RISK_TASK_STATUSES = BLOCKED_TASK_STATUSES | {"created", "split"}


@router.get("/overview")
def get_enterprise_brain_console_overview(request: Request, db: Session = Depends(get_db)):
    user = require_enterprise_brain_console_user(request, db)
    return build_enterprise_brain_console_overview(db, user)


def require_enterprise_brain_console_user(request: Request, db: Session):
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="no enterprise brain console permission")
    return user


def build_enterprise_brain_console_overview(db: Session, user) -> dict:
    employee_summary = build_employee_summary(db)
    task_summary = build_task_summary(db)
    risk_summary = build_risk_summary(db, employee_summary, task_summary)
    pending_confirmations = build_pending_confirmations(db)
    system_health = build_system_health(db)
    return {
        "readonly": True,
        "mode": "readonly",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "system": {
            "name": "天统AI企业大脑",
            "version": "V1",
            "current_sprint": CURRENT_SPRINT,
            "security_mode": "readonly",
            "description": "企业大脑总控台只读骨架",
        },
        "current_user": {
            "username": user.username,
            "role": normalize_role(user.role),
            "display_name": user.display_name,
        },
        "boss_dashboard": {
            "employee_summary": employee_summary,
            "task_summary": task_summary,
            "risk_summary": risk_summary,
            "pending_confirmations": pending_confirmations,
            "system_health": system_health,
        },
        "system_health": system_health,
        "centers": center_entries(db),
        "recent_activities": build_recent_activities(db),
        "empty_state": {
            "title": "未接入真实业务数据" if no_business_data(employee_summary, task_summary) else "已接入本地系统只读数据",
            "message": "未接入真实业务数据；当前仅聚合本地AI员工、Task Center和系统健康状态。" if no_business_data(employee_summary, task_summary) else "当前展示本地系统只读聚合数据，不接外部真实业务平台。",
            "no_real_business_data": no_business_data(employee_summary, task_summary),
        },
        "safety": {
            "readonly_mode": True,
            "auto_execute": False,
            "external_platform_connected": False,
            "openclaw_connected": False,
            "n8n_connected": False,
            "execution_engine_called": False,
            "execution_engine_entry_visible": False,
            "database_migration_created": False,
            "new_database_tables_created": False,
            "requires_boss_confirm_for_high_risk": True,
            "requires_security_audit_for_high_risk": True,
            "high_risk_requires": {
                "boss_confirm": True,
                "security_audited": True,
            },
        },
    }


def build_employee_summary(db: Session) -> dict:
    employees = db.query(AiEmployee).filter(AiEmployee.is_legacy.is_(False)).all()
    total = len(employees)
    active = sum(1 for row in employees if row.status == "active")
    inactive = sum(1 for row in employees if row.status != "active")
    active_employee_codes = [row.employee_code for row in employees if row.status == "active"]
    active_tasks = []
    if active_employee_codes:
        active_tasks = (
            db.query(TaskCenterTask)
            .filter(TaskCenterTask.assigned_ai_employee_code.in_(active_employee_codes))
            .filter(TaskCenterTask.status.in_(ACTIVE_TASK_STATUSES))
            .all()
        )
    working_codes = {task.assigned_ai_employee_code for task in active_tasks if task.assigned_ai_employee_code}
    department_rows: dict[str, int] = {}
    for employee in employees:
        department = employee.legion or "未分配部门"
        department_rows[department] = department_rows.get(department, 0) + 1
    risk_employee_codes = {
        row.assigned_ai_employee_code
        for row in db.query(TaskCenterTask.assigned_ai_employee_code)
        .filter(TaskCenterTask.assigned_ai_employee_code.isnot(None))
        .filter(TaskCenterTask.status.in_(BLOCKED_TASK_STATUSES))
        .all()
        if row.assigned_ai_employee_code
    }
    return summary(
        "员工概况",
        total,
        {
            "total_employees": total,
            "active_count": active,
            "inactive_count": inactive,
            "working_count": len(working_codes),
            "idle_count": max(active - len(working_codes), 0),
            "department_distribution": [
                {"department": key, "count": value}
                for key, value in sorted(department_rows.items(), key=lambda item: item[0])
            ],
            "risk_employee_count": len(risk_employee_codes),
        },
    )


def build_task_summary(db: Session) -> dict:
    rows = db.query(TaskCenterTask.status, func.count(TaskCenterTask.id)).group_by(TaskCenterTask.status).all()
    status_counts = {status: int(count) for status, count in rows}
    total = sum(status_counts.values())
    return summary(
        "任务概况",
        total,
        {
            "total_tasks": total,
            "running_count": sum(status_counts.get(status, 0) for status in ACTIVE_TASK_STATUSES),
            "pending_review_count": sum(status_counts.get(status, 0) for status in PENDING_REVIEW_STATUSES),
            "blocked_count": sum(status_counts.get(status, 0) for status in BLOCKED_TASK_STATUSES),
            "status_distribution": [
                {"status": status, "count": count}
                for status, count in sorted(status_counts.items(), key=lambda item: item[0])
            ],
        },
    )


def build_risk_summary(db: Session, employee_summary: dict, task_summary: dict) -> dict:
    blocked_tasks = task_summary["metrics"].get("blocked_count", 0)
    risk_tasks = db.query(TaskCenterTask).filter(TaskCenterTask.status.in_(RISK_TASK_STATUSES)).order_by(TaskCenterTask.id.desc()).limit(5).all()
    total_risks = blocked_tasks + employee_summary["metrics"].get("risk_employee_count", 0)
    return summary(
        "风险概况",
        total_risks,
        {
            "risk_employee_count": employee_summary["metrics"].get("risk_employee_count", 0),
            "blocked_task_count": blocked_tasks,
            "risk_items": [task_brief(task) for task in risk_tasks],
            "high_risk_requires": {
                "boss_confirm": True,
                "security_audited": True,
            },
        },
    )


def build_pending_confirmations(db: Session) -> dict:
    rows = (
        db.query(TaskCenterTask)
        .filter(TaskCenterTask.status.in_(["created", "split", "result_submitted", "accepted", "rejected", "blocked"]))
        .order_by(TaskCenterTask.updated_at.desc(), TaskCenterTask.id.desc())
        .limit(10)
        .all()
    )
    return summary(
        "待确认事项",
        len(rows),
        {
            "items": [task_brief(task) for task in rows],
            "pending_review_tasks": sum(1 for task in rows if task.status in PENDING_REVIEW_STATUSES),
            "risk_items": sum(1 for task in rows if task.status in BLOCKED_TASK_STATUSES),
            "confirmation_items": sum(1 for task in rows if task.status in {"created", "split"}),
        },
    )


def build_system_health(db: Session) -> dict:
    backend = health_item("Backend", "running", "FastAPI应用已响应总控台只读请求")
    database_status = "healthy"
    database_message = "SELECT 1 succeeded"
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        database_status = "unhealthy"
        database_message = str(exc)
    redis = check_redis_health()
    worker = check_worker_health()
    deploy = check_deploy_status(db)
    return {
        "title": "系统健康",
        "status": "ready",
        "message": "系统健康为只读检测，不触发部署或执行动作。",
        "items": [backend, health_item("Database", database_status, database_message), redis, worker, deploy],
    }


def check_redis_health() -> dict:
    try:
        ok = bool(database.get_redis().ping())
        return health_item("Redis", "healthy" if ok else "unhealthy", "redis ping succeeded" if ok else "redis ping failed")
    except Exception as exc:
        return health_item("Redis", "unknown", str(exc))


def check_worker_health() -> dict:
    try:
        raw = database.get_redis().get("tiantong:worker:heartbeat")
    except Exception as exc:
        return health_item("Worker", "unknown", str(exc))
    if not raw:
        return health_item("Worker", "unknown", "未发现worker heartbeat")
    return health_item("Worker", "running", f"last_seen_at={raw}")


def check_deploy_status(db: Session) -> dict:
    row = db.query(DeployRecord).order_by(DeployRecord.id.desc()).first()
    if not row:
        return health_item("Deploy", "empty", "暂无部署记录")
    return health_item("Deploy", row.status or "unknown", f"version={row.deploy_version or 'unknown'}")


def build_recent_activities(db: Session) -> list[dict]:
    activities: list[dict] = []
    task_audits = db.query(TaskCenterAuditLog).order_by(TaskCenterAuditLog.id.desc()).limit(8).all()
    deploy_records = db.query(DeployRecord).order_by(DeployRecord.id.desc()).limit(6).all()
    employee_logs = db.query(EmployeeLog).order_by(EmployeeLog.id.desc()).limit(8).all()
    for row in task_audits:
        activities.append(
            activity(
                "task_audit",
                f"Task Center: {row.action}",
                row.detail or f"任务 {row.task_id} 状态 {row.from_status or '-'} -> {row.to_status or '-'}",
                row.created_at,
                {"task_id": row.task_id, "actor_role": row.actor_role},
            )
        )
    for row in deploy_records:
        activities.append(
            activity(
                "deploy_record",
                f"Deploy Center: {row.status}",
                row.note or f"版本 {row.deploy_version or row.version or 'unknown'}",
                row.updated_at or row.created_at,
                {"deploy_id": row.deploy_id, "branch": row.branch},
            )
        )
    for row in employee_logs:
        activities.append(
            activity(
                "employee_activity",
                f"Employee Activity: {row.action}",
                row.detail or "员工活动记录",
                row.created_at,
                {"user_id": row.user_id},
            )
        )
    activities.sort(key=lambda item: item["created_at"] or "", reverse=True)
    return activities[:12]


def summary(title: str, count: int, metrics: dict) -> dict:
    return {
        "title": title,
        "status": "ready" if count else "empty",
        "message": "未接入真实业务数据" if count == 0 else "本地系统只读聚合",
        "count": count,
        "metrics": metrics,
    }


def health_item(name: str, status: str, message: str) -> dict:
    return {"name": name, "status": status, "message": message}


def task_brief(task: TaskCenterTask) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "assigned_ai_employee_code": task.assigned_ai_employee_code,
        "assigned_ai_employee_name": task.assigned_ai_employee_name,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def no_business_data(employee_summary: dict, task_summary: dict) -> bool:
    return employee_summary.get("count", 0) == 0 and task_summary.get("count", 0) == 0


def center_entries(db: Session) -> list[dict]:
    employee_count, employee_updated_at = count_and_latest(db, AiEmployee, AiEmployee.updated_at, AiEmployee.is_legacy.is_(False))
    task_count, task_updated_at = count_and_latest(db, TaskCenterTask, TaskCenterTask.updated_at)
    deploy_count, deploy_updated_at = count_and_latest(db, DeployRecord, DeployRecord.updated_at)
    knowledge_count = sum(
        count_rows(db, model)
        for model in [KnowledgeFile, KnowledgeArticle, SopLibrary, PromptLibrary]
    )
    knowledge_updated_at = latest_datetime(
        [
            latest_value(db, KnowledgeFile.updated_at),
            latest_value(db, KnowledgeArticle.updated_at),
            latest_value(db, SopLibrary.updated_at),
            latest_value(db, PromptLibrary.updated_at),
        ]
    )
    skill_count = count_rows(db, SopLibrary) + count_rows(db, PromptLibrary)
    return [
        center("AI员工工作台", "查看AI员工状态、任务、成长和风险", "/employee-workspace.html", "partial", "medium", employee_count, employee_updated_at),
        center("AI会议室", "多AI员工协作讨论、观点汇总和方案生成", "#", "designing", "medium", 0, None),
        center("Task Center", "任务事实来源和任务状态查看", "/task-center.html", "connected", "medium", task_count, task_updated_at),
        center("Skill Center", "技能资产、SOP和插件能力入口", "/sop-skill-center.html", "partial", "medium", skill_count, knowledge_updated_at),
        center("天藏 Knowledge OS", "知识、SOP、Prompt和案例资产", "/tiancang.html", "partial", "medium", knowledge_count, knowledge_updated_at),
        center("Organization", "组织、部门、岗位和权限边界", "/dashboard/organization.html", "partial", "medium", employee_count, employee_updated_at),
        center("Audit Center", "审计、安全报告和风险事件中心", "#", "designing", "high", count_rows(db, TaskCenterAuditLog), latest_value(db, TaskCenterAuditLog.created_at)),
        center("AI运营驾驶舱", "京东60店经营状态与分析入口", "/jd-dashboard.html", "partial", "medium", 0, None),
        center("Deploy Center", "部署健康、版本和迁移状态检查", "/deploy-center.html", "connected", "high", deploy_count, deploy_updated_at),
    ]


def center(name: str, description: str, url: str, status: str, risk_level: str, count: int, last_updated) -> dict:
    return {
        "name": name,
        "description": description,
        "url": url,
        "status": status,
        "count": int(count or 0),
        "last_updated": last_updated.isoformat() if last_updated else None,
        "risk_level": risk_level,
        "primary_action": "查看" if url != "#" else "设计中",
    }


def activity(source: str, title: str, summary: str, created_at, metadata: dict | None = None) -> dict:
    return {
        "source": source,
        "title": title,
        "summary": summary,
        "created_at": created_at.isoformat() if created_at else None,
        "metadata": metadata or {},
    }


def count_rows(db: Session, model, *filters) -> int:
    query = db.query(func.count(model.id))
    for condition in filters:
        query = query.filter(condition)
    return int(query.scalar() or 0)


def latest_value(db: Session, column, *filters):
    model = column.class_
    query = db.query(func.max(column))
    for condition in filters:
        query = query.filter(condition)
    return query.scalar()


def count_and_latest(db: Session, model, latest_column, *filters) -> tuple[int, object | None]:
    return count_rows(db, model, *filters), latest_value(db, latest_column, *filters)


def latest_datetime(values: list) -> object | None:
    clean = [value for value in values if value]
    return max(clean) if clean else None
