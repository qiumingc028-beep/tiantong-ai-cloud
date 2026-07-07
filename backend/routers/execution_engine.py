from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..dispatch_models import EmployeeExecutionLog
from ..execution_engine import (
    ExecutionEngineError,
    ExecutionSafetyError,
    acquire_execution_lock,
    complete_task_execution,
    enqueue_execution_task,
    execution_log_to_dict,
    fail_task_execution,
    release_execution_lock,
    start_task_execution,
)
from ..models import TaskCenterTask
from .ai_execution import require_automation_read, require_automation_user


router = APIRouter(prefix="/api/execution")


class ClaimPayload(BaseModel):
    boss_confirmed: bool = False
    security_audited: bool = False


class StartPayload(BaseModel):
    worker_id: str = "api"


class CompletePayload(BaseModel):
    output_data: dict | list | str | int | float | bool | None = None
    tool_used: list[str] | None = None
    worker_id: str = "api"


class FailPayload(BaseModel):
    error_message: str
    tool_used: list[str] | None = None
    worker_id: str = "api"


@router.post("/tasks/{task_id}/claim")
def claim_task(task_id: int, request: Request, payload: ClaimPayload | None = None, db: Session = Depends(get_db)):
    require_automation_user(request, db, "task_center.execute")
    payload = payload or ClaimPayload()
    task = get_task_or_404(db, task_id)
    try:
        item = enqueue_execution_task(
            db,
            task,
            boss_confirmed=payload.boss_confirmed,
            security_audited=payload.security_audited,
        )
    except ExecutionSafetyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ExecutionEngineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "queue_item": item, "task": task_to_execution_dict(task)}


@router.post("/tasks/{task_id}/start")
def start_task(task_id: int, request: Request, payload: StartPayload | None = None, db: Session = Depends(get_db)):
    require_automation_user(request, db, "task_center.execute")
    payload = payload or StartPayload()
    task = get_task_or_404(db, task_id)
    worker_id = payload.worker_id.strip() or "api"
    if not acquire_execution_lock(task.id, worker_id):
        raise HTTPException(status_code=409, detail="task is already locked")
    try:
        log = start_task_execution(db, task, worker_id=worker_id)
    except ExecutionEngineError as exc:
        release_execution_lock(task.id, worker_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "task": task_to_execution_dict(task), "log": execution_log_to_dict(log)}


@router.post("/tasks/{task_id}/complete")
def complete_task(task_id: int, request: Request, payload: CompletePayload | None = None, db: Session = Depends(get_db)):
    require_automation_user(request, db, "task_center.execute")
    payload = payload or CompletePayload()
    task = get_task_or_404(db, task_id)
    try:
        log = complete_task_execution(db, task, output_data=payload.output_data, waiting_review=False)
    except ExecutionEngineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    release_execution_lock(task.id, payload.worker_id.strip() or "api")
    return {"ok": True, "task": task_to_execution_dict(task), "log": execution_log_to_dict(log)}


@router.post("/tasks/{task_id}/fail")
def fail_task(task_id: int, payload: FailPayload, request: Request, db: Session = Depends(get_db)):
    require_automation_user(request, db, "task_center.execute")
    task = get_task_or_404(db, task_id)
    log = fail_task_execution(db, task, error_message=payload.error_message)
    release_execution_lock(task.id, payload.worker_id.strip() or "api")
    return {"ok": True, "task": task_to_execution_dict(task), "log": execution_log_to_dict(log)}


@router.get("/logs")
def list_execution_logs(request: Request, db: Session = Depends(get_db)):
    require_automation_read(request, db)
    rows = db.query(EmployeeExecutionLog).order_by(EmployeeExecutionLog.id.desc()).limit(200).all()
    return {"logs": [execution_log_to_dict(row) for row in rows]}


def get_task_or_404(db: Session, task_id: int) -> TaskCenterTask:
    task = db.get(TaskCenterTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


def task_to_execution_dict(task: TaskCenterTask) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "assigned_ai_employee_code": task.assigned_ai_employee_code,
        "assigned_ai_employee_name": task.assigned_ai_employee_name,
    }
