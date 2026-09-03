import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from .database import get_redis
from .logging_config import configure_json_logging


QUEUE_NAME = "tiantong:tasks"
PROCESSING_QUEUE_NAME = f"{QUEUE_NAME}:processing"
PROCESSING_METADATA_PREFIX = f"{QUEUE_NAME}:processing:"
PROCESSING_DEADLINES_KEY = f"{QUEUE_NAME}:processing:deadlines"
PROCESSING_GENERATION_PREFIX = f"{QUEUE_NAME}:claim-generation:"
STATUS_PREFIX = "tiantong:task_status:"
RECENT_STATUS_KEY = "tiantong:task_status_recent"
STATUS_TTL_SECONDS = 7 * 24 * 3600
configure_json_logging()
logger = logging.getLogger("tiantong.queue")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def enqueue_task(
    task_type: str,
    payload: dict,
    max_retries: int = 3,
    delay_note: str | None = None,
    *,
    task_id: str | None = None,
    attempt: int = 0,
):
    task_id = task_id or str(uuid.uuid4())
    item = {
        "task_id": task_id,
        "task_type": task_type,
        "payload": payload,
        "attempt": attempt,
        "max_retries": max_retries,
        "queued_at": utc_now(),
    }
    redis_client = get_redis()
    redis_client.rpush(QUEUE_NAME, json.dumps(item, ensure_ascii=False))
    update_task_status(task_id, "queued", task_type, payload, message=delay_note or "任务已进入队列", attempt=attempt, max_retries=max_retries)
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


_CLAIM_SCRIPT = """
local raw = redis.call('LPOP', KEYS[1])
if not raw then return nil end
local task = cjson.decode(raw)
local generation_key = ARGV[7] .. task['task_id']
local current_generation = tonumber(redis.call('GET', generation_key) or 0)
local payload_generation = tonumber(task['claim_generation'] or 0)
if payload_generation > current_generation then current_generation = payload_generation end
task['claim_generation'] = current_generation + 1
redis.call('SET', generation_key, tostring(task['claim_generation']), 'EX', ARGV[8])
raw = cjson.encode(task)
local payload = task['payload'] or {}
local lease_id = task['task_id'] .. ':' .. tostring(task['claim_generation'])
local metadata = ARGV[1] .. lease_id
redis.call('RPUSH', KEYS[2], raw)
redis.call('HSET', metadata,
  'task_id', task['task_id'],
  'tenant_id', tostring(payload['tenant_id'] or ''),
  'company_id', tostring(payload['company_id'] or ''),
  'store_id', tostring(payload['store_id'] or ''),
  'sync_window_started_at', tostring(payload['sync_window_started_at'] or ''),
  'claimed_by', ARGV[2],
  'claim_generation', tostring(task['claim_generation']),
  'started_at', ARGV[3],
  'heartbeat_at', ARGV[3],
  'visibility_deadline', ARGV[4])
redis.call('EXPIRE', metadata, ARGV[5])
redis.call('ZADD', KEYS[3], ARGV[6], lease_id)
return raw
"""


def _lease_id(task: dict) -> str:
    return f"{task['task_id']}:{task.get('claim_generation', '')}"


def _metadata_key(task: dict) -> str:
    return f"{PROCESSING_METADATA_PREFIX}{_lease_id(task)}"


def claim_task(worker_id: str, timeout: int = 5, visibility_timeout: int = 120):
    """Atomically move one ready task into processing and record its lease."""
    redis_client = get_redis()
    stop_at = time.monotonic() + timeout
    raw = None
    while raw is None:
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(seconds=visibility_timeout)
        try:
            raw = redis_client.eval(
                _CLAIM_SCRIPT,
                3,
                QUEUE_NAME,
                PROCESSING_QUEUE_NAME,
                PROCESSING_DEADLINES_KEY,
                PROCESSING_METADATA_PREFIX,
                worker_id,
                now.isoformat(),
                deadline.isoformat(),
                str(max(visibility_timeout * 3, 300)),
                str(deadline.timestamp()),
                PROCESSING_GENERATION_PREFIX,
                str(STATUS_TTL_SECONDS),
            )
        except (RedisTimeoutError, RedisConnectionError) as exc:
            logger.warning("redis_queue_read_warning: %s: %s", type(exc).__name__, exc)
            return None
        if raw is not None or timeout == 0 or time.monotonic() >= stop_at:
            break
        time.sleep(0.1)
    if not raw:
        return None
    task = json.loads(raw)
    task["_processing_raw"] = raw
    return task


def dequeue_task(timeout: int = 5):
    """Compatibility interface; claimed tasks still require explicit acknowledgement."""
    return claim_task(worker_id=f"worker-{uuid.uuid4()}", timeout=timeout)


