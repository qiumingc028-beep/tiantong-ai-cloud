from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..deploy_models import DeployHealthCheck, DeployRecord
from ..employee_command_dashboard import build_employee_command_dashboard, build_employee_detail
from ..employee_organization import build_employee_organization_center
from ..employee_performance import build_ai_employee_business_board
from ..models import AiEmployee, TaskCenterTask
from . import deploy_center


router = APIRouter(prefix="/api/ceo-dashboard")

TASK_STATUSES = [
    "created",
    "split",
    "assigned",
    "running",
    "result_submitted",
    "accepted",
    "rejected",
    "audited",
    "summarized",
]
PENDING_STATUSES = ["created", "split", "assigned", "running", "result_submitted", "accepted", "rejected", "audited"]
EXPECTED_ALEMBIC_VERSION = deploy_center.EXPECTED_ALEMBIC_VERSION


@router.get("/summary")
def get_ceo_dashboard_summary(request: Request, db: Session = Depends(get_db)):
    require_ceo_dashboard_user(request, db)
    return build_ceo_dashboard_summary(db)


@router.get("/employee-command-dashboard")
def get_employee_command_dashboard(request: Request, db: Session = Depends(get_db)):
    require_ceo_dashboard_user(request, db)
    return build_employee_command_dashboard(db)


@router.get("/employee-command-dashboard/employees/{employee_code}")
def get_employee_command_dashboard_detail(employee_code: str, request: Request, db: Session = Depends(get_db)):
    require_ceo_dashboard_user(request, db)
    return build_employee_detail(db, employee_code)


def require_ceo_dashboard_user(request: Request, db: Session):
    user = current_user(request, db)
    role_code = normalize_role(user.role)
    if role_code not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="no CEO dashboard permission")
    return user


def build_ceo_dashboard_summary(db: Session):
    system_health = build_system_health(db)
    task_summary = build_task_summary(db)
    employee_summary = build_employee_summary(db)
    deploy_summary = build_deploy_summary(db, system_health)
    ai_employee_business_board = build_ai_employee_business_board(db)
    ai_employee_organization_board = build_employee_organization_center(db)
    ai_employee_command_dashboard = build_employee_command_dashboard(db)
    pending_actions = build_pending_actions(task_summary, system_health, deploy_summary)
    alerts = build_alerts(system_health, task_summary, employee_summary, deploy_summary, pending_actions)
    return {
        "overall_status": resolve_overall_status(alerts, pending_actions),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "system_health": system_health,
        "task_summary": task_summary,
        "pending_actions": pending_actions,
        "employee_summary": employee_summary,
        "ai_employee_business_board": ai_employee_business_board,
        "ai_employee_organization_board": ai_employee_organization_board,
        "ai_employee_command_dashboard": ai_employee_command_dashboard,
        "deploy_summary": deploy_summary,
        "alerts": alerts,
    }


def build_system_health(db: Session):
    database = deploy_center.check_database(db)
    redis = deploy_center.check_redis()
    migration = deploy_center.check_migration(db)
    return {
        "backend": "healthy",
        "database": database["status"],
        "redis": redis["status"],
        "migration": migration["status"],
    }


def build_task_summary(db: Session):
    counts = {status: 0 for status in TASK_STATUSES}
    rows = db.query(TaskCenterTask.status, func.count(TaskCenterTask.id)).group_by(TaskCenterTask.status).all()
    total = 0
    for status, count in rows:
        total += count
        if status in counts:
            counts[status] = count
    pending_count = sum(counts[status] for status in PENDING_STATUSES)
    recent_tasks = (
        db.query(TaskCenterTask)
        .filter(TaskCenterTask.status.in_(PENDING_STATUSES))
        .order_by(TaskCenterTask.id.desc())
        .limit(8)
        .all()
    )
    return {
        "total": total,
        **counts,
        "pending_count": pending_count,
        "recent_pending_tasks": [task_brief(task) for task in recent_tasks],
    }


def build_employee_summary(db: Session):
    total = db.query(func.count(AiEmployee.id)).scalar() or 0
    active = db.query(func.count(AiEmployee.id)).filter(AiEmployee.status == "active").scalar() or 0
    inactive = db.query(func.count(AiEmployee.id)).filter(AiEmployee.status == "inactive").scalar() or 0
    legions = db.query(func.count(func.distinct(AiEmployee.legion))).filter(AiEmployee.legion.isnot(None)).scalar() or 0
    active_employees = (
        db.query(AiEmployee)
        .filter(AiEmployee.status == "active", AiEmployee.is_legacy.is_(False))
        .order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc())
        .limit(12)
        .all()
    )
    return {
        "total": total,
        "active": active,
        "inactive": inactive,
        "legions": legions,
        "active_employees": [employee_brief(employee) for employee in active_employees],
    }


