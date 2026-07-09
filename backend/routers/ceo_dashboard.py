from __future__ import annotations

from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..brain_execution.models import BrainExecutionRun, BrainWorkerStatus
from ..brain_execution.queue import get_queue_status
from ..database import get_db
from ..deploy_models import DeployHealthCheck, DeployRecord, HealthCheckRecord
from ..employee_command_dashboard import build_employee_command_dashboard, build_employee_detail
from ..employee_organization import build_employee_organization_center
from ..employee_performance import build_ai_employee_business_board
from ..models import AiEmployee, TaskCenterTask
from ..workers.tian_shang_worker import latest_tian_shang_status
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


@router.get("/daily-operations")
def get_daily_operations(request: Request, db: Session = Depends(get_db)):
    require_ceo_dashboard_user(request, db)
    return build_daily_operations(db)


@router.get("/daily-summary")
def get_daily_summary(request: Request, db: Session = Depends(get_db)):
    require_ceo_dashboard_user(request, db)
    return build_daily_summary(db)


@router.get("/deployment-history")
def get_deployment_history(request: Request, limit: int = 8, db: Session = Depends(get_db)):
    require_ceo_dashboard_user(request, db)
    return build_deployment_history(db, limit)


@router.get("/latest-deploy")
def get_latest_deploy(request: Request, db: Session = Depends(get_db)):
    require_ceo_dashboard_user(request, db)
    return {"latest_deploy": latest_deploy_summary(db)}


@router.get("/health-check-history")
def get_health_check_history(request: Request, limit: int = 20, db: Session = Depends(get_db)):
    require_ceo_dashboard_user(request, db)
    return build_health_check_history(db, limit)


@router.get("/employee-command-dashboard")
def get_employee_command_dashboard(request: Request, db: Session = Depends(get_db)):
    require_ceo_dashboard_user(request, db)
    return build_employee_command_dashboard(db)


@router.get("/employee-command-dashboard/employees/{employee_code}")
def get_employee_command_dashboard_detail(employee_code: str, request: Request, db: Session = Depends(get_db)):
    require_ceo_dashboard_user(request, db)
    return build_employee_detail(db, employee_code)


@router.get("/brain-execution-summary")
def get_brain_execution_summary(request: Request, db: Session = Depends(get_db)):
    require_ceo_dashboard_user(request, db)
    return build_brain_execution_summary(db)


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
    tian_shang_execution = latest_tian_shang_status(db)
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
        "tian_shang_execution": tian_shang_execution,
        "deploy_summary": deploy_summary,
        "alerts": alerts,
    }


def build_daily_operations(db: Session) -> dict:
    data = build_daily_summary(db)
    return {
        **data,
        "forbidden_actions": ["auto_execute", "auto_deploy", "permission_change", "external_api_call"],
    }


def build_daily_summary(db: Session) -> dict:
    system_health = build_system_health(db)
    deploy_summary = build_deploy_summary(db, system_health)
    task_summary = build_task_summary(db)
    employee_summary = build_employee_summary(db)
    today_summary = build_today_task_summary(db)
    pending_confirmations = build_pending_actions(task_summary, system_health, deploy_summary)
    risk_alerts = build_alerts(system_health, task_summary, employee_summary, deploy_summary, pending_confirmations)
    running_employee_codes = running_task_employee_codes(db)
    active_count = employee_summary["active"]
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "readonly": True,
        "system_status": {
            "overall": resolve_overall_status(risk_alerts, pending_confirmations),
            "backend": system_health["backend"],
            "database": system_health["database"],
            "redis": system_health["redis"],
            "migration": system_health["migration"],
        },
        "employee_summary": {
            "total": employee_summary["total"],
            "active": active_count,
            "inactive": employee_summary["inactive"],
            "running": len(running_employee_codes),
            "idle": max(active_count - len(running_employee_codes), 0),
            "error": 0,
        },
        "task_summary": today_summary,
        "pending_confirmations": pending_confirmations,
        "risk_alerts": risk_alerts,
        "recent_failed_tasks": recent_failed_tasks(db),
    }


