from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..ai_employees import DEFAULT_STRATEGY_EMPLOYEE, employee_name
from ..database import get_db
from ..models import TaskCenterResult, TaskCenterTask
from ..queue import enqueue_task
from .ai_execution import constant_time_equal, first_system_user, parse_json_value, require_automation_read, require_automation_user


router = APIRouter()

SPRINT18_QUEUE_TYPE = "sprint18_business_loop"


class EcommerceOrderWebhook(BaseModel):
    platform: str = "ecommerce"
    order_id: str
    sku: str
    product_name: str | None = None
    quantity: int = 1
    amount: float = 0
    customer_tags: list[str] | None = None
    auto_optimize: bool = False


class ContentMetricsWebhook(BaseModel):
    platform: str = "content"
    content_id: str
    title: str | None = None
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    auto_optimize: bool = False


class FileUploadWebhook(BaseModel):
    filename: str
    file_type: str = "text"
    content_summary: str | None = None
    rows: list[dict] | None = None
    auto_optimize: bool = False


class ReplayRequest(BaseModel):
    feedback: dict | list | str | int | float | bool | None = None


@router.post("/api/business-webhooks/ecommerce/orders")
def ecommerce_order_webhook(
    payload: EcommerceOrderWebhook,
    request: Request,
    db: Session = Depends(get_db),
    x_webhook_secret: str | None = Header(default=None),
):
    user = authorize_business_webhook(request, db, x_webhook_secret)
    task = create_business_task(
        db=db,
        user_id=user.id,
        event_type="ecommerce_order",
        event_payload=payload.model_dump(),
        auto_optimize=payload.auto_optimize,
    )
    db.commit()
    db.refresh(task)
    enqueue_business_task(task)
    return {"ok": True, "event_type": "ecommerce_order", "task_id": task.id, "task": task_to_business_api(task, db)}


@router.post("/api/business-webhooks/content/metrics")
def content_metrics_webhook(
    payload: ContentMetricsWebhook,
    request: Request,
    db: Session = Depends(get_db),
    x_webhook_secret: str | None = Header(default=None),
):
    user = authorize_business_webhook(request, db, x_webhook_secret)
    task = create_business_task(
        db=db,
        user_id=user.id,
        event_type="content_metrics",
        event_payload=payload.model_dump(),
        auto_optimize=payload.auto_optimize,
    )
    db.commit()
    db.refresh(task)
    enqueue_business_task(task)
    return {"ok": True, "event_type": "content_metrics", "task_id": task.id, "task": task_to_business_api(task, db)}


@router.post("/api/business-webhooks/files")
def file_upload_webhook(
    payload: FileUploadWebhook,
    request: Request,
    db: Session = Depends(get_db),
    x_webhook_secret: str | None = Header(default=None),
):
    user = authorize_business_webhook(request, db, x_webhook_secret)
    task = create_business_task(
        db=db,
        user_id=user.id,
        event_type="file_upload",
        event_payload=payload.model_dump(),
        auto_optimize=payload.auto_optimize,
    )
    db.commit()
    db.refresh(task)
    enqueue_business_task(task)
    return {"ok": True, "event_type": "file_upload", "task_id": task.id, "task": task_to_business_api(task, db)}


@router.get("/api/business-loop/decisions")
def list_business_decisions(request: Request, db: Session = Depends(get_db)):
    require_automation_read(request, db)
    tasks = (
        db.query(TaskCenterTask)
        .filter(TaskCenterTask.source == "sprint18_business_loop")
        .order_by(TaskCenterTask.id.desc())
        .all()
    )
    return {"tasks": [task_to_business_api(task, db) for task in tasks]}


@router.get("/api/business-loop/results")
def list_business_results(request: Request, db: Session = Depends(get_db)):
    require_automation_read(request, db)
    rows = (
        db.query(TaskCenterResult)
        .join(TaskCenterTask, TaskCenterResult.task_id == TaskCenterTask.id)
        .filter(TaskCenterTask.source == "sprint18_business_loop")
        .order_by(TaskCenterResult.id.desc())
        .all()
    )
    return {"results": [result_to_business_api(row) for row in rows]}


