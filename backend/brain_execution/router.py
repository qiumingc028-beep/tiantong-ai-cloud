from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..models import User
from .executor import enqueue_approved_execution
from .planner import analyze_goal, approve_run, create_plan, get_task_chain, list_execution_contexts, list_execution_events, list_execution_logs, list_worker_statuses
from .queue import get_queue_status
from .schemas import AnalyzePayload, ApprovePayload, PlanPayload, StartPayload


router = APIRouter(prefix="/api/brain")
PRIVILEGED_ROLES = {"owner", "admin"}
EMPLOYEE_ROLES = {"operator", "customer_service", "designer", "editor", "finance"}


@router.post("/analyze")
def analyze(payload: AnalyzePayload, request: Request, db: Session = Depends(get_db)):
    user = require_brain_user(request, db)
    return analyze_goal(payload.goal, db=db, created_by=user.username)


@router.post("/plan")
def plan(payload: PlanPayload, request: Request, db: Session = Depends(get_db)):
    user = require_brain_user(request, db)
    return create_plan(
        db,
        payload.goal,
        execution_id=payload.execution_id,
        created_by=user.username,
        boss_confirm=payload.boss_confirm,
        security_audited=payload.security_audited,
    )


@router.post("/approve")
def approve(payload: ApprovePayload, request: Request, db: Session = Depends(get_db)):
    user = require_privileged_user(request, db)
    result = approve_run(
        db,
        payload.execution_id,
        approve_user=user.username,
        decision=payload.decision,
        reason=payload.reason,
        boss_confirm=payload.boss_confirm,
        security_audited=payload.security_audited,
    )
    if result.get("error"):
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return result


@router.post("/start")
def start(payload: StartPayload, request: Request, db: Session = Depends(get_db)):
    require_privileged_user(request, db)
    result = enqueue_approved_execution(db, payload.execution_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return result


@router.get("/queue/status")
def queue_status(request: Request, db: Session = Depends(get_db)):
    require_brain_user(request, db)
    return get_queue_status()


@router.get("/workers/status")
def workers_status(request: Request, db: Session = Depends(get_db)):
    require_privileged_user(request, db)
    return {"workers": list_worker_statuses(db)}


@router.get("/tasks/{execution_id}")
def tasks(execution_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_brain_user(request, db)
    result = get_task_chain(db, execution_id)
    if not result:
        raise HTTPException(status_code=404, detail="任务链不存在")
    if not can_view_all(user):
        nodes = [row for row in result["nodes"] if row["employee_code"] == user.username]
        result["nodes"] = nodes
    return result


@router.get("/executions/{execution_id}")
def execution_detail(execution_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_brain_user(request, db)
    result = get_task_chain(db, execution_id)
    if not result:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    if not can_view_all(user):
        result["nodes"] = [row for row in result["nodes"] if row["employee_code"] == user.username]
    result["events"] = list_execution_events(db, execution_id)
    return result


@router.get("/executions/{execution_id}/context")
def execution_context(execution_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_brain_user(request, db)
    result = get_task_chain(db, execution_id)
    if not result:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    contexts = list_execution_contexts(db, execution_id)
    if not can_view_all(user):
        contexts = [row for row in contexts if row["employee_code"] == user.username]
    return {"execution_id": execution_id, "contexts": contexts}


@router.get("/logs")
def logs(request: Request, db: Session = Depends(get_db)):
    user = require_brain_user(request, db)
    employee_code = None if can_view_all(user) else user.username
    return {"logs": list_execution_logs(db, employee_code=employee_code)}


def require_brain_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role == "viewer":
        raise HTTPException(status_code=403, detail="无 Brain Execution 访问权限")
    if role in PRIVILEGED_ROLES or role in EMPLOYEE_ROLES:
        return user
    raise HTTPException(status_code=403, detail="无 Brain Execution 访问权限")


def require_privileged_user(request: Request, db: Session) -> User:
    user = require_brain_user(request, db)
    if not can_view_all(user):
        raise HTTPException(status_code=403, detail="需要 Owner/Admin 权限")
    return user


def can_view_all(user: User) -> bool:
    return normalize_role(user.role) in PRIVILEGED_ROLES
