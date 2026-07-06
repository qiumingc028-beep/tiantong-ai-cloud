from __future__ import annotations

from typing import Optional
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import current_user, require_permission_user
from ..database import get_db
from ..models import AiEmployee, TaskCenterAuditLog, TaskCenterResult, TaskCenterReview, TaskCenterTask, User


router = APIRouter(prefix="/api/task-center")

TASK_STATUSES = {
    "created",
    "split",
    "assigned",
    "running",
    "result_submitted",
    "accepted",
    "rejected",
    "audited",
    "summarized",
}
ACCEPTANCE_REVIEW_STATUSES = {"accepted", "rejected"}


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str = "normal"
    parent_task_id: Optional[int] = None
    split_plan: Optional[str] = None


class TaskStatusUpdate(BaseModel):
    status: str
    detail: Optional[str] = None


class TaskAssign(BaseModel):
    ai_employee_code: str
    ai_employee_name: Optional[str] = None
    detail: Optional[str] = None


class TaskResultSubmit(BaseModel):
    result_content: str
    attachments: Optional[list[str]] = None


class TaskReviewSubmit(BaseModel):
    review_status: str
    comment: Optional[str] = None


class TaskSummarySubmit(BaseModel):
    summary: str


@router.post("/tasks")
def create_task(payload: TaskCreate, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "task_center.manage")
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="task title is required")
    if payload.parent_task_id and not db.get(TaskCenterTask, payload.parent_task_id):
        raise HTTPException(status_code=404, detail="parent task not found")

    task = TaskCenterTask(
        title=title,
        description=payload.description,
        priority=payload.priority.strip() or "normal",
        parent_task_id=payload.parent_task_id,
        split_plan=payload.split_plan,
        status="split" if payload.split_plan else "created",
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(task)
    db.flush()
    write_audit_log(db, task, user, "task_created", None, task.status, "boss created task")
    db.commit()
    db.refresh(task)
    return {"ok": True, "task": task_to_dict(task)}


@router.get("/tasks")
def list_tasks(request: Request, status: Optional[str] = None, db: Session = Depends(get_db)):
    require_task_read(request, db)
    query = db.query(TaskCenterTask)
    if status:
        query = query.filter(TaskCenterTask.status == status)
    tasks = query.order_by(TaskCenterTask.id.desc()).all()
    return [task_to_dict(task) for task in tasks]


@router.get("/tasks/{task_id}")
def get_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    require_task_read(request, db)
    task = get_task_or_404(db, task_id)
    return {
        **task_to_dict(task),
        "results": [result_to_dict(row) for row in db.query(TaskCenterResult).filter(TaskCenterResult.task_id == task_id).order_by(TaskCenterResult.id.asc()).all()],
        "reviews": [review_to_dict(row) for row in db.query(TaskCenterReview).filter(TaskCenterReview.task_id == task_id).order_by(TaskCenterReview.id.asc()).all()],
    }


@router.patch("/tasks/{task_id}/status")
def update_task_status(task_id: int, payload: TaskStatusUpdate, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "task_center.manage")
    status = normalize_status(payload.status)
    task = get_task_or_404(db, task_id)
    set_task_status(db, task, status, user, "status_updated", payload.detail)
    db.commit()
    db.refresh(task)
    return {"ok": True, "task": task_to_dict(task)}


@router.post("/tasks/{task_id}/assign")
def assign_ai_employee(task_id: int, payload: TaskAssign, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "task_center.manage")
    task = get_task_or_404(db, task_id)
    employee_code = payload.ai_employee_code.strip()
    ai_employee = db.query(AiEmployee).filter(AiEmployee.employee_code == employee_code).one_or_none()
    if not ai_employee:
        raise HTTPException(status_code=404, detail="AI employee not found")
    if ai_employee.status != "active":
        raise HTTPException(status_code=400, detail="AI employee is inactive")
    if ai_employee.is_legacy:
        raise HTTPException(status_code=400, detail="legacy AI employee cannot be assigned")

    task.assigned_ai_employee_code = employee_code
    task.assigned_ai_employee_name = payload.ai_employee_name or ai_employee.employee_name
    set_task_status(db, task, "assigned", user, "ai_employee_assigned", payload.detail or task.assigned_ai_employee_code)
    db.commit()
    db.refresh(task)
    return {"ok": True, "task": task_to_dict(task)}


@router.post("/tasks/{task_id}/start")
def start_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "task_center.execute")
    task = get_task_or_404(db, task_id)
    if not task.assigned_ai_employee_code:
        raise HTTPException(status_code=400, detail="task is not assigned")
    set_task_status(db, task, "running", user, "task_started", task.assigned_ai_employee_code)
    db.commit()
    db.refresh(task)
    return {"ok": True, "task": task_to_dict(task)}


@router.post("/tasks/{task_id}/results")
def submit_result(task_id: int, payload: TaskResultSubmit, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "task_center.execute")
    task = get_task_or_404(db, task_id)
    if not task.assigned_ai_employee_code:
        raise HTTPException(status_code=400, detail="task is not assigned")
    result_content = payload.result_content.strip()
    if not result_content:
        raise HTTPException(status_code=400, detail="result content is required")

    result = TaskCenterResult(
        task_id=task.id,
        ai_employee_code=task.assigned_ai_employee_code,
        ai_employee_name=task.assigned_ai_employee_name,
        result_content=result_content,
        attachments_json=json.dumps(payload.attachments or [], ensure_ascii=False),
        submitted_by_id=user.id,
    )
    db.add(result)
    set_task_status(db, task, "result_submitted", user, "result_submitted", "AI employee submitted result")
    db.commit()
    db.refresh(result)
    db.refresh(task)
    return {"ok": True, "task": task_to_dict(task), "result": result_to_dict(result)}


