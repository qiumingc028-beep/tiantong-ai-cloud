from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from ..database import get_redis


BRAIN_EXECUTION_QUEUE = "brain_execution_queue"
BRAIN_EXECUTION_PRIORITY_QUEUES = {
    "high": "brain_execution_queue:high",
    "normal": "brain_execution_queue:normal",
    "low": "brain_execution_queue:low",
}
BRAIN_EXECUTION_QUEUE_ORDER = ["high", "normal", "low"]
BRAIN_EXECUTION_STATUS_PREFIX = "brain_execution_queue:status:"
BRAIN_EXECUTION_RECENT_STATUS = "brain_execution_queue:recent"
BRAIN_EXECUTION_STATUS_TTL_SECONDS = 7 * 24 * 3600


def enqueue_execution(
    execution_id: int,
    *,
    task_id: str | None = None,
    priority: str = "normal",
    max_retry: int = 3,
    payload: dict[str, Any] | None = None,
) -> dict:
    item = {
        "execution_id": int(execution_id),
        "task_id": task_id or f"brain-{execution_id}",
        "priority": priority,
        "status": "waiting",
        "attempt": 0,
        "retry_count": 0,
        "max_retry": int(max_retry),
        "created_at": utc_now(),
        "payload": payload or {},
    }
    get_redis().rpush(queue_name_for_priority(item["priority"]), json.dumps(item, ensure_ascii=False))
    update_queue_status(item, "waiting", "Brain execution queued")
    return item


def dequeue_execution(timeout: int = 5) -> dict | None:
    try:
        result = get_redis().blpop([BRAIN_EXECUTION_PRIORITY_QUEUES[name] for name in BRAIN_EXECUTION_QUEUE_ORDER], timeout=timeout)
    except (RedisTimeoutError, RedisConnectionError):
        return None
    if not result:
        return None
    _, raw = result
    return json.loads(raw)


def requeue_execution(item: dict, message: str) -> dict:
    item["attempt"] = int(item.get("attempt", 0)) + 1
    item["retry_count"] = item["attempt"]
    item["status"] = "waiting"
    item["created_at"] = utc_now()
    get_redis().rpush(queue_name_for_priority(item["priority"]), json.dumps(item, ensure_ascii=False))
    update_queue_status(item, "retrying", message)
    return item


def update_queue_status(item: dict, status: str, message: str = "") -> dict:
    redis_client = get_redis()
    now = utc_now()
    data = {
        "execution_id": int(item["execution_id"]),
        "task_id": item.get("task_id") or f"brain-{item['execution_id']}",
        "priority": item.get("priority", "normal"),
        "status": status,
        "attempt": int(item.get("attempt", 0)),
        "retry_count": int(item.get("retry_count", item.get("attempt", 0))),
        "max_retry": int(item.get("max_retry", 3)),
        "message": message,
        "created_at": item.get("created_at") or now,
        "updated_at": now,
    }
    raw = json.dumps(data, ensure_ascii=False)
    redis_client.setex(f"{BRAIN_EXECUTION_STATUS_PREFIX}{data['execution_id']}", BRAIN_EXECUTION_STATUS_TTL_SECONDS, raw)
    redis_client.lpush(BRAIN_EXECUTION_RECENT_STATUS, raw)
    redis_client.ltrim(BRAIN_EXECUTION_RECENT_STATUS, 0, 199)
    return data


def get_queue_status(limit: int = 100) -> dict:
    redis_client = get_redis()
    priority_waiting = {
        priority: redis_client.llen(queue_name) if hasattr(redis_client, "llen") else 0
        for priority, queue_name in BRAIN_EXECUTION_PRIORITY_QUEUES.items()
    }
    legacy_waiting = redis_client.llen(BRAIN_EXECUTION_QUEUE) if hasattr(redis_client, "llen") else 0
    waiting = sum(priority_waiting.values()) + legacy_waiting
    rows = [json.loads(row) for row in redis_client.lrange(BRAIN_EXECUTION_RECENT_STATUS, 0, max(0, limit - 1))]
    counts = {"waiting": waiting or 0, "running": 0, "success": 0, "failed": 0, "timeout": 0, "retrying": 0}
    for row in rows:
        status = row.get("status")
        if status in counts and status != "waiting":
            counts[status] += 1
    return {
        "queue": BRAIN_EXECUTION_QUEUE,
        "priority_queues": BRAIN_EXECUTION_PRIORITY_QUEUES,
        "priority_waiting": priority_waiting,
        "waiting": counts["waiting"],
        "running": counts["running"],
        "success": counts["success"],
        "failed": counts["failed"],
        "timeout": counts["timeout"],
        "retrying": counts["retrying"],
        "recent": rows,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def queue_name_for_priority(priority: str | None) -> str:
    clean = (priority or "normal").lower()
    return BRAIN_EXECUTION_PRIORITY_QUEUES.get(clean, BRAIN_EXECUTION_PRIORITY_QUEUES["normal"])
