from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..auth import get_role_permissions, normalize_role, require_permission_user, current_user
from ..database import get_db, get_redis
from ..models import AiEmployee, AiTask, EmployeeLog, TaskCenterAuditLog, TaskCenterResult, TaskCenterReview, TaskCenterTask
from ..skills_engine.registry import list_employee_skill_cards
from ..tool_router.router_engine import list_routes


router = APIRouter()

EMPLOYEE_STATUSES = {"active", "inactive"}


class AiEmployeeCreate(BaseModel):
    employee_code: str
    employee_name: str
    legion: str | None = None
    duty: str | None = None
    status: str = "active"
    task_types: list[str] = []
    default_permissions: list[str] = []
    is_legacy: bool = False
    sort_order: int = 0


class AiEmployeeUpdate(BaseModel):
    employee_name: str | None = None
    legion: str | None = None
    duty: str | None = None
    status: str | None = None
    task_types: list[str] | None = None
    default_permissions: list[str] | None = None
    is_legacy: bool | None = None
    sort_order: int | None = None


@router.get("/api/ai-employees")
def list_ai_employees(
    request: Request,
    status: str | None = None,
    task_type: str | None = None,
    include_legacy: bool = False,
    db: Session = Depends(get_db),
):
    require_ai_employee_read(request, db)
    query = db.query(AiEmployee)
    if status:
        query = query.filter(AiEmployee.status == normalize_employee_status(status))
    if not include_legacy:
        query = query.filter(AiEmployee.is_legacy.is_(False))
    employees = query.order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc()).all()
    if task_type:
        employees = [employee for employee in employees if task_type in parse_json_list(employee.task_types)]
    return [employee_to_dict(employee) for employee in employees]


@router.get("/api/ai-employees/runtime-status")
def get_ai_employee_runtime_status(request: Request, db: Session = Depends(get_db)):
    require_ai_employee_read(request, db)
    employees = (
        db.query(AiEmployee)
        .filter(AiEmployee.is_legacy.is_(False))
        .order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc())
        .all()
    )
    employee_codes = [employee.employee_code for employee in employees]
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    current_tasks = load_current_tasks(db, employee_codes)
    completed_counts = load_today_completed_counts(db, employee_codes, today_start)
    recent_errors = load_recent_errors(db, employee_codes)

    rows = [
        employee_runtime_to_dict(
            db,
            employee,
            current_tasks.get(employee.employee_code),
            completed_counts.get(employee.employee_code, 0),
            recent_errors.get(employee.employee_code),
        )
        for employee in employees
    ]
    summary = {
        "total_employees": len(rows),
        "online_count": sum(1 for row in rows if row["status"] == "active"),
        "working_count": sum(1 for row in rows if row["runtime_status"] == "working"),
        "error_count": sum(1 for row in rows if row["runtime_status"] == "error"),
        "idle_count": sum(1 for row in rows if row["runtime_status"] == "idle"),
    }
    return {
        "readonly": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "employees": rows,
    }


@router.get("/api/ai-employees/{employee_code}")
def get_ai_employee(employee_code: str, request: Request, db: Session = Depends(get_db)):
    require_ai_employee_read(request, db)
    return employee_to_dict(get_employee_or_404(db, employee_code))


