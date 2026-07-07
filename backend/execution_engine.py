from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.orm import Session

from .database import get_redis
from .dispatch_models import EmployeeExecutionLog
from .models import TaskCenterResult, TaskCenterTask


logger = logging.getLogger("tiantong.execution_engine")

EXECUTION_QUEUE_NAME = "tiantong:execution:tasks"
EXECUTION_LOCK_PREFIX = "tiantong:execution:lock:"
EXECUTION_LOCK_TTL_SECONDS = 10 * 60
EXECUTION_QUEUE_TYPE = "sprint18_employee_execution"
EXECUTION_STATUSES = {"assigned", "running", "waiting_review", "completed", "failed"}
HIGH_RISK_KEYWORDS = {
    "deploy",
    "deployment",
    "上线",
    "部署",
    "权限",
    "permission",
    "password",
    "secret",
    "token",
    "支付",
    "扣费",
    "删除",
    "drop",
    "truncate",
    "git push",
    "systemctl",
    "docker",
}
SENSITIVE_WORDS = {
    "password",
    "secret",
    "token",
    "api key",
    "authorization",
    "bearer",
    "private_key",
    "access_token",
    "refresh_token",
}


class ExecutionEngineError(RuntimeError):
    pass


class ExecutionLockError(ExecutionEngineError):
    pass


class ExecutionSafetyError(ExecutionEngineError):
    pass


def enqueue_execution_task(db: Session, task: TaskCenterTask, boss_confirmed: bool = False, security_audited: bool = False) -> dict:
    validate_claimable_task(task)
    enforce_high_risk_approval(task, boss_confirmed=boss_confirmed, security_audited=security_audited)
    payload = {
        "queue_item_id": str(uuid.uuid4()),
        "task_id": task.id,
        "employee_code": task.assigned_ai_employee_code,
        "employee_name": task.assigned_ai_employee_name,
        "task_status": task.status,
        "risk_level": infer_execution_risk(task),
        "boss_confirmed": bool(boss_confirmed),
        "security_audited": bool(security_audited),
        "queued_at": utc_now(),
    }
    try:
        get_redis().rpush(EXECUTION_QUEUE_NAME, json.dumps(payload, ensure_ascii=False))
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("execution_queue_push_warning: %s: %s", type(exc).__name__, exc)
        raise ExecutionEngineError("execution queue unavailable") from exc
    write_execution_log(
        db,
        task,
        status="assigned",
        action="execution_queued",
        input_data=task_input_summary(task),
        output_data={"queue": EXECUTION_QUEUE_NAME, "queue_item_id": payload["queue_item_id"]},
        tool_used=[],
    )
    db.commit()
    return payload


def pop_execution_task(timeout: int = 5) -> dict | None:
    try:
        result = get_redis().blpop(EXECUTION_QUEUE_NAME, timeout=timeout)
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("execution_queue_read_warning: %s: %s", type(exc).__name__, exc)
        return None
    if not result:
        return None
    _, raw = result
    return json.loads(raw)


def process_next_execution_task(db: Session, timeout: int = 1, worker_id: str = "employee_worker") -> bool:
    item = pop_execution_task(timeout=timeout)
    if not item:
        return False
    task = db.get(TaskCenterTask, int(item["task_id"]))
    if not task:
        return False
    if not acquire_execution_lock(task.id, worker_id):
        logger.warning("execution_task_lock_busy task_id=%s worker_id=%s", task.id, worker_id)
        return False
    try:
        start_task_execution(
            db,
            task,
            worker_id=worker_id,
            boss_confirmed=truthy(item.get("boss_confirmed")),
            security_audited=truthy(item.get("security_audited")),
        )
        output = build_mock_execution_output(task)
        complete_task_execution(db, task, output_data=output, waiting_review=False, worker_id=worker_id)
        return True
    except Exception as exc:
        fail_task_execution(db, task, error_message=str(exc), worker_id=worker_id)
        raise
    finally:
        release_execution_lock(task.id, worker_id)


def start_task_execution(
    db: Session,
    task: TaskCenterTask,
    worker_id: str = "api",
    boss_confirmed: bool = False,
    security_audited: bool = False,
) -> EmployeeExecutionLog:
    enforce_high_risk_approval(task, boss_confirmed=boss_confirmed, security_audited=security_audited)
    if task.status != "assigned":
        raise ExecutionEngineError(f"task must be assigned before running, current={task.status}")
    if not task.assigned_ai_employee_code:
        raise ExecutionEngineError("task has no assigned employee")
    task.status = "running"
    log = write_execution_log(
        db,
        task,
        status="running",
        action="execution_started",
        input_data=task_input_summary(task),
        output_data={"worker_id": worker_id},
        tool_used=[],
        started_at=now_utc(),
    )
    db.commit()
    db.refresh(log)
    return log


def complete_task_execution(
    db: Session,
    task: TaskCenterTask,
    output_data,
    waiting_review: bool = False,
    worker_id: str = "api",
) -> EmployeeExecutionLog:
    if task.status not in {"running", "waiting_review"}:
        raise ExecutionEngineError(f"task must be running before completion, current={task.status}")
    task.status = "waiting_review" if waiting_review else "completed"
    output = sanitize_payload(output_data)
    log = write_execution_log(
        db,
        task,
        status=task.status,
        action="execution_completed" if task.status == "completed" else "execution_waiting_review",
        input_data=task_input_summary(task),
        output_data=output,
        tool_used=["mock_executor"],
        finished_at=now_utc(),
    )
    if task.status == "completed":
        db.add(
            TaskCenterResult(
                task_id=task.id,
                ai_employee_code=task.assigned_ai_employee_code or "unassigned",
                ai_employee_name=task.assigned_ai_employee_name or task.assigned_ai_employee_code,
                result_content=json.dumps(output, ensure_ascii=False),
                attachments_json=json.dumps([], ensure_ascii=False),
            )
        )
    db.commit()
    db.refresh(log)
    return log


