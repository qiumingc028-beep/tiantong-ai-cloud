from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from ..auth import get_role_permissions, normalize_role, require_permission_user, current_user
from ..database import get_db, get_redis
from ..models import AiEmployee, AiTask, EmployeeLog


router = APIRouter()

EMPLOYEE_STATUSES = {"active", "inactive"}


class AiEmployeeCreate(BaseModel):
    employee_code: str
    employee_name: str
    legion: Optional[str] = None
    duty: Optional[str] = None
    status: str = "active"
    task_types: list[str] = []
    default_permissions: list[str] = []
    is_legacy: bool = False
    sort_order: int = 0


class AiEmployeeUpdate(BaseModel):
    employee_name: Optional[str] = None
    legion: Optional[str] = None
    duty: Optional[str] = None
    status: Optional[str] = None
    task_types: Optional[list[str]] = None
    default_permissions: Optional[list[str]] = None
    is_legacy: Optional[bool] = None
    sort_order: Optional[int] = None


@router.get("/api/ai-employees")
def list_ai_employees(
    request: Request,
    status: Optional[str] = None,
    task_type: Optional[str] = None,
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


@router.get("/api/ai-employees/{employee_code}")
def get_ai_employee(employee_code: str, request: Request, db: Session = Depends(get_db)):
    require_ai_employee_read(request, db)
    return employee_to_dict(get_employee_or_404(db, employee_code))


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


def parse_json_list(value: Optional[str]):
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