@router.get("/api/ai-employees/{employee_id}/detail")
def get_ai_employee_detail(employee_id: str, request: Request, db: Session = Depends(get_db)):
    require_ai_employee_read(request, db)
    employee = get_employee_or_404(db, employee_id)
    employee_codes = [employee.employee_code]
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    current_task = load_current_tasks(db, employee_codes).get(employee.employee_code)
    today_completed = load_today_completed_counts(db, employee_codes, today_start).get(employee.employee_code, 0)
    recent_error = load_recent_errors(db, employee_codes).get(employee.employee_code)
    recent_tasks = attach_task_metadata(db, load_employee_recent_tasks(db, employee.employee_code))
    success_stats = load_employee_success_stats(db, employee.employee_code)
    permission_scope = employee_permission_scope(db, employee)
    current_status = employee_runtime_to_dict(db, employee, current_task, today_completed, recent_error)
    return {
        "readonly": True,
        "employee": employee_to_dict(employee),
        "department": employee.legion,
        "role": employee.duty,
        "current_status": current_status,
        "current_task": task_detail_brief(current_task) if current_task else None,
        "historical_tasks": [task_detail_brief(task) for task in recent_tasks],
        "skills": employee_skills(db, employee),
        "executable_task_types": parse_json_list(employee.task_types),
        "permission_scope": permission_scope,
        "recent_tasks": [task_detail_brief(task) for task in recent_tasks],
        "recent_error": task_detail_brief(recent_error) if recent_error else None,
        "success_rate": success_stats,
        "recent_logs": load_employee_recent_logs(db, employee.employee_code, recent_tasks),
        "data_sources": [
            "ai_employees",
            "task_center_tasks",
            "task_center_results",
            "task_center_reviews",
            "task_center_audit_logs",
            "tool_router_routes",
        ],
        "safety": {
            "readonly": True,
            "does_not_trigger_execution": True,
            "external_api_called": False,
            "execution_engine_modified": False,
            "task_center_core_modified": False,
            "requires_boss_confirm_for_high_risk": True,
            "requires_security_audit_for_high_risk": True,
            "high_risk_requires": {
                "boss_confirm": True,
                "security_audited": True,
            },
            "dangerous_action_entrypoints_hidden": True,
            "can_auto_execute": permission_scope["can_auto_execute"],
        },
    }


@router.post("/api/ai-employees")
def create_ai_employee(payload: AiEmployeeCreate, request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "ai_employees.manage")
    employee_code = payload.employee_code.strip()
    employee_name = payload.employee_name.strip()
    if not employee_code:
        raise HTTPException(status_code=400, detail="employee code is required")
    if not employee_name:
        raise HTTPException(status_code=400, detail="employee name is required")
    if db.query(AiEmployee).filter(AiEmployee.employee_code == employee_code).one_or_none():
        raise HTTPException(status_code=400, detail="employee code already exists")

    employee = AiEmployee(
        employee_code=employee_code,
        employee_name=employee_name,
        legion=payload.legion,
        duty=payload.duty,
        status=normalize_employee_status(payload.status),
        task_types=json.dumps(payload.task_types, ensure_ascii=False),
        default_permissions=json.dumps(payload.default_permissions, ensure_ascii=False),
        is_legacy=payload.is_legacy,
        sort_order=payload.sort_order,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return {"ok": True, "employee": employee_to_dict(employee)}


@router.patch("/api/ai-employees/{employee_code}")
def update_ai_employee(employee_code: str, payload: AiEmployeeUpdate, request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "ai_employees.manage")
    employee = get_employee_or_404(db, employee_code)
    if payload.employee_name is not None:
        employee_name = payload.employee_name.strip()
        if not employee_name:
            raise HTTPException(status_code=400, detail="employee name is required")
        employee.employee_name = employee_name
    if payload.legion is not None:
        employee.legion = payload.legion
    if payload.duty is not None:
        employee.duty = payload.duty
    if payload.status is not None:
        employee.status = normalize_employee_status(payload.status)
    if payload.task_types is not None:
        employee.task_types = json.dumps(payload.task_types, ensure_ascii=False)
    if payload.default_permissions is not None:
        employee.default_permissions = json.dumps(payload.default_permissions, ensure_ascii=False)
    if payload.is_legacy is not None:
        employee.is_legacy = payload.is_legacy
    if payload.sort_order is not None:
        employee.sort_order = payload.sort_order
    db.commit()
    db.refresh(employee)
    return {"ok": True, "employee": employee_to_dict(employee)}


@router.post("/api/ai-employees/{employee_code}/enable")
def enable_ai_employee(employee_code: str, request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "ai_employees.manage")
    employee = get_employee_or_404(db, employee_code)
    employee.status = "active"
    db.commit()
    db.refresh(employee)
    return {"ok": True, "employee": employee_to_dict(employee)}


@router.post("/api/ai-employees/{employee_code}/disable")
def disable_ai_employee(employee_code: str, request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "ai_employees.manage")
    employee = get_employee_or_404(db, employee_code)
    employee.status = "inactive"
    db.commit()
    db.refresh(employee)
    return {"ok": True, "employee": employee_to_dict(employee)}


@router.get("/api/ai/tasks")
def list_ai_tasks(request: Request, db: Session = Depends(get_db)):
    require_ai_task_read(request, db)
    tasks = db.query(AiTask).options(joinedload(AiTask.owner)).order_by(AiTask.id.asc()).all()
    return [task_to_dict(t) for t in tasks]


@router.post("/api/ai/tasks/{task_id}")
async def update_ai_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "ai.tasks.manage")
    data = await request.json()
    task = db.get(AiTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="AI员工任务不存在")
    task.status = data.get("status", "").strip() or "idle"
    task.today_task = data.get("today_task", "").strip()
    task.execution_log = data.get("execution_log", "").strip()
    task.owner_user_id = data.get("owner_user_id") or None
    db.add(EmployeeLog(user_id=user.id, action="ai_task_update", detail=f"更新AI任务 {task_id}", ip_address=request.client.host if request.client else None))
    db.commit()
    return {"ok": True}