def build_brain_execution_summary(db: Session) -> dict:
    rows = db.query(BrainExecutionRun.status, func.count(BrainExecutionRun.id)).group_by(BrainExecutionRun.status).all()
    counts = {status: count for status, count in rows}
    success = counts.get("SUCCESS", 0)
    failed = counts.get("FAILED", 0)
    timeout = counts.get("TIMEOUT", 0)
    finished = success + failed + timeout
    workers = db.query(BrainWorkerStatus).order_by(BrainWorkerStatus.worker_id.asc()).all()
    recent_failures = (
        db.query(BrainExecutionRun)
        .filter(BrainExecutionRun.status.in_(["FAILED", "TIMEOUT"]))
        .order_by(BrainExecutionRun.finished_at.desc(), BrainExecutionRun.id.desc())
        .limit(8)
        .all()
    )
    durations = [
        (row.finished_at - row.started_at).total_seconds()
        for row in db.query(BrainExecutionRun).filter(BrainExecutionRun.started_at.isnot(None), BrainExecutionRun.finished_at.isnot(None)).all()
        if row.finished_at and row.started_at
    ]
    queue_status = get_queue_status()
    return {
        "readonly": True,
        "mode": "simulation",
        "current_execution_count": counts.get("RUNNING", 0),
        "queued_count": counts.get("QUEUED", 0) + int(queue_status.get("waiting", 0)),
        "worker_count": len(workers),
        "worker_statuses": [brain_worker_summary(row) for row in workers],
        "success_rate": round(success / finished * 100, 2) if finished else 0,
        "failed_count": failed,
        "timeout_count": timeout,
        "average_execution_seconds": round(sum(durations) / len(durations), 2) if durations else 0,
        "queue_status": queue_status,
        "status_counts": counts,
        "recent_failures": [brain_execution_failure_summary(row) for row in recent_failures],
        "forbidden_actions": ["shell", "external_api", "auto_install_skill", "code_change", "deploy"],
    }


def build_today_task_summary(db: Session) -> dict:
    start = today_start_utc()
    rows = (
        db.query(TaskCenterTask.status, func.count(TaskCenterTask.id))
        .filter(TaskCenterTask.created_at >= start)
        .group_by(TaskCenterTask.status)
        .all()
    )
    counts = {status: count for status, count in rows}
    completed = sum(counts.get(status, 0) for status in ["summarized", "accepted", "audited"])
    pending = sum(counts.get(status, 0) for status in ["created", "split"])
    return {
        "today_total": sum(counts.values()),
        "pending": pending,
        "assigned": counts.get("assigned", 0),
        "running": counts.get("running", 0),
        "completed": completed,
        "failed": counts.get("rejected", 0),
        "result_submitted": counts.get("result_submitted", 0),
    }


def running_task_employee_codes(db: Session) -> set[str]:
    rows = (
        db.query(TaskCenterTask.assigned_ai_employee_code)
        .filter(TaskCenterTask.status == "running", TaskCenterTask.assigned_ai_employee_code.isnot(None))
        .all()
    )
    return {row[0] for row in rows if row[0]}


def recent_failed_tasks(db: Session) -> list[dict]:
    rows = (
        db.query(TaskCenterTask)
        .filter(TaskCenterTask.status == "rejected")
        .order_by(TaskCenterTask.updated_at.desc(), TaskCenterTask.id.desc())
        .limit(5)
        .all()
    )
    return [task_brief(row) for row in rows]


