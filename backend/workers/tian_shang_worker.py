from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.orm import Session

from ..database import get_redis
from ..employee_execution.ai_executor import execute_tian_shang_plan
from ..employee_execution.ai_planner import build_tian_shang_plan
from ..employee_execution.models import EmployeeExecutionContract
from ..models import TaskCenterResult, TaskCenterTask


logger = logging.getLogger("tiantong.tian_shang_worker")

TIAN_SHANG_QUEUE = "tiantong:employee:tianshang:execution"
TIAN_SHANG_EMPLOYEE_ID = "tianshang"
TIAN_SHANG_EMPLOYEE_NAME = "天商：商品中心"
CONTRACT_STATUSES = {"CREATED", "PLANNING", "EXECUTING", "WAITING_TOOL", "COMPLETED", "REVIEWED", "FAILED"}


def create_tian_shang_task(db: Session, goal: str, created_by_id: int | None = None, enqueue: bool = True) -> dict:
    plan = build_tian_shang_plan(goal)
    task = TaskCenterTask(
        title=f"Sprint26 天商真实执行 MVP：{plan['goal']}",
        description=json.dumps({"goal": plan["goal"], "employee": TIAN_SHANG_EMPLOYEE_ID}, ensure_ascii=False),
        status="assigned",
        priority="normal",
        source="sprint26_tian_shang_execution",
        assigned_ai_employee_code=TIAN_SHANG_EMPLOYEE_ID,
        assigned_ai_employee_name=TIAN_SHANG_EMPLOYEE_NAME,
        split_plan=json.dumps(plan, ensure_ascii=False),
        created_by_id=created_by_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    contract = create_contract_for_task(db, task, plan)
    if enqueue:
        enqueue_tian_shang_contract(contract.id)
    return {"task": task_to_dict(task), "contract": contract_to_dict(contract), "queued": enqueue}


def create_contract_for_task(db: Session, task: TaskCenterTask, plan: dict | None = None) -> EmployeeExecutionContract:
    plan = plan or build_tian_shang_plan(task.title)
    contract = EmployeeExecutionContract(
        employee_id=TIAN_SHANG_EMPLOYEE_ID,
        task_id=str(task.id),
        input_data=json.dumps({"goal": plan["goal"], "task_title": task.title}, ensure_ascii=False),
        required_tools=json.dumps(plan["required_tools"], ensure_ascii=False),
        execution_plan=json.dumps(plan, ensure_ascii=False),
        status="CREATED",
        review_status="pending",
        progress=0,
        current_step="等待天商 Worker 领取",
    )
    db.add(contract)
    db.commit()
    db.refresh(contract)
    return contract


def enqueue_tian_shang_contract(contract_id: int) -> dict:
    item = {"contract_id": int(contract_id), "employee_id": TIAN_SHANG_EMPLOYEE_ID, "queued_at": utc_now()}
    get_redis().rpush(TIAN_SHANG_QUEUE, json.dumps(item, ensure_ascii=False))
    return item


def dequeue_tian_shang_contract(timeout: int = 1) -> dict | None:
    try:
        result = get_redis().blpop(TIAN_SHANG_QUEUE, timeout=timeout)
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("tian_shang_queue_warning: %s: %s", type(exc).__name__, exc)
        return None
    if not result:
        return None
    _, raw = result
    return json.loads(raw)


def process_next_tian_shang_execution(db: Session, timeout: int = 1) -> bool:
    item = dequeue_tian_shang_contract(timeout=timeout)
    if not item:
        return False
    contract = db.get(EmployeeExecutionContract, int(item["contract_id"]))
    if not contract or contract.status not in {"CREATED", "PLANNING"}:
        return False
    try:
        execute_contract(db, contract)
        return True
    except Exception as exc:
        contract.status = "FAILED"
        contract.error_log = str(exc)[:1000]
        contract.current_step = "执行失败"
        db.commit()
        logger.exception("tian_shang_execution_failed contract_id=%s", item.get("contract_id"))
        return False


def execute_contract(db: Session, contract: EmployeeExecutionContract) -> EmployeeExecutionContract:
    payload = parse_json(contract.input_data)
    goal = payload.get("goal") or payload.get("task_title") or "分析男士机械表市场"

    contract.status = "PLANNING"
    contract.progress = 20
    contract.current_step = "AI Planner 正在拆解任务"
    plan = build_tian_shang_plan(goal)
    contract.execution_plan = json.dumps(plan, ensure_ascii=False)
    db.commit()

    contract.status = "EXECUTING"
    contract.progress = 45
    contract.current_step = "天商正在执行商品分析"
    db.commit()

    contract.status = "WAITING_TOOL"
    contract.progress = 60
    contract.current_step = "调用内部工具：market_search / data_analysis / report_generator"
    db.commit()

    result = execute_tian_shang_plan(goal, plan)
    contract.result = json.dumps(result, ensure_ascii=False)
    contract.status = "COMPLETED"
    contract.progress = 100
    contract.current_step = "报告已生成，等待复盘审核"
    contract.review_status = "pending_review"
    db.commit()

    write_task_result(db, contract, result)
    db.refresh(contract)
    return contract


def write_task_result(db: Session, contract: EmployeeExecutionContract, result: dict) -> None:
    task = db.get(TaskCenterTask, int(contract.task_id)) if str(contract.task_id).isdigit() else None
    if task:
        task.status = "completed"
        db.add(
            TaskCenterResult(
                task_id=task.id,
                ai_employee_code=TIAN_SHANG_EMPLOYEE_ID,
                ai_employee_name=TIAN_SHANG_EMPLOYEE_NAME,
                result_content=json.dumps(result, ensure_ascii=False),
                attachments_json=json.dumps([], ensure_ascii=False),
            )
        )
        db.commit()


def latest_tian_shang_status(db: Session) -> dict:
    row = (
        db.query(EmployeeExecutionContract)
        .filter(EmployeeExecutionContract.employee_id == TIAN_SHANG_EMPLOYEE_ID)
        .order_by(EmployeeExecutionContract.id.desc())
        .first()
    )
    if not row:
        return {
            "employee_id": TIAN_SHANG_EMPLOYEE_ID,
            "employee_name": TIAN_SHANG_EMPLOYEE_NAME,
            "status": "idle",
            "current_task": None,
            "progress": 0,
            "report_available": False,
        }
    return {
        "employee_id": TIAN_SHANG_EMPLOYEE_ID,
        "employee_name": TIAN_SHANG_EMPLOYEE_NAME,
        "status": row.status.lower(),
        "current_task": parse_json(row.input_data).get("goal") or row.current_step,
        "progress": row.progress,
        "report_available": bool(row.result),
        "contract_id": row.id,
        "review_status": row.review_status,
    }


def contract_to_dict(row: EmployeeExecutionContract) -> dict:
    return {
        "id": row.id,
        "employee_id": row.employee_id,
        "task_id": row.task_id,
        "input": parse_json(row.input_data),
        "required_tools": parse_json(row.required_tools),
        "execution_plan": parse_json(row.execution_plan),
        "result": parse_json(row.result),
        "status": row.status,
        "error_log": row.error_log,
        "review_status": row.review_status,
        "progress": row.progress,
        "current_step": row.current_step,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def task_to_dict(row: TaskCenterTask) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "status": row.status,
        "assigned_ai_employee_code": row.assigned_ai_employee_code,
        "assigned_ai_employee_name": row.assigned_ai_employee_name,
    }


def parse_json(value: str | None):
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