@router.post("/api/business-loop/results/{result_id}/replay")
def replay_business_result(result_id: int, payload: ReplayRequest, request: Request, db: Session = Depends(get_db)):
    user = require_automation_user(request, db, "task_center.manage")
    row = db.get(TaskCenterResult, result_id)
    if not row or not row.task or row.task.source != "sprint18_business_loop":
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="result not found")
    previous = parse_json_value(row.result_content)
    task = create_business_task(
        db=db,
        user_id=user.id,
        event_type="feedback_replay",
        event_payload={"previous_result": previous, "feedback": payload.feedback},
        auto_optimize=False,
        loop_iteration=next_loop_iteration(row.task),
    )
    db.commit()
    db.refresh(task)
    enqueue_business_task(task)
    return {"ok": True, "task_id": task.id, "task": task_to_business_api(task, db)}


def authorize_business_webhook(request: Request, db: Session, secret: str | None):
    expected_secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if expected_secret and constant_time_equal(secret or "", expected_secret):
        return first_system_user(db)
    return require_automation_user(request, db, "task_center.manage")


def create_business_task(
    db: Session,
    user_id: int,
    event_type: str,
    event_payload: dict,
    auto_optimize: bool,
    loop_iteration: int = 0,
) -> TaskCenterTask:
    metadata = {
        "sprint18": True,
        "event_type": event_type,
        "input": event_payload,
        "loop_id": str(uuid4()),
        "loop_iteration": loop_iteration,
        "auto_optimize": bool(auto_optimize),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    task = TaskCenterTask(
        title=f"Sprint 18 business loop: {event_type}",
        description=json.dumps({"input": event_payload}, ensure_ascii=False),
        status="assigned",
        priority="normal",
        source="sprint18_business_loop",
        assigned_ai_employee_code=DEFAULT_STRATEGY_EMPLOYEE,
        assigned_ai_employee_name=employee_name(DEFAULT_STRATEGY_EMPLOYEE),
        split_plan=json.dumps(metadata, ensure_ascii=False),
        created_by_id=user_id,
        updated_by_id=user_id,
    )
    db.add(task)
    db.flush()
    return task


def enqueue_business_task(task: TaskCenterTask) -> None:
    enqueue_task(
        SPRINT18_QUEUE_TYPE,
        {
            "task_center_id": task.id,
            "metadata": task_metadata(task),
        },
        max_retries=1,
        delay_note="Sprint 18 business loop queued",
    )


def task_to_business_api(task: TaskCenterTask, db: Session) -> dict:
    metadata = task_metadata(task)
    latest_result = (
        db.query(TaskCenterResult)
        .filter(TaskCenterResult.task_id == task.id)
        .order_by(TaskCenterResult.id.desc())
        .first()
    )
    return {
        "id": task.id,
        "event_type": metadata.get("event_type"),
        "input": metadata.get("input"),
        "status": task.status,
        "assigned_to": task.assigned_ai_employee_code,
        "loop_id": metadata.get("loop_id"),
        "loop_iteration": metadata.get("loop_iteration", 0),
        "auto_optimize": metadata.get("auto_optimize", False),
        "result": parse_json_value(latest_result.result_content) if latest_result else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def result_to_business_api(row: TaskCenterResult) -> dict:
    task = row.task
    metadata = task_metadata(task) if task else {}
    return {
        "id": row.id,
        "task_id": row.task_id,
        "event_type": metadata.get("event_type"),
        "loop_id": metadata.get("loop_id"),
        "loop_iteration": metadata.get("loop_iteration", 0),
        "result": parse_json_value(row.result_content),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def task_metadata(task: TaskCenterTask) -> dict:
    try:
        data = json.loads(task.split_plan or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def next_loop_iteration(task: TaskCenterTask) -> int:
    metadata = task_metadata(task)
    try:
        return int(metadata.get("loop_iteration", 0)) + 1
    except Exception:
        return 1