@router.post("/api/ai/tasks/{task_id}/run")
def run_ai_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "ai.tasks.manage")
    task = db.get(AiTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="AI员工任务不存在")
    now = datetime.now(timezone.utc)
    task.status = "running"
    task.last_run_at = now
    line = f"{now.strftime('%Y-%m-%d %H:%M:%S')} 手动触发执行"
    task.execution_log = ((task.execution_log or "") + "\n" + line).strip()
    db.add(EmployeeLog(user_id=user.id, action="ai_task_run", detail=f"触发{task.ai_employee_name}执行", ip_address=request.client.host if request.client else None))
    db.commit()
    push_ai_queue(task)
    return {"ok": True, "message": f"{task.ai_employee_name} 已进入执行状态"}


def get_employee_or_404(db: Session, employee_code: str):
    employee = db.query(AiEmployee).filter(AiEmployee.employee_code == employee_code.strip()).one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="AI employee not found")
    return employee


def normalize_employee_status(status: str) -> str:
    clean = status.strip()
    if clean not in EMPLOYEE_STATUSES:
        raise HTTPException(status_code=400, detail="invalid employee status")
    return clean


def parse_json_list(value: str | None):
    if not value:
        return []
    try:
        data = json.loads(value)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def employee_to_dict(employee: AiEmployee):
    return {
        "id": employee.id,
        "employee_code": employee.employee_code,
        "employee_name": employee.employee_name,
        "legion": employee.legion,
        "duty": employee.duty,
        "status": employee.status,
        "task_types": parse_json_list(employee.task_types),
        "default_permissions": parse_json_list(employee.default_permissions),
        "is_legacy": employee.is_legacy,
        "sort_order": employee.sort_order,
        "created_at": employee.created_at.isoformat() if employee.created_at else None,
        "updated_at": employee.updated_at.isoformat() if employee.updated_at else None,
    }


def load_current_tasks(db: Session, employee_codes: list[str]) -> dict[str, TaskCenterTask]:
    if not employee_codes:
        return {}
    rows = (
        db.query(TaskCenterTask)
        .filter(
            TaskCenterTask.assigned_ai_employee_code.in_(employee_codes),
            TaskCenterTask.status.in_(("assigned", "running")),
        )
        .order_by(TaskCenterTask.updated_at.desc(), TaskCenterTask.id.desc())
        .all()
    )
    tasks: dict[str, TaskCenterTask] = {}
    for task in rows:
        if task.assigned_ai_employee_code and task.assigned_ai_employee_code not in tasks:
            tasks[task.assigned_ai_employee_code] = task
    return tasks


def load_today_completed_counts(db: Session, employee_codes: list[str], today_start: datetime) -> dict[str, int]:
    if not employee_codes:
        return {}
    rows = (
        db.query(TaskCenterTask.assigned_ai_employee_code, func.count(TaskCenterTask.id))
        .filter(
            TaskCenterTask.assigned_ai_employee_code.in_(employee_codes),
            TaskCenterTask.status.in_(("accepted", "audited", "summarized", "completed")),
            TaskCenterTask.updated_at >= today_start,
        )
        .group_by(TaskCenterTask.assigned_ai_employee_code)
        .all()
    )
    return {code: count for code, count in rows if code}


