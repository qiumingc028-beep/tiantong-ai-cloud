from __future__ import annotations

from typing import Optional
import json
import uuid
from datetime import datetime, timezone

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .database import get_redis


QUEUE_NAME = "tiantong:tasks"
STATUS_PREFIX = "tiantong:task_status:"
RECENT_STATUS_KEY = "tiantong:task_status_recent"
STATUS_TTL_SECONDS = 7 * 24 * 3600


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def enqueue_task(task_type: str, payload: dict, max_retries: int = 3, delay_note: Optional[str] = None):
    task_id = str(uuid.uuid4())
    item = {
        "task_id": task_id,
        "task_type": task_type,
        "payload": payload,
        "attempt": 0,
        "max_retries": max_retries,
        "queued_at": utc_now(),
    }
    redis_client = get_redis()
    redis_client.rpush(QUEUE_NAME, json.dumps(item, ensure_ascii=False))
    update_task_status(task_id, "queued", task_type, payload, message=delay_note or "任务已进入队列", attempt=0, max_retries=max_retries)
    return item


def requeue_task(task: dict, message: str):
    task["attempt"] = int(task.get("attempt", 0)) + 1
    task["queued_at"] = utc_now()
    get_redis().rpush(QUEUE_NAME, json.dumps(task, ensure_ascii=False))
    update_task_status(
        task["task_id"],
        "retrying",
        task["task_type"],
        task.get("payload", {}),
        message=message,
        attempt=task["attempt"],
        max_retries=int(task.get("max_retries", 3)),
    )


def dequeue_task(timeout: int = 5):
    try:
        result = get_redis().blpop(QUEUE_NAME, timeout=timeout)
    except (RedisTimeoutError, RedisConnectionError) as exc:
        print(f"Redis queue read warning: {type(exc).__name__}: {exc}", flush=True)
        return None
    if not result:
        return None
    _, raw = result
    return json.loads(raw)


def update_task_status(
    task_id: str,
    status: str,
    task_type: str,
    payload: dict,
    message: str = "",
    attempt: int = 0,
    max_retries: Optional[int] = None,
):
    redis_client = get_redis()
    now = utc_now()
    data = {
        "task_id": task_id,
        "status": status,
        "task_type": task_type,
        "payload": payload,
        "message": message,
        "attempt": attempt,
        "retry_count": attempt,
        "max_retries": max_retries,
        "last_executed_at": now,
        "updated_at": now,
    }
    raw = json.dumps(data, ensure_ascii=False)
    redis_client.setex(f"{STATUS_PREFIX}{task_id}", STATUS_TTL_SECONDS, raw)
    redis_client.lpush(RECENT_STATUS_KEY, raw)
    redis_client.ltrim(RECENT_STATUS_KEY, 0, 199)
    return data


def get_recent_task_status(limit: int = 50):
    rows = get_redis().lrange(RECENT_STATUS_KEY, 0, max(0, limit - 1))
    return [json.loads(row) for row in rows]


def get_queue_status(limit: int = 50):
    redis_client = get_redis()
    pending = len(getattr(redis_client, "lists", {}).get(QUEUE_NAME, [])) if hasattr(redis_client, "lists") else None
    if hasattr(redis_client, "llen"):
        pending = redis_client.llen(QUEUE_NAME)
    return {
        "name": QUEUE_NAME,
        "pending": pending,
        "recent": get_recent_task_status(limit),
    }