@router.post("/tasks/{task_id}/reviews")
def submit_acceptance_review(task_id: int, payload: TaskReviewSubmit, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "task_center.review")
    task = get_task_or_404(db, task_id)
    review_status = normalize_acceptance_review_status(payload.review_status)
    review = TaskCenterReview(
        task_id=task.id,
        review_type="acceptance",
        review_status=review_status,
        comment=payload.comment,
        reviewer_role="tianjian",
        reviewer_id=user.id,
    )
    db.add(review)
    next_status = "rejected" if review_status == "rejected" else "accepted"
    set_task_status(db, task, next_status, user, "acceptance_reviewed", payload.comment)
    db.commit()
    db.refresh(review)
    db.refresh(task)
    return {"ok": True, "task": task_to_dict(task), "review": review_to_dict(review)}


@router.post("/tasks/{task_id}/audits")
def submit_audit_review(task_id: int, payload: TaskReviewSubmit, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "task_center.audit")
    task = get_task_or_404(db, task_id)
    review = TaskCenterReview(
        task_id=task.id,
        review_type="audit",
        review_status=payload.review_status.strip() or "audited",
        comment=payload.comment,
        reviewer_role="tianjian_audit",
        reviewer_id=user.id,
    )
    db.add(review)
    set_task_status(db, task, "audited", user, "task_audited", payload.comment)
    db.commit()
    db.refresh(review)
    db.refresh(task)
    return {"ok": True, "task": task_to_dict(task), "audit": review_to_dict(review)}


@router.post("/tasks/{task_id}/summary")
def summarize_task(task_id: int, payload: TaskSummarySubmit, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "task_center.manage")
    task = get_task_or_404(db, task_id)
    summary = payload.summary.strip()
    if not summary:
        raise HTTPException(status_code=400, detail="summary is required")
    task.summary = summary
    set_task_status(db, task, "summarized", user, "task_summarized", summary)
    db.commit()
    db.refresh(task)
    return {"ok": True, "task": task_to_dict(task)}


@router.get("/tasks/{task_id}/audit-logs")
def list_task_audit_logs(task_id: int, request: Request, db: Session = Depends(get_db)):
    require_task_read(request, db)
    get_task_or_404(db, task_id)
    rows = db.query(TaskCenterAuditLog).filter(TaskCenterAuditLog.task_id == task_id).order_by(TaskCenterAuditLog.id.asc()).all()
    return [audit_log_to_dict(row) for row in rows]


def require_task_read(request: Request, db: Session) -> User:
    try:
        return require_permission_user(request, db, "task_center.read")
    except HTTPException as exc:
        if exc.status_code == 403:
            return require_permission_user(request, db, "task_center.manage")
        raise


def get_task_or_404(db: Session, task_id: int) -> TaskCenterTask:
    task = db.get(TaskCenterTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


def normalize_status(status: str) -> str:
    clean = status.strip()
    if clean not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="invalid task status")
    return clean


def normalize_acceptance_review_status(status: str) -> str:
    clean = status.strip()
    if clean not in ACCEPTANCE_REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail="invalid review status")
    return clean


def set_task_status(db: Session, task: TaskCenterTask, status: str, user: User, action: str, detail: Optional[str] = None) -> None:
    from_status = task.status
    task.status = normalize_status(status)
    task.updated_by_id = user.id
    write_audit_log(db, task, user, action, from_status, task.status, detail)


def write_audit_log(
    db: Session,
    task: TaskCenterTask,
    user: User,
    action: str,
    from_status: Optional[str],
    to_status: Optional[str],
    detail: Optional[str],
) -> None:
    db.add(
        TaskCenterAuditLog(
            task_id=task.id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            detail=detail,
            actor_id=user.id,
            actor_role=user.role,
        )
    )


def iso(value: Optional[datetime]):
    return value.isoformat() if value else None


def parse_json_list(value: Optional[str]):
    if not value:
        return []
    try:
        data = json.loads(value)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def user_to_dict(user: Optional[User]):
    return {"id": user.id, "display_name": user.display_name, "role": user.role} if user else None


def task_to_dict(task: TaskCenterTask):
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status,
        "priority": task.priority,
        "source": task.source,
        "parent_task_id": task.parent_task_id,
        "assigned_ai_employee_code": task.assigned_ai_employee_code,
        "assigned_ai_employee_name": task.assigned_ai_employee_name,
        "split_plan": task.split_plan,
        "summary": task.summary,
        "created_by": user_to_dict(task.created_by),
        "updated_by": user_to_dict(task.updated_by),
        "created_at": iso(task.created_at),
        "updated_at": iso(task.updated_at),
    }


def result_to_dict(result: TaskCenterResult):
    return {
        "id": result.id,
        "task_id": result.task_id,
        "ai_employee_code": result.ai_employee_code,
        "ai_employee_name": result.ai_employee_name,
        "result_content": result.result_content,
        "attachments": parse_json_list(result.attachments_json),
        "submitted_by": user_to_dict(result.submitted_by),
        "created_at": iso(result.created_at),
    }


def review_to_dict(review: TaskCenterReview):
    return {
        "id": review.id,
        "task_id": review.task_id,
        "review_type": review.review_type,
        "review_status": review.review_status,
        "comment": review.comment,
        "reviewer_role": review.reviewer_role,
        "reviewer": user_to_dict(review.reviewer),
        "created_at": iso(review.created_at),
    }


def audit_log_to_dict(row: TaskCenterAuditLog):
    return {
        "id": row.id,
        "task_id": row.task_id,
        "action": row.action,
        "from_status": row.from_status,
        "to_status": row.to_status,
        "detail": row.detail,
        "actor": user_to_dict(row.actor),
        "actor_role": row.actor_role,
        "created_at": iso(row.created_at),
    }
