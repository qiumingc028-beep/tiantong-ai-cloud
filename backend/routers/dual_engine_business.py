from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..ai_employees import DEFAULT_STRATEGY_EMPLOYEE
from ..core.orchestrator import handle_event
from ..database import get_db
from ..models import TaskCenterResult, TaskCenterTask
from ..queue_worker import process_next_event
from ..task_queue import ORCHESTRATOR_STATUS_PREFIX
from .ai_execution import require_automation_read, require_automation_user


router = APIRouter()
SOURCE = "sprint18_dual_engine"


class BusinessPayload(BaseModel):
    data: dict
    auto_execute: bool = True


class MoneyLoopStartPayload(BaseModel):
    seed: dict = {}
    cycles: int = 1


class MoneyOptimizePayload(BaseModel):
    feedback: dict = {}


@router.post("/api/business/ecommerce/orders")
def ecommerce_orders(payload: BusinessPayload, request: Request, db: Session = Depends(get_db)):
    user = require_automation_user(request, db, "task_center.manage")
    result = dispatch_business_event("ecommerce_order", payload.data)
    row = write_engine_result(db, user.id, "ecommerce_order", payload.data, result, DEFAULT_STRATEGY_EMPLOYEE)
    return {"ok": True, "engine": "ecommerce", "task_id": row.task_id, "result": result}


@router.post("/api/business/ecommerce/metrics")
def ecommerce_metrics(payload: BusinessPayload, request: Request, db: Session = Depends(get_db)):
    user = require_automation_user(request, db, "task_center.manage")
    result = dispatch_business_event("ecommerce_metrics", payload.data)
    row = write_engine_result(db, user.id, "ecommerce_metrics", payload.data, result, "tianshu")
    return {"ok": True, "engine": "ecommerce", "task_id": row.task_id, "result": result}


@router.post("/api/business/ecommerce/decision")
def ecommerce_decision(payload: BusinessPayload, request: Request, db: Session = Depends(get_db)):
    user = require_automation_user(request, db, "task_center.manage")
    result = dispatch_business_event("dual_engine_decision", payload.data)
    row = write_engine_result(db, user.id, "dual_engine_decision", payload.data, result, DEFAULT_STRATEGY_EMPLOYEE)
    return {"ok": True, "engine": "dual", "task_id": row.task_id, "result": result}


@router.post("/api/content/generate/video")
def generate_video(payload: BusinessPayload, request: Request, db: Session = Depends(get_db)):
    user = require_automation_user(request, db, "task_center.manage")
    result = dispatch_business_event("content_video", payload.data)
    row = write_engine_result(db, user.id, "content_video", payload.data, result, "tianbo")
    return {"ok": True, "engine": "content", "task_id": row.task_id, "result": result}


@router.post("/api/content/generate/xiaohongshu")
def generate_xiaohongshu(payload: BusinessPayload, request: Request, db: Session = Depends(get_db)):
    user = require_automation_user(request, db, "task_center.manage")
    result = dispatch_business_event("content_xiaohongshu", payload.data)
    row = write_engine_result(db, user.id, "content_xiaohongshu", payload.data, result, "tianyu")
    return {"ok": True, "engine": "content", "task_id": row.task_id, "result": result}


@router.post("/api/content/analyze/trend")
def analyze_content_trend(payload: BusinessPayload, request: Request, db: Session = Depends(get_db)):
    user = require_automation_user(request, db, "task_center.manage")
    result = dispatch_business_event("content_trend", payload.data)
    row = write_engine_result(db, user.id, "content_trend", payload.data, result, "tianshu")
    return {"ok": True, "engine": "content", "task_id": row.task_id, "result": result}


@router.post("/api/business/decision-center")
def decision_center(payload: BusinessPayload, request: Request, db: Session = Depends(get_db)):
    user = require_automation_user(request, db, "task_center.manage")
    result = dispatch_business_event("decision_center", payload.data)
    row = write_engine_result(db, user.id, "decision_center", payload.data, result, result["assigned_to"])
    return {"ok": True, "engine": result["engine"], "task_id": row.task_id, "result": result}


@router.get("/api/business/data-lake")
def data_lake(request: Request, db: Session = Depends(get_db)):
    require_automation_read(request, db)
    rows = (
        db.query(TaskCenterResult)
        .join(TaskCenterTask, TaskCenterResult.task_id == TaskCenterTask.id)
        .filter(TaskCenterTask.source == SOURCE)
        .order_by(TaskCenterResult.id.desc())
        .all()
    )
    return {
        "orders": filter_rows(rows, "ecommerce_order"),
        "content_metrics": filter_rows(rows, "content_"),
        "traffic_data": filter_rows(rows, "content_trend"),
        "competitor_data": [],
        "results": [result_to_api(row) for row in rows],
    }


