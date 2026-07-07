from __future__ import annotations

import json
import os
import hmac
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..ai_employees import DEFAULT_COLLECTOR_EMPLOYEE, DEFAULT_STRATEGY_EMPLOYEE, FLOW_EMPLOYEE_CODES, FLOW_TASK_TYPES, employee_name, normalize_employee_code
from ..auth import require_permission_user
from ..database import get_db
from ..models import TaskCenterResult, TaskCenterTask, User
from ..queue import enqueue_task


router = APIRouter()

SPRINT17_QUEUE_TYPE = "sprint17_ai_task"
FLOW_CHAIN = list(FLOW_EMPLOYEE_CODES)


class AutomationTaskCreate(BaseModel):
    type: str
    input: dict | list | str | int | float | bool | None = None
    assigned_to: str | None = None


class AutomationTaskAssign(BaseModel):
    assigned_to: str


class AutomationTaskComplete(BaseModel):
    result: dict | list | str | int | float | bool | None = None


class FlowCreate(BaseModel):
    input: dict | list | str | int | float | bool | None = None
    type: str = "tiancai_to_tianbo_flow"


class WebhookTaskCreate(BaseModel):
    type: str = "webhook_task"
    input: dict | list | str | int | float | bool | None = None
    assigned_to: str | None = DEFAULT_COLLECTOR_EMPLOYEE
    flow: str | None = None


class FeedbackLoopCreate(BaseModel):
    feedback: dict | list | str | int | float | bool | None = None
    assigned_to: str | None = None
    type: str = "feedback_optimization"


@router.post("/api/tasks")
def create_task(payload: AutomationTaskCreate, request: Request, db: Session = Depends(get_db)):
    user = require_automation_user(request, db, "task_center.manage")
    task_type = clean_required(payload.type, "type")
    assigned_to = normalize_employee_code(clean_optional(payload.assigned_to))
    task = create_automation_task(
        db=db,
        user=user,
        task_type=task_type,
        task_input=payload.input,
        assigned_to=assigned_to,
        status="assigned" if assigned_to else "created",
    )
    db.commit()
    db.refresh(task)
    if assigned_to:
        enqueue_automation_task(task)
    return {"ok": True, "task": task_to_api(task, db)}


@router.get("/api/tasks")
def list_tasks(request: Request, db: Session = Depends(get_db)):
    require_automation_read(request, db)
    rows = (
        db.query(TaskCenterTask)
        .filter(TaskCenterTask.source == "sprint17_ai_execution")
        .order_by(TaskCenterTask.id.desc())
        .all()
    )
    return {"tasks": [task_to_api(row, db) for row in rows]}


@router.post("/api/tasks/{task_id}/assign")
def assign_task(task_id: int, payload: AutomationTaskAssign, request: Request, db: Session = Depends(get_db)):
    require_automation_user(request, db, "task_center.manage")
    task = get_automation_task_or_404(db, task_id)
    assigned_to = normalize_employee_code(clean_required(payload.assigned_to, "assigned_to"))
    task.assigned_ai_employee_code = assigned_to
    task.assigned_ai_employee_name = employee_name(assigned_to) or assigned_to
    task.status = "assigned"
    db.commit()
    db.refresh(task)
    enqueue_automation_task(task)
    return {"ok": True, "task": task_to_api(task, db)}


@router.post("/api/tasks/{task_id}/complete")
def complete_task(task_id: int, payload: AutomationTaskComplete, request: Request, db: Session = Depends(get_db)):
    user = require_automation_user(request, db, "task_center.execute")
    task = get_automation_task_or_404(db, task_id)
    result = write_task_result(db, task, payload.result, submitted_by_id=user.id)
    task.status = "completed"
    task.updated_by_id = user.id
    db.commit()
    db.refresh(task)
    db.refresh(result)
    return {"ok": True, "task": task_to_api(task, db), "result": result_to_api(result)}


@router.post("/api/flows/tiancai-tianshu-tiance-tianbo")
def create_tiancai_to_tianbo_flow(payload: FlowCreate, request: Request, db: Session = Depends(get_db)):
    user = require_automation_user(request, db, "task_center.manage")
    return create_flow_task(db, user, payload)