def today_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    return datetime.combine(now.date(), time.min, tzinfo=timezone.utc)


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
    last_record = latest_deploy_record(db)
    last_check = db.query(DeployHealthCheck).order_by(DeployHealthCheck.id.desc()).first()
    last_health_record = db.query(HealthCheckRecord).order_by(HealthCheckRecord.checked_at.desc(), HealthCheckRecord.id.desc()).first()
    deploy_records = deployment_records(db, 8)
    health_records = db.query(HealthCheckRecord).order_by(HealthCheckRecord.checked_at.desc(), HealthCheckRecord.id.desc()).limit(50).all()
    statuses = [system_health["database"], system_health["redis"], system_health["migration"]]
    return {
        "overall_status": normalize_deploy_status(statuses),
        "database_status": system_health["database"],
        "redis_status": system_health["redis"],
        "alembic_version": alembic_version,
        "expected_version": EXPECTED_ALEMBIC_VERSION,
        "last_deploy_status": deploy_status(last_record),
        "last_health_check_status": health_status(last_health_record, last_check),
        "deployment_history": [deploy_record_summary(record) for record in deploy_records],
        "latest_deploy": deploy_record_summary(last_record) if last_record else None,
        "last_health_check_time": latest_health_check_time(last_health_record, last_check),
        "service_stability_score": service_stability_score(health_records, statuses),
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


def build_deployment_history(db: Session, limit: int = 8) -> dict:
    safe_limit = max(1, min(limit, 50))
    records = deployment_records(db, safe_limit)
    return {
        "deployment_history": [deploy_record_summary(record) for record in records],
        "total": len(records),
        "readonly": True,
    }


def build_health_check_history(db: Session, limit: int = 20) -> dict:
    safe_limit = max(1, min(limit, 100))
    records = (
        db.query(HealthCheckRecord)
        .order_by(HealthCheckRecord.checked_at.desc(), HealthCheckRecord.id.desc())
        .limit(safe_limit)
        .all()
    )
    return {
        "health_check_history": [health_check_record_summary(record) for record in records],
        "latest_checked_at": iso(records[0].checked_at) if records else None,
        "total": len(records),
        "readonly": True,
    }


def latest_deploy_summary(db: Session) -> dict | None:
    record = latest_deploy_record(db)
    return deploy_record_summary(record) if record else None


def latest_deploy_record(db: Session) -> DeployRecord | None:
    return db.query(DeployRecord).order_by(DeployRecord.id.desc()).first()


def deployment_records(db: Session, limit: int) -> list[DeployRecord]:
    return db.query(DeployRecord).order_by(DeployRecord.id.desc()).limit(limit).all()


def deploy_status(record: DeployRecord | None) -> str | None:
    if not record:
        return None
    return record.deploy_status or record.status


def health_status(record: HealthCheckRecord | None, legacy_record: DeployHealthCheck | None) -> str | None:
    if record:
        return record.status
    if legacy_record:
        return legacy_record.status
    return None


def latest_health_check_time(record: HealthCheckRecord | None, legacy_record: DeployHealthCheck | None) -> str | None:
    if record:
        return iso(record.checked_at)
    if legacy_record:
        return iso(legacy_record.checked_at)
    return None


def service_stability_score(records: list[HealthCheckRecord], current_statuses: list[str]) -> int:
    if records:
        healthy = sum(1 for record in records if record.status in {"healthy", "running", "ok", "success"})
        return round(healthy / len(records) * 100)
    healthy = sum(1 for status in current_statuses if status in {"healthy", "running", "ok", "success"})
    return round(healthy / len(current_statuses) * 100) if current_statuses else 0


def deploy_record_summary(record: DeployRecord) -> dict:
    return {
        "deploy_id": record.deploy_id or str(record.id),
        "version": record.version or record.deploy_version,
        "commit_id": record.commit_id or record.commit_hash,
        "deploy_time": iso(record.deploy_time or record.finished_at or record.started_at or record.created_at),
        "deploy_status": deploy_status(record),
        "operator": record.operator,
    }


def health_check_record_summary(record: HealthCheckRecord) -> dict:
    return {
        "service": record.service,
        "status": record.status,
        "checked_at": iso(record.checked_at),
        "latency": record.latency,
    }


def brain_worker_summary(record: BrainWorkerStatus) -> dict:
    return {
        "worker_id": record.worker_id,
        "status": record.status,
        "heartbeat": iso(record.heartbeat_at),
        "current_execution_id": record.current_execution_id,
        "current_node_id": record.current_node_id,
        "current_task": record.current_task,
        "processed_count": record.processed_count,
        "success_count": record.success_count,
        "failed_count": record.failed_count,
        "timeout_count": record.timeout_count,
    }


def brain_execution_failure_summary(record: BrainExecutionRun) -> dict:
    return {
        "execution_id": record.id,
        "task_id": record.task_id,
        "employee_id": record.employee_id,
        "status": record.status,
        "risk_level": record.risk_level,
        "last_error": record.last_error or record.error_message,
        "finished_at": iso(record.finished_at),
    }


def action(level: str, action_type: str, message: str, count: int | None = None):
    data = {"level": level, "type": action_type, "message": message}
    if count is not None:
        data["count"] = count
    return data


def alert(level: str, alert_type: str, message: str):
    return {"level": level, "type": alert_type, "message": message}


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


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