@router.post("/api/money/loop/start")
def start_money_loop(payload: MoneyLoopStartPayload, request: Request, db: Session = Depends(get_db)):
    user = require_automation_user(request, db, "task_center.manage")
    loop_status = dispatch_business_event("money_loop_start", {"seed": payload.seed, "cycles": payload.cycles})
    rows = [
        write_engine_result(db, user.id, "money_loop_cycle", payload.seed, cycle, "tiantong")
        for cycle in loop_status.get("results", [])
    ]
    return {
        "ok": True,
        "status": loop_status,
        "task_ids": [row.task_id for row in rows],
    }


@router.post("/api/money/loop/stop")
def stop_money_loop(request: Request, db: Session = Depends(get_db)):
    require_automation_user(request, db, "task_center.manage")
    return {"ok": True, "status": dispatch_business_event("money_loop_stop", {})}


@router.get("/api/money/loop/status")
def money_loop_status(request: Request, db: Session = Depends(get_db)):
    require_automation_read(request, db)
    return {"ok": True, "status": dispatch_business_event("money_loop_status", {})}


@router.post("/api/money/optimize")
def optimize_money_loop(payload: MoneyOptimizePayload, request: Request, db: Session = Depends(get_db)):
    user = require_automation_user(request, db, "task_center.manage")
    result = dispatch_business_event("money_optimize", {"feedback": payload.feedback})
    row = write_engine_result(db, user.id, "money_loop_optimization", payload.feedback, result, "tiantong")
    return {"ok": True, "task_id": row.task_id, "result": result}


def dispatch_business_event(action: str, payload: dict) -> dict:
    queued = handle_event(
        {
            "source": "api",
            "target": "dual_engine",
            "action": action,
            "payload": payload,
        }
    )
    process_next_event(timeout=1)
    return read_queued_result(queued["event_id"])


def read_queued_result(event_id: str) -> dict:
    from ..database import get_redis

    raw = get_redis().get(f"{ORCHESTRATOR_STATUS_PREFIX}{event_id}")
    if not raw:
        return {"status": "queued", "event_id": event_id}
    data = json.loads(raw)
    result = data.get("result") if isinstance(data.get("result"), dict) else None
    if result and isinstance(result.get("result"), dict):
        return result["result"]
    return {"status": data.get("status"), "event_id": event_id}


def write_engine_result(
    db: Session,
    user_id: int,
    event_type: str,
    payload: dict,
    result: dict,
    assigned_to: str,
) -> TaskCenterResult:
    metadata = {
        "sprint18_dual_engine": True,
        "event_type": event_type,
        "input": payload,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    task = TaskCenterTask(
        title=f"Sprint 18 dual engine: {event_type}",
        description=json.dumps({"input": payload}, ensure_ascii=False),
        status="completed",
        priority="normal",
        source=SOURCE,
        assigned_ai_employee_code=assigned_to,
        assigned_ai_employee_name=assigned_to,
        split_plan=json.dumps(metadata, ensure_ascii=False),
        created_by_id=user_id,
        updated_by_id=user_id,
    )
    db.add(task)
    db.flush()
    row = TaskCenterResult(
        task_id=task.id,
        ai_employee_code=assigned_to,
        ai_employee_name=assigned_to,
        result_content=json.dumps(
            {
                "input": payload,
                "result": result,
                "closed_loop": "data -> analysis -> decision -> internal writeback -> feedback candidate",
                "external_execution": False,
            },
            ensure_ascii=False,
        ),
        attachments_json=json.dumps([], ensure_ascii=False),
        submitted_by_id=user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def filter_rows(rows: list[TaskCenterResult], event_prefix: str) -> list[dict]:
    return [result_to_api(row) for row in rows if event_type(row).startswith(event_prefix)]


def event_type(row: TaskCenterResult) -> str:
    try:
        metadata = json.loads(row.task.split_plan or "{}") if row.task else {}
    except Exception:
        metadata = {}
    return metadata.get("event_type") or ""


def result_to_api(row: TaskCenterResult) -> dict:
    try:
        result = json.loads(row.result_content)
    except Exception:
        result = row.result_content
    return {
        "id": row.id,
        "task_id": row.task_id,
        "event_type": event_type(row),
        "assigned_to": row.ai_employee_code,
        "result": result,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