def build_deploy_summary(db: Session, system_health: dict):
    alembic_version = deploy_center.get_current_alembic_version(db)
    last_record = db.query(DeployRecord).order_by(DeployRecord.id.desc()).first()
    last_check = db.query(DeployHealthCheck).order_by(DeployHealthCheck.id.desc()).first()
    statuses = [system_health["database"], system_health["redis"], system_health["migration"]]
    return {
        "overall_status": normalize_deploy_status(statuses),
        "database_status": system_health["database"],
        "redis_status": system_health["redis"],
        "alembic_version": alembic_version,
        "expected_version": EXPECTED_ALEMBIC_VERSION,
        "last_deploy_status": last_record.status if last_record else None,
        "last_health_check_status": last_check.status if last_check else None,
    }


def build_pending_actions(task_summary: dict, system_health: dict, deploy_summary: dict):
    actions = []
    if any(system_health[key] not in {"healthy", "running"} for key in ("backend", "database", "redis")):
        actions.append(action("critical", "system_health", "系统健康异常，需要查看天盾部署中心"))
    if deploy_summary["alembic_version"] != deploy_summary["expected_version"]:
        actions.append(action("critical", "migration", "数据库迁移版本不一致，需要检查"))
    if task_summary["rejected"] > 0:
        actions.append(action("warning", "rejected", "有任务验收未通过，需要重新处理", task_summary["rejected"]))
    if task_summary["result_submitted"] > 0:
        actions.append(action("warning", "result_submitted", "有任务等待天检验收", task_summary["result_submitted"]))
    if task_summary["accepted"] > 0:
        actions.append(action("normal", "accepted", "有任务等待天监审计", task_summary["accepted"]))
    if task_summary["audited"] > 0:
        actions.append(action("normal", "audited", "有任务等待天统汇总", task_summary["audited"]))
    if task_summary["split"] > 0:
        actions.append(action("normal", "split", "有任务等待分配 AI 员工", task_summary["split"]))
    if task_summary["created"] > 0:
        actions.append(action("normal", "created", "有任务等待天统拆解", task_summary["created"]))
    return actions[:8]


def build_alerts(system_health: dict, task_summary: dict, employee_summary: dict, deploy_summary: dict, pending_actions: list[dict]):
    alerts = []
    if system_health["backend"] not in {"healthy", "running"}:
        alerts.append(alert("critical", "backend", "backend 异常"))
    if system_health["database"] != "healthy":
        alerts.append(alert("critical", "database", "database 异常"))
    if system_health["redis"] != "healthy":
        alerts.append(alert("critical", "redis", "Redis 异常"))
    if deploy_summary["alembic_version"] != deploy_summary["expected_version"] or system_health["migration"] != "healthy":
        alerts.append(alert("warning", "migration", "数据库迁移版本不一致"))
    if task_summary["rejected"] > 0:
        alerts.append(alert("warning", "rejected_tasks", "有验收未通过任务"))
    if task_summary["result_submitted"] > 0:
        alerts.append(alert("warning", "result_submitted", "有任务等待验收"))
    if employee_summary["active"] == 0:
        alerts.append(alert("critical", "active_employees", "active AI员工为 0"))
    if employee_summary["inactive"] > 0:
        alerts.append(alert("info", "inactive_employees", "存在停用 AI员工"))
    if not alerts and not pending_actions:
        alerts.append(alert("info", "system_normal", "系统运行正常"))
    return alerts


def resolve_overall_status(alerts: list[dict], pending_actions: list[dict]):
    if any(item["level"] == "critical" for item in alerts + pending_actions):
        return "critical"
    if any(item["level"] == "warning" for item in alerts + pending_actions):
        return "warning"
    return "normal"


def normalize_deploy_status(statuses: list[str]):
    if any(status == "unhealthy" for status in statuses):
        return "unhealthy"
    if any(status in {"warning", "unknown"} for status in statuses):
        return "degraded"
    return "healthy"


def action(level: str, action_type: str, message: str, count: int | None = None):
    data = {"level": level, "type": action_type, "message": message}
    if count is not None:
        data["count"] = count
    return data


def alert(level: str, alert_type: str, message: str):
    return {"level": level, "type": alert_type, "message": message}


def task_brief(task: TaskCenterTask):
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "assigned_ai_employee_code": task.assigned_ai_employee_code,
        "assigned_ai_employee_name": task.assigned_ai_employee_name,
    }


def employee_brief(employee: AiEmployee):
    return {
        "employee_code": employee.employee_code,
        "employee_name": employee.employee_name,
        "legion": employee.legion,
        "status": employee.status,
    }