def fail_task_execution(db: Session, task: TaskCenterTask, error_message: str, worker_id: str = "api") -> EmployeeExecutionLog:
    task.status = "failed"
    log = write_execution_log(
        db,
        task,
        status="failed",
        action="execution_failed",
        input_data=task_input_summary(task),
        output_data={"worker_id": worker_id},
        tool_used=[],
        error_message=redact_text(error_message),
        finished_at=now_utc(),
    )
    db.commit()
    db.refresh(log)
    return log


def acquire_execution_lock(task_id: int, owner: str, ttl_seconds: int = EXECUTION_LOCK_TTL_SECONDS) -> bool:
    key = execution_lock_key(task_id)
    redis_client = get_redis()
    try:
        if hasattr(redis_client, "set"):
            return bool(redis_client.set(key, owner, nx=True, ex=ttl_seconds))
        if redis_client.get(key):
            return False
        redis_client.setex(key, ttl_seconds, owner)
        return True
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("execution_lock_warning: %s: %s", type(exc).__name__, exc)
        return False


def release_execution_lock(task_id: int, owner: str) -> None:
    key = execution_lock_key(task_id)
    redis_client = get_redis()
    try:
        current = redis_client.get(key)
        if decode_redis_value(current) in {owner, None}:
            redis_client.delete(key)
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("execution_lock_release_warning: %s: %s", type(exc).__name__, exc)


def execution_lock_key(task_id: int) -> str:
    return f"{EXECUTION_LOCK_PREFIX}{task_id}"


def validate_claimable_task(task: TaskCenterTask) -> None:
    if task.status != "assigned":
        raise ExecutionEngineError(f"task status must be assigned, current={task.status}")
    if not task.assigned_ai_employee_code:
        raise ExecutionEngineError("task has no assigned employee")


def enforce_high_risk_approval(task: TaskCenterTask, boss_confirmed: bool, security_audited: bool) -> None:
    if infer_execution_risk(task) in {"high", "critical"} and not (boss_confirmed and security_audited):
        raise ExecutionSafetyError("high risk execution requires boss confirmation and security audit")


def infer_execution_risk(task: TaskCenterTask) -> str:
    text = f"{task.title or ''} {task.description or ''} {task.priority or ''}".lower()
    if any(keyword in text for keyword in HIGH_RISK_KEYWORDS):
        return "critical" if any(keyword in text for keyword in {"deploy", "deployment", "部署", "上线", "docker"}) else "high"
    return "low"


def write_execution_log(
    db: Session,
    task: TaskCenterTask,
    status: str,
    action: str,
    input_data=None,
    output_data=None,
    tool_used=None,
    error_message: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> EmployeeExecutionLog:
    if status not in EXECUTION_STATUSES:
        raise ExecutionEngineError(f"invalid execution status: {status}")
    row = EmployeeExecutionLog(
        task_id=task.id,
        employee_code=task.assigned_ai_employee_code or "unassigned",
        action=action,
        result=json.dumps(sanitize_payload(output_data), ensure_ascii=False) if output_data is not None else None,
        status=status,
        input_data=json.dumps(sanitize_payload(input_data), ensure_ascii=False) if input_data is not None else None,
        output_data=json.dumps(sanitize_payload(output_data), ensure_ascii=False) if output_data is not None else None,
        tool_used=json.dumps(sanitize_payload(tool_used or []), ensure_ascii=False),
        error_message=redact_text(error_message) if error_message else None,
        started_at=started_at,
        finished_at=finished_at,
    )
    db.add(row)
    return row


def execution_log_to_dict(row: EmployeeExecutionLog) -> dict:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "employee_code": row.employee_code,
        "status": row.status or row.action,
        "input_data": parse_json(row.input_data),
        "output_data": parse_json(row.output_data),
        "tool_used": parse_json(row.tool_used),
        "error_message": row.error_message,
        "started_at": iso(row.started_at),
        "finished_at": iso(row.finished_at),
        "created_at": iso(row.created_at),
    }


def task_input_summary(task: TaskCenterTask) -> dict:
    return {
        "task_id": task.id,
        "title": redact_text(task.title),
        "description": redact_text(task.description),
        "assigned_to": task.assigned_ai_employee_code,
        "priority": task.priority,
        "source": task.source,
    }


def build_mock_execution_output(task: TaskCenterTask) -> dict:
    return {
        "mode": "mock_execution",
        "task_id": task.id,
        "employee_code": task.assigned_ai_employee_code,
        "summary": f"{task.assigned_ai_employee_name or task.assigned_ai_employee_code} 已完成受控模拟执行，等待人工验收。",
        "safety_boundary": [
            "不自动部署",
            "不自动修改权限",
            "不自动提交代码",
            "不自动调用高风险工具",
        ],
    }


def sanitize_payload(value):
    if isinstance(value, dict):
        return {
            redact_text(str(key)): "[REDACTED]" if is_sensitive_key(str(key)) else sanitize_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value)
    lowered = text.lower()
    if any(word in lowered for word in SENSITIVE_WORDS):
        return "[REDACTED]"
    return text


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(word in lowered for word in SENSITIVE_WORDS)


def parse_json(value: str | None):
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def decode_redis_value(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def utc_now() -> str:
    return now_utc().isoformat()


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