def heartbeat_task(
    task: dict,
    worker_id: str,
    *,
    now: datetime | None = None,
    visibility_timeout: int = 120,
) -> bool:
    now = now or datetime.now(timezone.utc)
    metadata_key = _metadata_key(task)
    redis_client = get_redis()
    deadline = now + timedelta(seconds=visibility_timeout)
    return bool(redis_client.eval(
        _HEARTBEAT_SCRIPT,
        2,
        metadata_key,
        PROCESSING_DEADLINES_KEY,
        worker_id,
        now.isoformat(),
        deadline.isoformat(),
        str(max(visibility_timeout * 3, 300)),
        _lease_id(task),
        str(deadline.timestamp()),
    ))


_HEARTBEAT_SCRIPT = """
if redis.call('HGET', KEYS[1], 'claimed_by') ~= ARGV[1] then return 0 end
redis.call('HSET', KEYS[1], 'heartbeat_at', ARGV[2], 'visibility_deadline', ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[4])
redis.call('ZADD', KEYS[2], ARGV[6], ARGV[5])
return 1
"""


_ACK_SCRIPT = """
if redis.call('HGET', KEYS[2], 'claimed_by') ~= ARGV[2] then return 0 end
if redis.call('HGET', KEYS[2], 'task_id') ~= ARGV[3] then return 0 end
if redis.call('HGET', KEYS[2], 'claim_generation') ~= ARGV[4] then return 0 end
if redis.call('LREM', KEYS[1], 1, ARGV[1]) == 0 then return 0 end
redis.call('DEL', KEYS[2])
redis.call('ZREM', KEYS[3], ARGV[3] .. ':' .. ARGV[4])
return 1
"""


def ack_task(task: dict, worker_id: str, raw: str | None = None) -> bool:
    raw = raw or task.get("_processing_raw")
    if not raw:
        return False
    redis_client = get_redis()
    return bool(redis_client.eval(
        _ACK_SCRIPT,
        3,
        PROCESSING_QUEUE_NAME,
        _metadata_key(task),
        PROCESSING_DEADLINES_KEY,
        raw,
        worker_id,
        task["task_id"],
        str(task.get("claim_generation", "")),
    ))


_NACK_SCRIPT = """
if redis.call('HGET', KEYS[2], 'claimed_by') ~= ARGV[2] then return 0 end
if redis.call('HGET', KEYS[2], 'task_id') ~= ARGV[3] then return 0 end
if redis.call('HGET', KEYS[2], 'claim_generation') ~= ARGV[4] then return 0 end
if redis.call('LREM', KEYS[1], 1, ARGV[1]) == 0 then return 0 end
redis.call('LPUSH', KEYS[4], ARGV[1])
redis.call('DEL', KEYS[2])
redis.call('ZREM', KEYS[3], ARGV[3] .. ':' .. ARGV[4])
return 1
"""


def nack_task(task: dict, worker_id: str, raw: str | None = None) -> bool:
    """Return a temporarily unclaimable task without losing its lease identity."""
    raw = raw or task.get("_processing_raw")
    if not raw:
        return False
    return bool(get_redis().eval(
        _NACK_SCRIPT,
        4,
        PROCESSING_QUEUE_NAME,
        _metadata_key(task),
        PROCESSING_DEADLINES_KEY,
        QUEUE_NAME,
        raw,
        worker_id,
        task["task_id"],
        str(task.get("claim_generation", "")),
    ))


_REAP_EXPIRED_SCRIPT = """
local deadline = redis.call('HGET', KEYS[3], 'visibility_deadline')
if deadline and deadline > ARGV[3] then return 0 end
if redis.call('LREM', KEYS[1], 1, ARGV[1]) == 0 then return 0 end
redis.call('RPUSH', KEYS[2], ARGV[1])
redis.call('DEL', KEYS[3])
redis.call('ZREM', KEYS[4], ARGV[2])
return 1
"""


def reap_expired_tasks(*, now: datetime | None = None, before_requeue=None) -> list[dict]:
    """Return expired leases after their durable state is ready to be claimed."""
    now = now or datetime.now(timezone.utc)
    redis_client = get_redis()
    recovered = []
    expired_ids = set(redis_client.zrangebyscore(PROCESSING_DEADLINES_KEY, "-inf", now.timestamp()))
    for raw in redis_client.lrange(PROCESSING_QUEUE_NAME, 0, -1):
        task = json.loads(raw)
        lease_id = _lease_id(task)
        if lease_id not in expired_ids:
            continue
        if before_requeue is not None and not before_requeue(task):
            continue
        if redis_client.eval(
            _REAP_EXPIRED_SCRIPT,
            4,
            PROCESSING_QUEUE_NAME,
            QUEUE_NAME,
            _metadata_key(task),
            PROCESSING_DEADLINES_KEY,
            raw,
            lease_id,
            now.isoformat(),
        ):
            recovered.append(task)
    return recovered


def update_task_status(
    task_id: str,
    status: str,
    task_type: str,
    payload: dict,
    message: str = "",
    attempt: int = 0,
    max_retries: int | None = None,
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
