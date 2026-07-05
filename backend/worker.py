import time
from datetime import datetime, timezone

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .database import SessionLocal
from .models import EmployeeLog, JdSyncLog
from .queue import dequeue_task, requeue_task, update_task_status
from .services.ai_store_manager import analyze_store_health
from .services.jd_collectors import (
    JdCollectorError,
    sync_jd_orders,
    sync_jd_products,
    sync_jd_smart,
    sync_jzt,
)


SUPPORTED_TASK_TYPES = {
    "sync_jd_smart",
    "sync_jzt",
    "sync_jd_orders",
    "sync_jd_products",
    "ai_store_manager_daily",
}


def handle_task(task):
    task_id = task["task_id"]
    task_type = task["task_type"]
    payload = task.get("payload", {})
    attempt = int(task.get("attempt", 0))
    max_retries = int(task.get("max_retries", 3))
    db = SessionLocal()
    log = JdSyncLog(
        store_id=payload.get("store_id"),
        task_id=task_id,
        task_type=task_type,
        status="running",
        attempt=attempt,
        started_at=datetime.now(timezone.utc),
    )
    db.add(log)
    db.commit()
    update_task_status(task_id, "running", task_type, payload, message="任务执行中", attempt=attempt, max_retries=max_retries)
    try:
        if task_type == "sync_jd_smart":
            result = sync_jd_smart(db, int(payload["store_id"]))
        elif task_type == "sync_jzt":
            result = sync_jzt(db, int(payload["store_id"]))
        elif task_type == "sync_jd_orders":
            result = sync_jd_orders(db, int(payload["store_id"]))
        elif task_type == "sync_jd_products":
            result = sync_jd_products(db, int(payload["store_id"]))
        elif task_type == "ai_store_manager_daily":
            result = {"suggestions": analyze_store_health(db)}
            write_employee_log(db, task_type, "success", result, attempt, max_retries)
        else:
            raise RuntimeError(f"未知任务类型: {task_type}")
        log.status = "success"
        log.message = str(result)
        log.finished_at = datetime.now(timezone.utc)
        db.commit()
        update_task_status(task_id, "success", task_type, payload, message="任务执行成功", attempt=attempt, max_retries=max_retries)
    except Exception as exc:
        db.rollback()
        log.status = "failed"
        log.message = str(exc)
        log.finished_at = datetime.now(timezone.utc)
        db.add(log)
        if task_type == "ai_store_manager_daily":
            write_employee_log(db, task_type, "failed", {"error": str(exc)}, attempt, max_retries)
        db.commit()
        if attempt < max_retries:
            requeue_task(task, f"执行失败，准备重试: {exc}")
        else:
            update_task_status(task_id, "failed", task_type, payload, message=str(exc), attempt=attempt, max_retries=max_retries)
        raise
    finally:
        db.close()


def write_employee_log(db, task_type: str, status: str, detail: dict, attempt: int, max_retries: int):
    db.add(
        EmployeeLog(
            action=task_type,
            detail=str(
                {
                    "status": status,
                    "detail": detail,
                    "retry_count": attempt,
                    "max_retries": max_retries,
                    "last_executed_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
        )
    )


def main():
    while True:
        process_next_task()
        time.sleep(0.1)


def process_next_task():
    try:
        task = dequeue_task(timeout=5)
    except (RedisTimeoutError, RedisConnectionError) as exc:
        print(f"Redis queue warning: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(2)
        return False
    if not task:
        return False
    try:
        handle_task(task)
    except JdCollectorError as exc:
        print(f"采集任务未完成: {exc}", flush=True)
    except Exception as exc:
        print(f"任务执行失败: {exc}", flush=True)
    return True


if __name__ == "__main__":
    main()