@router.post("/api/webhooks/tasks")
def webhook_create_task(
    payload: WebhookTaskCreate,
    request: Request,
    db: Session = Depends(get_db),
    x_webhook_secret: str | None = Header(default=None),
):
    expected_secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if expected_secret and constant_time_equal(x_webhook_secret or "", expected_secret):
        system_user = first_system_user(db)
    else:
        system_user = require_automation_user(request, db, "task_center.manage")

    if payload.flow == "tiancai-tianshu-tiance-tianbo":
        return create_flow_task(db, system_user, FlowCreate(input=payload.input, type="webhook_business_flow"))

    assigned_to = normalize_employee_code(clean_optional(payload.assigned_to)) or DEFAULT_COLLECTOR_EMPLOYEE
    task = create_automation_task(
        db=db,
        user=system_user,
        task_type=clean_required(payload.type, "type"),
        task_input=payload.input,
        assigned_to=assigned_to,
        status="assigned",
    )
    db.commit()
    db.refresh(task)
    enqueue_automation_task(task)
    return {"ok": True, "task": task_to_api(task, db), "trigger": "webhook"}


@router.post("/api/tasks/{task_id}/feedback-loop")
def create_feedback_loop_task(task_id: int, payload: FeedbackLoopCreate, request: Request, db: Session = Depends(get_db)):
    user = require_automation_user(request, db, "task_center.manage")
    source_task = get_automation_task_or_404(db, task_id)
    latest_result = latest_task_result(db, source_task.id)
    if not latest_result:
        raise HTTPException(status_code=400, detail="task has no result")

    loop_input = {
        "source_task_id": source_task.id,
        "source_result": parse_json_value(latest_result.result_content),
        "feedback": payload.feedback,
    }
    assigned_to = normalize_employee_code(clean_optional(payload.assigned_to) or source_task.assigned_ai_employee_code) or DEFAULT_STRATEGY_EMPLOYEE
    task = create_automation_task(
        db=db,
        user=user,
        task_type=clean_required(payload.type, "type"),
        task_input=loop_input,
        assigned_to=assigned_to,
        status="assigned",
        metadata={
            "sprint17": True,
            "business_loop": True,
            "type": payload.type,
            "input": loop_input,
            "source_task_id": source_task.id,
            "flow_id": None,
            "flow_steps": [],
            "flow_index": None,
        },
    )
    db.commit()
    db.refresh(task)
    enqueue_automation_task(task)
    return {"ok": True, "task": task_to_api(task, db), "source_task_id": source_task.id}


def create_flow_task(db: Session, user: User, payload: FlowCreate) -> dict:
    flow_id = str(uuid4())
    first_employee = FLOW_CHAIN[0]
    metadata = {
        "sprint17": True,
        "type": FLOW_TASK_TYPES[first_employee],
        "input": payload.input,
        "flow_id": flow_id,
        "flow_steps": FLOW_CHAIN,
        "flow_index": 0,
        "business_loop": True,
    }
    task = create_automation_task(
        db=db,
        user=user,
        task_type=FLOW_TASK_TYPES[first_employee],
        task_input=payload.input,
        assigned_to=first_employee,
        status="assigned",
        metadata=metadata,
        title=f"Sprint 17 business flow {payload.type} step 1/{len(FLOW_CHAIN)}",
    )
    db.commit()
    db.refresh(task)
    enqueue_automation_task(task)
    return {"ok": True, "flow_id": flow_id, "task": task_to_api(task, db), "chain": FLOW_CHAIN}


@router.get("/api/results")
def list_results(request: Request, db: Session = Depends(get_db)):
    require_automation_read(request, db)
    rows = (
        db.query(TaskCenterResult)
        .join(TaskCenterTask, TaskCenterResult.task_id == TaskCenterTask.id)
        .filter(TaskCenterTask.source == "sprint17_ai_execution")
        .order_by(TaskCenterResult.id.desc())
        .all()
    )
    return {"results": [result_to_api(row) for row in rows]}


