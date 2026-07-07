from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .database import get_redis


ORCHESTRATOR_QUEUE_NAME = "tiantong:orchestrator:events"
ORCHESTRATOR_STATUS_PREFIX = "tiantong:orchestrator:event_status:"
ORCHESTRATOR_STATUS_TTL_SECONDS = 7 * 24 * 3600


def push_queue(event: dict, route: dict | None = None, max_retries: int = 3) -> dict:
    event_id = str(uuid.uuid4())
    item = {
        "event_id": event_id,
        "event": event,
        "route": route or {},
        "attempt": 0,
        "max_retries": max_retries,
        "queued_at": utc_now(),
    }
    get_redis().rpush(ORCHESTRATOR_QUEUE_NAME, json.dumps(item, ensure_ascii=False))
    update_event_status(event_id, "queued", item)
    return item


def pop_queue(timeout: int = 5) -> dict | None:
    try:
        result = get_redis().blpop(ORCHESTRATOR_QUEUE_NAME, timeout=timeout)
    except (RedisTimeoutError, RedisConnectionError):
        return None
    if not result:
        return None
    _, raw = result
    return json.loads(raw)


def requeue_event(item: dict, message: str) -> dict:
    item["attempt"] = int(item.get("attempt", 0)) + 1
    item["queued_at"] = utc_now()
    get_redis().rpush(ORCHESTRATOR_QUEUE_NAME, json.dumps(item, ensure_ascii=False))
    update_event_status(item["event_id"], "retrying", item, message)
    return item


def update_event_status(event_id: str, status: str, item: dict, message: str = "") -> dict:
    data = {
        "event_id": event_id,
        "status": status,
        "route": item.get("route", {}),
        "event": item.get("event", {}),
        "attempt": int(item.get("attempt", 0)),
        "max_retries": int(item.get("max_retries", 3)),
        "message": message,
        "result": item.get("result"),
        "self_healing": item.get("self_healing"),
        "updated_at": utc_now(),
    }
    get_redis().setex(
        f"{ORCHESTRATOR_STATUS_PREFIX}{event_id}",
        ORCHESTRATOR_STATUS_TTL_SECONDS,
        json.dumps(data, ensure_ascii=False),
    )
    return data


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