def load_recent_errors(db: Session, employee_codes: list[str]) -> dict[str, TaskCenterTask]:
    if not employee_codes:
        return {}
    rows = (
        db.query(TaskCenterTask)
        .filter(
            TaskCenterTask.assigned_ai_employee_code.in_(employee_codes),
            TaskCenterTask.status.in_(("failed", "rejected")),
        )
        .order_by(TaskCenterTask.updated_at.desc(), TaskCenterTask.id.desc())
        .all()
    )
    errors: dict[str, TaskCenterTask] = {}
    for task in rows:
        if task.assigned_ai_employee_code and task.assigned_ai_employee_code not in errors:
            errors[task.assigned_ai_employee_code] = task
    return errors


def employee_runtime_to_dict(
    db: Session,
    employee: AiEmployee,
    current_task: TaskCenterTask | None,
    today_completed_tasks: int,
    recent_error: TaskCenterTask | None,
):
    if recent_error:
        runtime_status = "error"
    elif current_task:
        runtime_status = "working"
    elif employee.status == "active":
        runtime_status = "idle"
    else:
        runtime_status = "offline"
    return {
        "employee_code": employee.employee_code,
        "employee_name": employee.employee_name,
        "department": employee.legion,
        "duty": employee.duty,
        "status": employee.status,
        "runtime_status": runtime_status,
        "current_task": task_runtime_brief(current_task),
        "today_completed_tasks": today_completed_tasks,
        "recent_error": task_error_brief(recent_error),
        "tools": employee_tool_briefs(db, employee.employee_code),
    }