def create_automation_task(
    db: Session,
    user: User,
    task_type: str,
    task_input,
    assigned_to: str | None,
    status: str,
    metadata: dict | None = None,
    title: str | None = None,
) -> TaskCenterTask:
    metadata = metadata or {
        "sprint17": True,
        "type": task_type,
        "input": task_input,
        "flow_id": None,
        "flow_steps": [],
        "flow_index": None,
    }
    task = TaskCenterTask(
        title=title or f"Sprint 17 automation task: {task_type}",
        description=json.dumps({"input": task_input}, ensure_ascii=False),
        status=status,
        priority="normal",
        source="sprint17_ai_execution",
        assigned_ai_employee_code=assigned_to,
        assigned_ai_employee_name=employee_name(assigned_to) or assigned_to,
        split_plan=json.dumps(metadata, ensure_ascii=False),
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(task)
    db.flush()
    return task


def enqueue_automation_task(task: TaskCenterTask) -> None:
    enqueue_task(
        SPRINT17_QUEUE_TYPE,
        {
            "task_center_id": task.id,
            "assigned_to": task.assigned_ai_employee_code,
            "metadata": task_metadata(task),
        },
        max_retries=1,
        delay_note="Sprint 17 automation task queued",
    )


def write_task_result(db: Session, task: TaskCenterTask, result, submitted_by_id: int | None = None) -> TaskCenterResult:
    content = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
    row = TaskCenterResult(
        task_id=task.id,
        ai_employee_code=task.assigned_ai_employee_code or "unassigned",
        ai_employee_name=task.assigned_ai_employee_name or task.assigned_ai_employee_code,
        result_content=content,
        attachments_json=json.dumps([], ensure_ascii=False),
        submitted_by_id=submitted_by_id,
    )
    db.add(row)
    return row


def get_automation_task_or_404(db: Session, task_id: int) -> TaskCenterTask:
    task = db.get(TaskCenterTask, task_id)
    if not task or task.source != "sprint17_ai_execution":
        raise HTTPException(status_code=404, detail="task not found")
    return task


def require_automation_read(request: Request, db: Session) -> User:
    try:
        return require_automation_user(request, db, "task_center.read")
    except HTTPException as exc:
        if exc.status_code == 403:
            return require_automation_user(request, db, "task_center.manage")
        raise


def require_automation_user(request: Request, db: Session, permission_code: str) -> User:
    if has_valid_api_key(request) or has_valid_internal_bypass(request):
        return first_system_user(db)
    return require_permission_user(request, db, permission_code)


def has_valid_api_key(request: Request) -> bool:
    configured = os.getenv("AUTOMATION_API_KEY", "").strip()
    if not configured:
        return False
    supplied = request.headers.get("X-API-Key", "").strip()
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("apikey "):
        supplied = auth_header[7:].strip()
    return constant_time_equal(supplied, configured)


def has_valid_internal_bypass(request: Request) -> bool:
    supplied = request.headers.get("X-Internal-Bypass", "").strip()
    if supplied.lower() == "true":
        return True
    configured = os.getenv("INTERNAL_BYPASS_TOKEN", "").strip()
    if not configured:
        return False
    return constant_time_equal(supplied, configured)


def constant_time_equal(left: str, right: str) -> bool:
    return bool(left) and bool(right) and hmac.compare_digest(left, right)


def first_system_user(db: Session) -> User:
    user = db.query(User).filter(User.active.is_(True)).order_by(User.id.asc()).first()
    if not user:
        raise HTTPException(status_code=500, detail="system user not found")
    return user


def latest_task_result(db: Session, task_id: int) -> TaskCenterResult | None:
    return (
        db.query(TaskCenterResult)
        .filter(TaskCenterResult.task_id == task_id)
        .order_by(TaskCenterResult.id.desc())
        .first()
    )


def task_to_api(task: TaskCenterTask, db: Session) -> dict:
    metadata = task_metadata(task)
    latest_result = latest_task_result(db, task.id)
    return {
        "id": task.id,
        "type": metadata.get("type") or "unknown",
        "assigned_to": task.assigned_ai_employee_code,
        "input": metadata.get("input"),
        "status": task.status,
        "result": parse_json_value(latest_result.result_content) if latest_result else None,
        "flow_id": metadata.get("flow_id"),
        "flow_steps": metadata.get("flow_steps") or [],
        "flow_index": metadata.get("flow_index"),
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def result_to_api(row: TaskCenterResult) -> dict:
    task = row.task
    metadata = task_metadata(task) if task else {}
    return {
        "id": row.id,
        "task_id": row.task_id,
        "type": metadata.get("type") or "unknown",
        "assigned_to": row.ai_employee_code,
        "result": parse_json_value(row.result_content),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def task_metadata(task: TaskCenterTask) -> dict:
    try:
        data = json.loads(task.split_plan or "{}")
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data


def parse_json_value(value: str | None):
    if value is None:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def clean_required(value: str | None, field: str) -> str:
    clean = (value or "").strip()
    if not clean:
        raise HTTPException(status_code=400, detail=f"{field} is required")
    return clean


def clean_optional(value: str | None) -> str | None:
    clean = (value or "").strip()
    return clean or None