def task_runtime_brief(task: TaskCenterTask | None):
    if not task:
        return None
    return {
        "task_id": task.id,
        "title": task.title,
        "status": task.status,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def task_error_brief(task: TaskCenterTask | None):
    if not task:
        return None
    return {
        "task_id": task.id,
        "title": task.title,
        "status": task.status,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def employee_tool_briefs(db: Session, employee_code: str):
    return [
        {
            "tool_name": route["tool_name"],
            "risk_level": route["risk_level"],
            "enabled": route["enabled"],
            "priority": route["priority"],
        }
        for route in list_routes(db, employee_code=employee_code)
        if route["enabled"]
    ]


def employee_skills(db: Session, employee: AiEmployee):
    legacy_skills = [
        {
            "skill_code": task_type,
            "skill_name": task_type.replace("_", " "),
            "source": "ai_employees.task_types",
            "enabled": employee.status == "active",
        }
        for task_type in parse_json_list(employee.task_types)
    ]
    engine_skills = list_employee_skill_cards(db, employee.employee_code)
    return legacy_skills + engine_skills


def employee_permission_scope(db: Session, employee: AiEmployee):
    return {
        "default_permissions": parse_json_list(employee.default_permissions),
        "tools": employee_tool_briefs(db, employee.employee_code),
        "can_auto_execute": False,
        "can_modify_permissions": False,
        "requires_boss_confirm_for_high_risk": True,
    }


def load_employee_recent_tasks(db: Session, employee_code: str, limit: int = 10):
    return (
        db.query(TaskCenterTask)
        .filter(TaskCenterTask.assigned_ai_employee_code == employee_code)
        .order_by(TaskCenterTask.updated_at.desc(), TaskCenterTask.id.desc())
        .limit(limit)
        .all()
    )


def load_employee_success_stats(db: Session, employee_code: str):
    total = (
        db.query(func.count(TaskCenterTask.id))
        .filter(TaskCenterTask.assigned_ai_employee_code == employee_code)
        .scalar()
        or 0
    )
    success_statuses = ("accepted", "audited", "summarized", "completed", "success")
    failed_statuses = ("failed", "rejected", "timeout")
    success_count = (
        db.query(func.count(TaskCenterTask.id))
        .filter(TaskCenterTask.assigned_ai_employee_code == employee_code, TaskCenterTask.status.in_(success_statuses))
        .scalar()
        or 0
    )
    failed_count = (
        db.query(func.count(TaskCenterTask.id))
        .filter(TaskCenterTask.assigned_ai_employee_code == employee_code, TaskCenterTask.status.in_(failed_statuses))
        .scalar()
        or 0
    )
    completed_total = success_count + failed_count
    return {
        "total_tasks": total,
        "completed_or_failed_tasks": completed_total,
        "success_tasks": success_count,
        "failed_tasks": failed_count,
        "success_rate": round(success_count / completed_total, 4) if completed_total else 0,
    }


def task_detail_brief(task: TaskCenterTask):
    return {
        "task_id": task.id,
        "title": task.title,
        "status": task.status,
        "priority": task.priority,
        "source": task.source,
        "assigned_ai_employee_code": task.assigned_ai_employee_code,
        "assigned_ai_employee_name": task.assigned_ai_employee_name,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "has_result": bool(task_has_result(task)),
        "review_count": task_review_count(task),
    }


def task_has_result(task: TaskCenterTask):
    return getattr(task, "_has_result", False)


def task_review_count(task: TaskCenterTask):
    return getattr(task, "_review_count", 0)


def load_employee_recent_logs(db: Session, employee_code: str, recent_tasks: list[TaskCenterTask], limit: int = 10):
    task_ids = [task.id for task in recent_tasks]
    rows = []
    if task_ids:
        audit_rows = (
            db.query(TaskCenterAuditLog)
            .filter(TaskCenterAuditLog.task_id.in_(task_ids))
            .order_by(TaskCenterAuditLog.created_at.desc(), TaskCenterAuditLog.id.desc())
            .limit(limit)
            .all()
        )
        rows.extend(
            {
                "source": "task_center_audit",
                "task_id": row.task_id,
                "event": row.action,
                "status": row.to_status,
                "message": safe_log_message(row.detail),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in audit_rows
        )
    if len(rows) < limit:
        employee_rows = (
            db.query(EmployeeLog)
            .filter(EmployeeLog.detail.ilike(f"%{employee_code}%"))
            .order_by(EmployeeLog.created_at.desc(), EmployeeLog.id.desc())
            .limit(limit - len(rows))
            .all()
        )
        rows.extend(
            {
                "source": "employee_log",
                "task_id": None,
                "event": row.action,
                "status": None,
                "message": safe_log_message(row.detail),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in employee_rows
        )
    return rows[:limit]


def attach_task_metadata(db: Session, tasks: list[TaskCenterTask]):
    if not tasks:
        return tasks
    task_ids = [task.id for task in tasks]
    result_counts = dict(
        db.query(TaskCenterResult.task_id, func.count(TaskCenterResult.id))
        .filter(TaskCenterResult.task_id.in_(task_ids))
        .group_by(TaskCenterResult.task_id)
        .all()
    )
    review_counts = dict(
        db.query(TaskCenterReview.task_id, func.count(TaskCenterReview.id))
        .filter(TaskCenterReview.task_id.in_(task_ids))
        .group_by(TaskCenterReview.task_id)
        .all()
    )
    for task in tasks:
        setattr(task, "_has_result", bool(result_counts.get(task.id, 0)))
        setattr(task, "_review_count", int(review_counts.get(task.id, 0)))
    return tasks


def safe_log_message(value: str | None):
    if not value:
        return ""
    blocked = ("password", "password_hash", "secret", "token", "api key", "authorization", "bearer", "private_key")
    lowered = value.lower()
    if any(word in lowered for word in blocked):
        return "[redacted]"
    return value[:240]


def require_ai_employee_read(request: Request, db: Session):
    user = current_user(request, db)
    permissions = get_role_permissions(db, normalize_role(user.role))
    if not permissions.intersection({"ai_employees.read", "ai_employees.manage"}):
        raise HTTPException(status_code=403, detail="no AI employee registry permission")
    return user


def task_to_dict(task: AiTask):
    return {
        "id": task.id,
        "ai_employee_code": task.ai_employee_code,
        "ai_employee_name": task.ai_employee_name,
        "status": task.status,
        "today_task": task.today_task or "",
        "execution_log": task.execution_log or "",
        "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "owner": {"id": task.owner.id, "display_name": task.owner.display_name} if task.owner else None,
    }


def push_ai_queue(task: AiTask):
    get_redis().rpush(
        "ai:task_queue",
        json.dumps(
            {
                "task_id": task.id,
                "ai_employee_code": task.ai_employee_code,
                "ai_employee_name": task.ai_employee_name,
                "today_task": task.today_task,
                "queued_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        ),
    )


def require_ai_task_read(request: Request, db: Session):
    user = current_user(request, db)
    permissions = get_role_permissions(db, normalize_role(user.role))
    if not permissions.intersection({"ai.tasks.read", "ai.tasks.manage", "menu.ai_employees", "menu.workflows"}):
        raise HTTPException(status_code=403, detail="没有AI员工任务访问权限")
    return user
