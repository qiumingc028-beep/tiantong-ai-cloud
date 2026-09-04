import contextlib
import logging
import json
import os
import socket
import threading
import time
import uuid
from datetime import date, datetime, timezone, timedelta

from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .config import get_settings, require_service_role
from .agent_runtime import models as agent_runtime_models  # noqa: F401
from .agent_runtime.executors.computer.actions import models as computer_action_models  # noqa: F401
from .alpha_workflow import models as alpha_workflow_models  # noqa: F401
from .device_center import models as device_center_models  # noqa: F401
from .observability import models as observability_models  # noqa: F401
from .skills_engine import models as skills_engine_models  # noqa: F401

from .ai_employees import DEFAULT_COLLECTOR_EMPLOYEE, DEFAULT_STRATEGY_EMPLOYEE, FLOW_EMPLOYEE_CODES, FLOW_TASK_TYPES, employee_name, normalize_employee_code
from .core.orchestrator import handle_event
from .database import SessionLocal, get_redis
from .brain_execution.worker import process_next_execution as process_next_brain_execution
from .brain_orchestrator.planner import resolve_graph_ownership
from .execution_engine import process_next_execution_task
from .logging_config import configure_json_logging
from .models import EmployeeLog, JdSyncLog, JdWorkbenchSyncPolicy, JdWorkbenchStoreStatus, Store, TaskCenterResult, TaskCenterTask, User
from .models import JdWorkbenchDevice
from sqlalchemy import and_, or_
from .task_center_ownership import (
    bind_task_ownership_from_task,
    owned_task_from_context_or_none,
    task_ownership_context,
)
from .queue_worker import process_next_event
from .queue import (
    PROCESSING_QUEUE_NAME,
    ack_task,
    claim_task,
    discard_processing_task,
    enqueue_task,
    ensure_task_delivery,
    heartbeat_task,
    nack_task,
    reap_expired_tasks,
    retry_claimed_task,
    update_task_status,
)
from .services.ai_store_manager import analyze_store_health
from .services.jd_collectors import (
    JdCollectorError,
    sync_jd_orders,
    sync_jd_products,
    sync_jd_smart,
    sync_jzt,
)
from .workers.tian_shang_worker import process_next_tian_shang_execution


WORKER_HEARTBEAT_KEY = "tiantong:worker:heartbeat"
WORKER_HEARTBEAT_TTL_SECONDS = 120
DAILY_SCHEDULER_PREFIX = "tiantong:scheduler:daily:"
DAILY_SCHEDULER_OWNERSHIP_SOURCE = "daily_scheduler_ownership_source"
configure_json_logging()
logger = logging.getLogger("tiantong.worker")

SUPPORTED_TASK_TYPES = {
    "sync_jd_smart",
    "sync_jzt",
    "sync_jd_orders",
    "sync_jd_products",
    "ai_store_manager_daily",
    "sprint17_ai_task",
    "sprint18_business_loop",
}
SPRINT17_QUEUE_TYPE = "sprint17_ai_task"
SPRINT18_QUEUE_TYPE = "sprint18_business_loop"
JD_WORKBENCH_LEASE_PREFIX = "tiantong:jd-workbench:lease:"
JD_RETRY_BACKOFF_SECONDS = (30, 120, 300, 900, 1800)
JD_TASK_VISIBILITY_SECONDS = max(5, int(os.getenv("JD_TASK_VISIBILITY_SECONDS", "120")))
JD_SCHEDULER_POLL_SECONDS = max(1, int(os.getenv("JD_SCHEDULER_POLL_SECONDS", "30")))


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _sync_window(now: datetime, interval_seconds: int) -> datetime:
    start = int(now.timestamp()) // interval_seconds * interval_seconds
    return datetime.fromtimestamp(start, tz=timezone.utc)


def _clear_policy_lease(policy: JdWorkbenchSyncPolicy) -> None:
    policy.active_task_id = None
    policy.queue_state = None
    policy.lease_worker_id = None
    policy.lease_started_at = None
    policy.lease_heartbeat_at = None
    policy.visibility_deadline = None


def _status_rows(db, policy: JdWorkbenchSyncPolicy):
    return db.query(JdWorkbenchStoreStatus).join(
        JdWorkbenchDevice,
        JdWorkbenchDevice.device_id == JdWorkbenchStoreStatus.device_id,
    ).filter(
        JdWorkbenchStoreStatus.store_id == policy.store_id,
        JdWorkbenchDevice.tenant_id == policy.tenant_id,
        JdWorkbenchDevice.company_id == policy.company_id,
        JdWorkbenchDevice.revoked_at.is_(None),
    ).all()


def run_jd_workbench_scheduler(now=None):
    """Cloud-owned five-minute scheduler; desktop presence is not required."""
    now = now or datetime.now(timezone.utc)
    scheduled = 0
    lookup = SessionLocal()
    try:
        policy_ids = [row[0] for row in lookup.query(JdWorkbenchSyncPolicy.id).filter(JdWorkbenchSyncPolicy.enabled.is_(True)).all()]
    finally:
        lookup.close()
    for policy_id in policy_ids:
        db = SessionLocal()
        try:
            policy = db.query(JdWorkbenchSyncPolicy).filter(
                JdWorkbenchSyncPolicy.id == policy_id,
                JdWorkbenchSyncPolicy.enabled.is_(True),
            ).with_for_update(skip_locked=True).one_or_none()
            if policy is None:
                continue
            statuses = _status_rows(db, policy)
            status = statuses[0] if statuses else None
            if status and status.next_sync_at and status.next_sync_at > now:
                continue
            if policy.active_task_id:
                # PostgreSQL is authoritative; only the generation-fenced reaper
                # may recover an expired processing claim.
                continue
            window_started_at = _sync_window(now, policy.interval_seconds)
            previous_attempt = db.query(JdSyncLog).filter(
                JdSyncLog.tenant_id == policy.tenant_id,
                JdSyncLog.company_id == policy.company_id,
                JdSyncLog.store_id == policy.store_id,
                JdSyncLog.sync_window_started_at == window_started_at,
                JdSyncLog.task_type == "sync_jd_smart",
            ).order_by(JdSyncLog.attempt.desc()).first()
            if previous_attempt and previous_attempt.status == "success":
                _clear_policy_lease(policy)
                for status_row in statuses:
                    status_row.status = "IDLE"
                    status_row.reason_code = None
                    status_row.last_sync_at = previous_attempt.finished_at or now
                    status_row.retry_count = 0
                    status_row.last_error_at = None
                db.commit()
                continue
            task_id = previous_attempt.task_id if previous_attempt else str(uuid.uuid4())
            attempt = previous_attempt.attempt + 1 if previous_attempt else 0
            policy.active_task_id = task_id
            policy.queue_state = "ready"
            policy.visibility_deadline = now + timedelta(seconds=JD_TASK_VISIBILITY_SECONDS)
            policy.sync_window_started_at = window_started_at
            for status_row in statuses:
                status_row.status = "IDLE"
                status_row.last_attempt_at = now
                status_row.next_sync_at = now + timedelta(seconds=policy.interval_seconds)
            db.commit()
            try:
                enqueue_task(
                    "sync_jd_smart",
                    {
                        "tenant_id": policy.tenant_id,
                        "company_id": policy.company_id,
                        "store_id": policy.store_id,
                        "source": "cloud_scheduler",
                        "scheduled_at": now.isoformat(),
                        "sync_window_started_at": window_started_at.isoformat(),
                    },
                    max_retries=5,
                    task_id=task_id,
                    attempt=attempt,
                )
            except Exception:
                # Compensate the lease and state so a queue outage cannot strand a store.
                try:
                    _clear_policy_lease(policy)
                    for status_row in statuses:
                        status_row.status = "ERROR"
                        status_row.reason_code = "QUEUE_UNAVAILABLE"
                        status_row.next_sync_at = now + timedelta(seconds=JD_RETRY_BACKOFF_SECONDS[0])
                        status_row.retry_count = min(status_row.retry_count + 1, len(JD_RETRY_BACKOFF_SECONDS))
                    db.commit()
                finally:
                    raise
            scheduled += 1
        finally:
            db.close()
    return scheduled


def _claim_jd_workbench_task(task: dict, worker_id: str, now: datetime) -> str:
    db = SessionLocal()
    try:
        completed = db.query(JdSyncLog.id, JdSyncLog.claim_generation).filter(
            JdSyncLog.task_id == task["task_id"],
            JdSyncLog.attempt == int(task.get("attempt", 0)),
            JdSyncLog.status == "success",
        ).one_or_none()
    finally:
        db.close()
    if completed:
        task["db_claim_generation"] = completed[1]
        _clear_completed_jd_workbench_policy(task, now)
        return "completed"
    if task.get("task_type") != "sync_jd_smart" or task.get("payload", {}).get("source") != "cloud_scheduler":
        return "claimed"
    payload = task["payload"]
    db = SessionLocal()
    try:
        query = db.query(JdWorkbenchSyncPolicy).filter(
            JdWorkbenchSyncPolicy.tenant_id == int(payload["tenant_id"]),
            JdWorkbenchSyncPolicy.company_id == int(payload["company_id"]),
            JdWorkbenchSyncPolicy.store_id == int(payload["store_id"]),
        )
        policy = query.with_for_update(skip_locked=True).one_or_none()
        if policy is None:
            db.rollback()
            return "nack" if query.with_entities(JdWorkbenchSyncPolicy.id).one_or_none() else "discard"
        if policy.active_task_id != task["task_id"]:
            db.rollback()
            return "discard"
        latest = db.query(JdSyncLog).filter(
            JdSyncLog.task_id == policy.active_task_id,
        ).order_by(JdSyncLog.attempt.desc()).first()
        if latest and latest.status == "success":
            db.rollback()
            return "discard"
        expected_attempt = (
            latest.attempt
            if latest and latest.status == "running"
            else latest.attempt + 1
            if latest
            else 0
        )
        if int(task.get("attempt", 0)) != expected_attempt:
            db.rollback()
            return "discard"
        if policy.queue_state != "ready":
            db.rollback()
            return "nack"
        policy.queue_state = "processing"
        policy.lease_worker_id = worker_id
        policy.claim_generation += 1
        task["db_claim_generation"] = policy.claim_generation
        policy.lease_started_at = now
        policy.lease_heartbeat_at = now
        policy.visibility_deadline = now + timedelta(seconds=JD_TASK_VISIBILITY_SECONDS)
        for status in _status_rows(db, policy):
            status.status = "SYNCING"
            status.last_attempt_at = now
        db.commit()
        return "claimed"
    except (KeyError, TypeError, ValueError, IntegrityError):
        db.rollback()
        return "discard"
    finally:
        db.close()


def _clear_completed_jd_workbench_policy(task: dict, now: datetime) -> bool:
    """Converge a cloud policy after PostgreSQL proves the attempt completed."""
    if task.get("task_type") != "sync_jd_smart" or task.get("payload", {}).get("source") != "cloud_scheduler":
        return False
    payload = task["payload"]
    if task.get("db_claim_generation") is None:
        return False
    db = SessionLocal()
    try:
        policy = db.query(JdWorkbenchSyncPolicy).filter(
            JdWorkbenchSyncPolicy.tenant_id == int(payload["tenant_id"]),
            JdWorkbenchSyncPolicy.company_id == int(payload["company_id"]),
            JdWorkbenchSyncPolicy.store_id == int(payload["store_id"]),
            JdWorkbenchSyncPolicy.claim_generation == int(task["db_claim_generation"]),
        ).with_for_update().one_or_none()
        if policy is None:
            db.rollback()
            return False
        if policy.active_task_id is None and policy.queue_state is None:
            db.rollback()
            return True
        if policy.active_task_id != task["task_id"]:
            db.rollback()
            return False
        statuses = _status_rows(db, policy)
        _clear_policy_lease(policy)
        for status in statuses:
            status.status = "IDLE"
            status.reason_code = None
            status.last_sync_at = now
            status.retry_count = 0
            status.last_error_at = None
        db.commit()
        return True
    finally:
        db.close()


def _clear_failed_jd_workbench_policy(task: dict, now: datetime) -> bool:
    """Converge a failed cloud task after its terminal log commit."""
    if task.get("task_type") != "sync_jd_smart" or task.get("payload", {}).get("source") != "cloud_scheduler":
        return False
    payload = task["payload"]
    db = SessionLocal()
    try:
        policy = db.query(JdWorkbenchSyncPolicy).filter(
            JdWorkbenchSyncPolicy.tenant_id == int(payload["tenant_id"]),
            JdWorkbenchSyncPolicy.company_id == int(payload["company_id"]),
            JdWorkbenchSyncPolicy.store_id == int(payload["store_id"]),
            JdWorkbenchSyncPolicy.claim_generation == int(task.get("db_claim_generation", -1)),
        ).with_for_update().one_or_none()
        if policy is None:
            db.rollback()
            return False
        if policy.active_task_id is None and policy.queue_state is None:
            db.rollback()
            return True
        if policy.active_task_id != task["task_id"]:
            db.rollback()
            return False
        statuses = _status_rows(db, policy)
        _clear_policy_lease(policy)
        attempt = min(int(task.get("attempt", 0)) + 1, len(JD_RETRY_BACKOFF_SECONDS))
        for status in statuses:
            status.status = "ERROR"
            status.reason_code = "COLLECTOR_FAILED"
            status.retry_count = attempt
            status.last_error_at = now
            status.next_sync_at = now + timedelta(seconds=JD_RETRY_BACKOFF_SECONDS[attempt - 1])
        db.commit()
        return True
    finally:
        db.close()


def _finish_jd_workbench_task(task: dict, worker_id: str, *, success: bool, now: datetime) -> bool:
    if task.get("task_type") != "sync_jd_smart" or task.get("payload", {}).get("source") != "cloud_scheduler":
        return True
    payload = task["payload"]
    db = SessionLocal()
    redis = get_redis()
    try:
        policy = db.query(JdWorkbenchSyncPolicy).filter(
            JdWorkbenchSyncPolicy.tenant_id == int(payload["tenant_id"]),
            JdWorkbenchSyncPolicy.company_id == int(payload["company_id"]),
            JdWorkbenchSyncPolicy.store_id == int(payload["store_id"]),
            JdWorkbenchSyncPolicy.lease_worker_id == worker_id,
            JdWorkbenchSyncPolicy.claim_generation == int(task.get("db_claim_generation", -1)),
            JdWorkbenchSyncPolicy.queue_state == "processing",
        ).with_for_update().one_or_none()
        if policy is None or policy.active_task_id != task["task_id"]:
            db.rollback()
            return False
        statuses = _status_rows(db, policy)
        _clear_policy_lease(policy)
        if success:
            for status in statuses:
                status.status = "IDLE"
                status.reason_code = None
                status.last_sync_at = now
                status.retry_count = 0
                status.last_error_at = None
        else:
            attempt = min(int(task.get("attempt", 0)) + 1, len(JD_RETRY_BACKOFF_SECONDS))
            delay = JD_RETRY_BACKOFF_SECONDS[attempt - 1]
            for status in statuses:
                status.status = "ERROR"
                status.reason_code = "COLLECTOR_FAILED"
                status.retry_count = attempt
                status.last_error_at = now
                status.next_sync_at = now + timedelta(seconds=delay)
        db.commit()
        try:
            redis.delete(f"{JD_WORKBENCH_LEASE_PREFIX}{policy.tenant_id}:{policy.store_id}")
        except RedisError as exc:
            logger.warning("jd_workbench_lease_cleanup_pending task_id=%s error=%s", task["task_id"], type(exc).__name__)
        return True
    finally:
        db.close()


def _heartbeat_jd_workbench_task(task: dict, worker_id: str, now: datetime) -> bool:
    if task.get("task_type") != "sync_jd_smart" or task.get("payload", {}).get("source") != "cloud_scheduler":
        return True
    payload = task["payload"]
    db = SessionLocal()
    try:
        updated = db.query(JdWorkbenchSyncPolicy).filter(
            JdWorkbenchSyncPolicy.tenant_id == int(payload["tenant_id"]),
            JdWorkbenchSyncPolicy.company_id == int(payload["company_id"]),
            JdWorkbenchSyncPolicy.store_id == int(payload["store_id"]),
            JdWorkbenchSyncPolicy.active_task_id == task["task_id"],
            JdWorkbenchSyncPolicy.lease_worker_id == worker_id,
            JdWorkbenchSyncPolicy.claim_generation == int(task.get("db_claim_generation", -1)),
            JdWorkbenchSyncPolicy.queue_state == "processing",
        ).update({
            JdWorkbenchSyncPolicy.lease_heartbeat_at: now,
            JdWorkbenchSyncPolicy.visibility_deadline: now + timedelta(seconds=JD_TASK_VISIBILITY_SECONDS),
        }, synchronize_session=False)
        db.commit()
        return updated == 1
    finally:
        db.close()


def _assert_jd_workbench_claim_owned(db, task: dict, worker_id: str) -> None:
    """Fence the business commit with the authoritative PostgreSQL claim."""
    payload = task["payload"]
    owned = db.query(JdWorkbenchSyncPolicy.id).filter(
        JdWorkbenchSyncPolicy.tenant_id == int(payload["tenant_id"]),
        JdWorkbenchSyncPolicy.company_id == int(payload["company_id"]),
        JdWorkbenchSyncPolicy.store_id == int(payload["store_id"]),
        JdWorkbenchSyncPolicy.active_task_id == task["task_id"],
        JdWorkbenchSyncPolicy.lease_worker_id == worker_id,
        JdWorkbenchSyncPolicy.claim_generation == int(task.get("db_claim_generation", -1)),
        JdWorkbenchSyncPolicy.queue_state == "processing",
        JdWorkbenchSyncPolicy.visibility_deadline > datetime.now(timezone.utc),
    ).with_for_update().one_or_none()
    if owned is None:
        raise JdCollectorError("任务租约已失效")


def _recover_jd_workbench_task(task: dict, now: datetime) -> bool:
    if task.get("task_type") != "sync_jd_smart" or task.get("payload", {}).get("source") != "cloud_scheduler":
        db = SessionLocal()
        try:
            terminal = db.query(JdSyncLog.id).filter(
                JdSyncLog.task_id == task["task_id"],
                JdSyncLog.attempt == int(task.get("attempt", 0)),
                or_(
                    JdSyncLog.status == "success",
                    and_(
                        JdSyncLog.status == "failed",
                        JdSyncLog.attempt >= int(task.get("max_retries", 3)),
                    ),
                ),
            ).one_or_none()
            return False if terminal else None
        finally:
            db.close()
    payload = task["payload"]
    db = SessionLocal()
    try:
        policy = db.query(JdWorkbenchSyncPolicy).filter(
            JdWorkbenchSyncPolicy.tenant_id == int(payload["tenant_id"]),
            JdWorkbenchSyncPolicy.company_id == int(payload["company_id"]),
            JdWorkbenchSyncPolicy.store_id == int(payload["store_id"]),
        ).with_for_update().one_or_none()
        if policy is None or policy.active_task_id != task["task_id"]:
            db.rollback()
            return False
        if policy.queue_state == "ready":
            db.rollback()
            return True
        if (
            policy.queue_state != "processing"
            or policy.visibility_deadline is None
            or policy.visibility_deadline > now
        ):
            db.rollback()
            return False
        policy.queue_state = "ready"
        policy.lease_worker_id = None
        policy.lease_started_at = None
        policy.lease_heartbeat_at = None
        policy.visibility_deadline = None
        for status in _status_rows(db, policy):
            status.status = "IDLE"
            status.reason_code = None
            status.next_sync_at = now
        db.commit()
        return True
    finally:
        db.close()


def reap_jd_workbench_tasks(now=None) -> int:
    """Recover expired cloud claims from PostgreSQL, even after Redis loss."""
    now = now or datetime.now(timezone.utc)
    lookup = SessionLocal()
    try:
        policy_ids = [row[0] for row in lookup.query(JdWorkbenchSyncPolicy.id).filter(
            JdWorkbenchSyncPolicy.active_task_id.is_not(None),
            or_(
                JdWorkbenchSyncPolicy.queue_state == "ready",
                and_(
                    JdWorkbenchSyncPolicy.queue_state == "processing",
                    JdWorkbenchSyncPolicy.visibility_deadline.is_not(None),
                    JdWorkbenchSyncPolicy.visibility_deadline <= now,
                ),
            ),
        ).all()]
    finally:
        lookup.close()

    recovered = 0
    for policy_id in policy_ids:
        db = SessionLocal()
        task = None
        try:
            policy = db.query(JdWorkbenchSyncPolicy).filter(
                JdWorkbenchSyncPolicy.id == policy_id,
                JdWorkbenchSyncPolicy.active_task_id.is_not(None),
            ).with_for_update(skip_locked=True).one_or_none()
            if policy is None:
                continue
            expired = (
                policy.queue_state == "processing"
                and policy.visibility_deadline is not None
                and policy.visibility_deadline <= now
            )
            if policy.queue_state != "ready" and not expired:
                db.rollback()
                continue
            latest = db.query(JdSyncLog).filter(
                JdSyncLog.task_id == policy.active_task_id,
            ).order_by(JdSyncLog.attempt.desc()).first()
            if latest and latest.status == "success":
                _clear_policy_lease(policy)
                for status in _status_rows(db, policy):
                    status.status = "IDLE"
                    status.reason_code = None
                    status.last_sync_at = latest.finished_at or now
                    status.retry_count = 0
                    status.last_error_at = None
                db.commit()
                continue
            if latest and latest.status == "failed" and latest.attempt >= 5:
                statuses = _status_rows(db, policy)
                _clear_policy_lease(policy)
                attempt = min(latest.attempt + 1, len(JD_RETRY_BACKOFF_SECONDS))
                for status in statuses:
                    status.status = "ERROR"
                    status.reason_code = "COLLECTOR_FAILED"
                    status.retry_count = attempt
                    status.last_error_at = now
                    status.next_sync_at = now + timedelta(
                        seconds=JD_RETRY_BACKOFF_SECONDS[attempt - 1]
                    )
                db.commit()
                continue
            attempt = latest.attempt if latest and latest.status == "running" else (
                latest.attempt + 1 if latest else 0
            )
            if expired:
                policy.queue_state = "ready"
                policy.lease_worker_id = None
                policy.lease_started_at = None
                policy.lease_heartbeat_at = None
                policy.visibility_deadline = None
                for status in _status_rows(db, policy):
                    status.status = "IDLE"
                    status.reason_code = None
                    status.next_sync_at = now
            sync_window_started_at = policy.sync_window_started_at or _sync_window(
                now,
                policy.interval_seconds,
            )
            policy.sync_window_started_at = sync_window_started_at
            task = {
                "task_id": policy.active_task_id,
                "task_type": "sync_jd_smart",
                "payload": {
                    "tenant_id": policy.tenant_id,
                    "company_id": policy.company_id,
                    "store_id": policy.store_id,
                    "source": "cloud_scheduler",
                    "scheduled_at": now.isoformat(),
                    "sync_window_started_at": sync_window_started_at.isoformat(),
                },
                "attempt": attempt,
                "max_retries": 5,
                "claim_generation": policy.claim_generation,
            }
            db.commit()
        finally:
            db.close()
        if task is not None and ensure_task_delivery(task, now=now):
            recovered += 1
    non_cloud = reap_expired_tasks(
        now=now,
        before_requeue=lambda task: (
            False
            if task.get("task_type") == "sync_jd_smart"
            and task.get("payload", {}).get("source") == "cloud_scheduler"
            else _recover_jd_workbench_task(task, now)
        ),
    )
    return recovered + len(non_cloud)


def reconcile_completed_jd_workbench_tasks() -> int:
    """Remove Redis residue for task attempts already committed in PostgreSQL."""
    _reconcile_pending_task_statuses()
    redis = get_redis()
    reconciled = 0
    for raw in redis.lrange(PROCESSING_QUEUE_NAME, 0, -1):
        task = json.loads(raw)
        db = SessionLocal()
        try:
            terminal = db.query(JdSyncLog).filter(
                JdSyncLog.task_id == task["task_id"],
                JdSyncLog.attempt == int(task.get("attempt", 0)),
            ).one_or_none()
            status = terminal.status if terminal else None
            claim_generation = terminal.claim_generation if terminal else None
            notification_pending = terminal.redis_notification_pending if terminal else False
        finally:
            db.close()
        if not terminal:
            continue
        if notification_pending:
            continue
        fenced_task = {**task, "db_claim_generation": claim_generation}
        cloud = task.get("task_type") == "sync_jd_smart" and task.get("payload", {}).get("source") == "cloud_scheduler"
        if status == "success":
            if cloud and not _clear_completed_jd_workbench_policy(fenced_task, datetime.now(timezone.utc)):
                continue
        elif status == "failed" and cloud:
            if not _clear_failed_jd_workbench_policy(fenced_task, datetime.now(timezone.utc)):
                continue
        elif status != "failed" or int(task.get("attempt", 0)) < int(task.get("max_retries", 3)):
            continue
        if discard_processing_task(task, raw):
            reconciled += 1
    return reconciled


def _reconcile_pending_task_statuses() -> int:
    """Republish status notifications from PostgreSQL even after Redis state loss."""
    published = 0
    lookup = SessionLocal()
    try:
        pending_ids = [row[0] for row in lookup.query(JdSyncLog.id).filter(
            JdSyncLog.redis_notification_pending.is_(True),
            JdSyncLog.status.in_(("running", "success", "failed")),
        ).order_by(JdSyncLog.id).limit(100).all()]
    finally:
        lookup.close()
    for log_id in pending_ids:
        db = SessionLocal()
        try:
            if _publish_staged_task_status(db, log_id):
                published += 1
        finally:
            db.close()
    return published


def _stage_task_status(log: JdSyncLog, task: dict, status: str, message: str) -> None:
    log.redis_notification_pending = True
    log.redis_notification_payload = json.dumps({
        "task_id": task["task_id"],
        "status": status,
        "task_type": task["task_type"],
        "payload": task.get("payload", {}),
        "message": message,
        "attempt": int(task.get("attempt", 0)),
        "max_retries": int(task.get("max_retries", 3)),
    }, ensure_ascii=False, sort_keys=True)
    task["_redis_notification_pending"] = True


def _publish_staged_task_status(db, log_id: int, task: dict | None = None) -> bool:
    """Publish Redis status without allowing transport failure to rewrite DB truth."""
    log = db.query(JdSyncLog).filter(
        JdSyncLog.id == log_id,
        JdSyncLog.redis_notification_pending.is_(True),
    ).with_for_update(skip_locked=True).one_or_none()
    if log is None:
        if task is not None:
            task["_redis_notification_pending"] = False
            return True
        return False
    try:
        envelope = json.loads(log.redis_notification_payload or "")
        if not {"task_id", "status", "task_type"}.issubset(envelope):
            raise ValueError("missing required task status fields")
    except (TypeError, ValueError, json.JSONDecodeError):
        db.rollback()
        logger.error("task_status_notification_invalid log_id=%s", log_id)
        return False
    try:
        update_task_status(**envelope)
    except RedisError as exc:
        db.rollback()
        if task is not None:
            task["_redis_notification_pending"] = True
        logger.warning(
            "task_status_notification_pending task_id=%s status=%s error=%s",
            log.task_id, log.status, type(exc).__name__,
        )
        return False
    log.redis_notification_pending = False
    log.redis_notification_payload = None
    db.add(log)
    db.commit()
    if task is not None:
        task["_redis_notification_pending"] = False
    return True


def _publish_task_status_best_effort(db, log_id: int, task: dict) -> bool:
    """Keep transport/readback failures outside the business transaction outcome."""
    try:
        return _publish_staged_task_status(db, log_id, task)
    except Exception as exc:
        with contextlib.suppress(Exception):
            db.rollback()
        task["_redis_notification_pending"] = True
        logger.warning(
            "task_status_notification_pending log_id=%s error=%s",
            log_id, type(exc).__name__,
        )
        return False


class _TaskHeartbeat:
    def __init__(self, task: dict, worker_id: str):
        self.task = task
        self.worker_id = worker_id
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"queue-heartbeat-{task['task_id']}", daemon=True)

    def _run(self):
        while not self.stop.wait(JD_TASK_VISIBILITY_SECONDS / 3):
            if not _heartbeat_jd_workbench_task(self.task, self.worker_id, datetime.now(timezone.utc)):
                return
            if not heartbeat_task(self.task, self.worker_id, visibility_timeout=JD_TASK_VISIBILITY_SECONDS):
                return

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop.set()
        self.thread.join(timeout=1)


def update_worker_heartbeat():
    try:
        get_redis().setex(WORKER_HEARTBEAT_KEY, WORKER_HEARTBEAT_TTL_SECONDS, datetime.now(timezone.utc).isoformat())
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("worker_heartbeat_warning: %s: %s", type(exc).__name__, exc)


def run_daily_scheduler():
    if os.getenv("ENABLE_DAILY_BUSINESS_FLOW", "1") != "1":
        return
    today = date.today().isoformat()
    db = SessionLocal()
    try:
        sources = (
            db.query(TaskCenterTask)
            .filter(
                TaskCenterTask.source == DAILY_SCHEDULER_OWNERSHIP_SOURCE,
                TaskCenterTask.status == "completed",
            )
            .order_by(TaskCenterTask.id.asc())
            .all()
        )
        requester_ids = {source.requester_id for source in sources if source.requester_id is not None}
        users = {
            user.id: user
            for user in db.query(User).filter(User.id.in_(requester_ids), User.active.is_(True)).all()
        } if requester_ids else {}
        valid_sources: dict[str, TaskCenterTask] = {}
        invalid_scopes: set[str] = set()
        for source in sources:
            try:
                context = task_ownership_context(source)
            except ValueError:
                logger.warning("daily_business_flow_source_rejected: incomplete ownership")
                continue
            user = users.get(source.requester_id)
            if user is None:
                logger.warning("daily_business_flow_source_rejected: inactive or missing requester")
                invalid_scopes.add(context["ownership_scope_key"])
                continue
            scope = resolve_graph_ownership(db, user)
            expected = {
                "tenant_id": scope.tenant_id,
                "company_id": scope.company_id,
                "requester_id": scope.requester_id,
                "store_scope_key": scope.store_scope_key,
                "ownership_scope_key": scope.ownership_scope_key,
            }
            if any(context[field] != value for field, value in expected.items()):
                logger.warning("daily_business_flow_source_rejected: ownership mismatch")
                invalid_scopes.add(context["ownership_scope_key"])
                continue
            existing_source = valid_sources.get(scope.ownership_scope_key)
            if existing_source is not None and task_ownership_context(existing_source) != context:
                invalid_scopes.add(scope.ownership_scope_key)
                continue
            valid_sources.setdefault(scope.ownership_scope_key, source)

        for invalid_scope in invalid_scopes:
            valid_sources.pop(invalid_scope, None)
        if not valid_sources:
            logger.warning("daily_business_flow_skipped: no persisted ownership source")
            return

        redis_client = get_redis()
        for ownership_scope_key, source in sorted(valid_sources.items()):
            key = f"{DAILY_SCHEDULER_PREFIX}{today}:{ownership_scope_key}"
            try:
                acquired = redis_client.set(key, "pending", nx=True, ex=36 * 3600)
            except (RedisTimeoutError, RedisConnectionError):
                logger.warning("daily_business_flow_skipped: redis unavailable")
                return
            if not acquired:
                continue
            try:
                title = f"Sprint 17 daily business loop {today}"
                existing = (
                    db.query(TaskCenterTask)
                    .filter(
                        TaskCenterTask.source == "sprint17_ai_execution",
                        TaskCenterTask.title == title,
                        TaskCenterTask.ownership_scope_key == ownership_scope_key,
                    )
                    .order_by(TaskCenterTask.id.asc())
                    .all()
                )
                if existing:
                    redis_client.setex(key, 36 * 3600, "created")
                    continue

                first_employee = DEFAULT_COLLECTOR_EMPLOYEE
                flow_id = f"daily-business-{today}-{ownership_scope_key}"
                metadata = {
                    "sprint17": True,
                    "business_loop": True,
                    "scheduler": "daily",
                    "type": FLOW_TASK_TYPES[first_employee],
                    "input": {"source": "daily_scheduler", "date": today, "channels": ["ecommerce", "stock", "content"]},
                    "flow_id": flow_id,
                    "flow_steps": list(FLOW_EMPLOYEE_CODES),
                    "flow_index": 0,
                }
                task = TaskCenterTask(
                    title=title,
                    description=json.dumps({"input": metadata["input"]}, ensure_ascii=False),
                    status="assigned",
                    priority="normal",
                    source="sprint17_ai_execution",
                    parent_task_id=source.id,
                    assigned_ai_employee_code=first_employee,
                    assigned_ai_employee_name=employee_name(first_employee),
                    split_plan=json.dumps(metadata, ensure_ascii=False),
                )
                bind_task_ownership_from_task(task, parent=source)
                db.add(task)
                db.flush()
                enqueue_task(
                    SPRINT17_QUEUE_TYPE,
                    {
                        "task_center_id": task.id,
                        "assigned_to": first_employee,
                        "metadata": metadata,
                        "ownership": task_ownership_context(task),
                    },
                    max_retries=1,
                    delay_note="Sprint 17 daily business flow queued",
                )
                redis_client.setex(key, 36 * 3600, "created")
                db.commit()
                logger.info("daily_business_flow_created flow_id=%s task_id=%s", flow_id, task.id)
            except (RedisTimeoutError, RedisConnectionError, SQLAlchemyError):
                db.rollback()
                try:
                    redis_client.delete(key)
                except (RedisTimeoutError, RedisConnectionError):
                    logger.warning("daily_business_flow_lock_cleanup_failed")
                logger.warning("daily_business_flow_skipped: persistence unavailable")
                return
    finally:
        db.close()


def handle_task(task):
    result = handle_event(
        {
            "source": "worker",
            "target": "worker.task",
            "action": "process_worker_task",
            "payload": task,
            "force_sync": True,
        }
    )
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "任务执行被阻止")
    return result


def _handle_task_direct(task):
    task_id = task["task_id"]
    task_type = task["task_type"]
    payload = task.get("payload", {})
    attempt = int(task.get("attempt", 0))
    max_retries = int(task.get("max_retries", 3))
    cloud_scheduled = task_type == "sync_jd_smart" and payload.get("source") == "cloud_scheduler"
    db = SessionLocal()
    if task_type in {SPRINT17_QUEUE_TYPE, SPRINT18_QUEUE_TYPE}:
        center_id = int(payload["task_center_id"])
        if owned_task_from_context_or_none(db, task_id=center_id, ownership=payload.get("ownership")) is None:
            db.close()
            raise RuntimeError("task ownership is missing or inconsistent")
    log = db.query(JdSyncLog).filter(
        JdSyncLog.task_id == task_id,
        JdSyncLog.attempt == attempt,
    ).one_or_none()
    if log is None:
        store_id = payload.get("store_id")
        tenant_id = payload.get("tenant_id")
        company_id = payload.get("company_id")
        if store_id is not None and (tenant_id is None or company_id is None):
            store_scope = db.query(Store.tenant_id, Store.company_id).filter(Store.id == int(store_id)).one()
            tenant_id, company_id = store_scope
        sync_window = payload.get("sync_window_started_at")
        if isinstance(sync_window, str):
            sync_window = datetime.fromisoformat(sync_window.replace("Z", "+00:00"))
        if store_id is not None and sync_window is None:
            sync_window = _sync_window(datetime.now(timezone.utc), 300)
        log = JdSyncLog(
            tenant_id=tenant_id,
            company_id=company_id,
            store_id=store_id,
            sync_window_started_at=sync_window,
            claim_generation=task.get("db_claim_generation"),
            task_id=task_id,
            task_type=task_type,
            source=payload.get("source"),
            attempt=attempt,
        )
        db.add(log)
    if cloud_scheduled:
        # Fence the initial running-log write as well as the later business commit.
        try:
            _assert_jd_workbench_claim_owned(db, task, task["_worker_id"])
        except Exception:
            db.rollback()
            db.close()
            raise
    log.claim_generation = task.get("db_claim_generation")
    log.status = "running"
    log.started_at = datetime.now(timezone.utc)
    log.finished_at = None
    _stage_task_status(log, task, "running", "任务执行中")
    db.commit()
    _publish_task_status_best_effort(db, log.id, task)
    try:
        if task_type == "sync_jd_smart":
            cloud = payload.get("source") == "cloud_scheduler"
            def prepare_smart_commit():
                if cloud:
                    _assert_jd_workbench_claim_owned(db, task, task["_worker_id"])
                _stage_task_status(log, task, "success", "任务执行成功")

            result = sync_jd_smart(
                db,
                int(payload["store_id"]),
                completion_log=log,
                before_commit=prepare_smart_commit,
            )
        elif task_type == "sync_jzt":
            result = sync_jzt(db, int(payload["store_id"]))
        elif task_type == "sync_jd_orders":
            result = sync_jd_orders(db, int(payload["store_id"]))
        elif task_type == "sync_jd_products":
            result = sync_jd_products(db, int(payload["store_id"]))
        elif task_type == "ai_store_manager_daily":
            result = {"suggestions": analyze_store_health(db)}
            write_employee_log(db, task_type, "success", result, attempt, max_retries)
        elif task_type == SPRINT17_QUEUE_TYPE:
            result = execute_sprint17_task(db, task)
        elif task_type == SPRINT18_QUEUE_TYPE:
            result = execute_sprint18_business_loop(db, task)
        else:
            raise RuntimeError(f"未知任务类型: {task_type}")
        if task_type != "sync_jd_smart":
            log.status = "success"
            log.message = str(result)
            log.finished_at = datetime.now(timezone.utc)
            _stage_task_status(log, task, "success", "任务执行成功")
            db.commit()
        _publish_task_status_best_effort(db, log.id, task)
    except Exception as exc:
        db.rollback()
        if cloud_scheduled:
            # A stale worker must not overwrite the log owned by a newer claim.
            _assert_jd_workbench_claim_owned(db, task, task["_worker_id"])
        log.status = "failed"
        log.message = str(exc)
        log.finished_at = datetime.now(timezone.utc)
        terminal_failure = cloud_scheduled or attempt >= max_retries
        if terminal_failure:
            _stage_task_status(log, task, "failed", str(exc))
        else:
            log.redis_notification_pending = False
            log.redis_notification_payload = None
        db.add(log)
        if task_type == "ai_store_manager_daily":
            write_employee_log(db, task_type, "failed", {"error": str(exc)}, attempt, max_retries)
        db.commit()
        if terminal_failure:
            _publish_task_status_best_effort(db, log.id, task)
        raise
    finally:
        db.close()


def execute_sprint17_task(db, queued_task: dict) -> dict:
    payload = queued_task.get("payload", {})
    task_id = int(payload["task_center_id"])
    task = owned_task_from_context_or_none(db, task_id=task_id, ownership=payload.get("ownership"))
    if not task:
        raise RuntimeError(f"Sprint 17 task not found: {task_id}")

    metadata = parse_json(task.split_plan)
    task_input = metadata.get("input")
    assigned_to = normalize_employee_code(task.assigned_ai_employee_code or payload.get("assigned_to")) or "unassigned"
    task.status = "running"
    db.commit()

    result = handle_event(
        {
            "source": "worker",
            "target": assigned_to,
            "action": "execute_employee_skill",
            "force_sync": True,
            "payload": {
                "task_id": task.id,
                "task_type": metadata.get("type") or "mock_task",
                "task_input": task_input,
            },
        }
    )["result"]
    db.add(
        TaskCenterResult(
            task_id=task.id,
            ai_employee_code=assigned_to,
            ai_employee_name=task.assigned_ai_employee_name or employee_name(assigned_to) or assigned_to,
            result_content=json.dumps(result, ensure_ascii=False),
            attachments_json=json.dumps([], ensure_ascii=False),
        )
    )
    task.status = "completed"
    db.commit()
    create_next_flow_task_if_needed(db, task, metadata, result)
    return result


def execute_sprint18_business_loop(db, queued_task: dict) -> dict:
    payload = queued_task.get("payload", {})
    task_id = int(payload["task_center_id"])
    task = owned_task_from_context_or_none(db, task_id=task_id, ownership=payload.get("ownership"))
    if not task:
        raise RuntimeError(f"Sprint 18 task not found: {task_id}")

    metadata = parse_json(task.split_plan)
    task_input = metadata.get("input") if isinstance(metadata.get("input"), dict) else {}
    event_type = metadata.get("event_type") or "unknown"
    loop_iteration = int(metadata.get("loop_iteration") or 0)

    task.status = "running"
    db.commit()

    result = build_sprint18_business_result(task.id, event_type, task_input, loop_iteration)
    db.add(
        TaskCenterResult(
            task_id=task.id,
            ai_employee_code=normalize_employee_code(task.assigned_ai_employee_code) or DEFAULT_STRATEGY_EMPLOYEE,
            ai_employee_name=task.assigned_ai_employee_name or employee_name(DEFAULT_STRATEGY_EMPLOYEE),
            result_content=json.dumps(result, ensure_ascii=False),
            attachments_json=json.dumps([], ensure_ascii=False),
        )
    )
    task.status = "completed"
    db.commit()

    create_sprint18_feedback_task_if_needed(db, task, metadata, result)
    return result


def build_sprint18_business_result(task_id: int, event_type: str, task_input: dict, loop_iteration: int) -> dict:
    analysis = analyze_sprint18_business_event(event_type, task_input)
    decision = decide_sprint18_business_actions(event_type, analysis)
    execution = mock_execute_sprint18_decision(decision)
    return {
        "task_id": task_id,
        "event_type": event_type,
        "input": task_input,
        "analysis": analysis,
        "decision": decision,
        "execution": execution,
        "feedback_loop": {
            "reusable_as_input": True,
            "loop_iteration": loop_iteration,
            "next_input": {
                "source_task_id": task_id,
                "source_event_type": event_type,
                "decision": decision,
                "execution": execution,
            },
            "next_research_focus": decision.get("optimization_focus"),
        },
        "mode": "sprint18_business_mock",
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }


def analyze_sprint18_business_event(event_type: str, task_input: dict) -> dict:
    if event_type == "ecommerce_order":
        quantity = safe_number(task_input.get("quantity"), default=1)
        amount = safe_number(task_input.get("amount"), default=0)
        unit_price = round(amount / quantity, 2) if quantity else amount
        return {
            "summary": "电商订单触发：识别成交商品、客单价和复购线索。",
            "signal_type": "order_conversion",
            "product": {
                "sku": task_input.get("sku") or "unknown",
                "name": task_input.get("product_name") or task_input.get("sku") or "unknown",
                "quantity": quantity,
                "amount": amount,
                "unit_price": unit_price,
            },
            "customer_tags": task_input.get("customer_tags") or [],
            "confidence": "medium",
        }
    if event_type == "content_metrics":
        views = safe_number(task_input.get("views"))
        likes = safe_number(task_input.get("likes"))
        comments = safe_number(task_input.get("comments"))
        shares = safe_number(task_input.get("shares"))
        engagement = likes + comments + shares
        engagement_rate = round(engagement / views, 4) if views else 0
        return {
            "summary": "内容数据触发：识别互动率、传播潜力和内容复用价值。",
            "signal_type": "content_performance",
            "content": {
                "content_id": task_input.get("content_id") or "unknown",
                "title": task_input.get("title") or "未命名内容",
                "views": views,
                "engagement": engagement,
                "engagement_rate": engagement_rate,
            },
            "confidence": "medium",
        }
    if event_type == "file_upload":
        rows = task_input.get("rows") if isinstance(task_input.get("rows"), list) else []
        return {
            "summary": "文件上传触发：提取结构化行数、文件类型和人工摘要。",
            "signal_type": "uploaded_dataset",
            "file": {
                "filename": task_input.get("filename") or "unknown",
                "file_type": task_input.get("file_type") or "unknown",
                "row_count": len(rows),
                "content_summary": task_input.get("content_summary") or "暂无摘要",
            },
            "confidence": "low" if not rows else "medium",
        }
    if event_type == "feedback_replay":
        return {
            "summary": "反馈循环触发：基于历史结果和新增反馈重新生成优化建议。",
            "signal_type": "feedback_loop",
            "previous_result": task_input.get("previous_result"),
            "feedback": task_input.get("feedback"),
            "confidence": "medium",
        }
    return {
        "summary": "通用业务事件触发：进入保守策略分析。",
        "signal_type": "generic_business_event",
        "payload": task_input,
        "confidence": "low",
    }


def decide_sprint18_business_actions(event_type: str, analysis: dict) -> dict:
    if event_type == "ecommerce_order":
        product = analysis.get("product") or {}
        unit_price = safe_number(product.get("unit_price"))
        return {
            "selected_product": product.get("sku"),
            "pricing_strategy": {
                "suggested_price": round(unit_price * 1.08, 2) if unit_price else 0,
                "reason": "基于当前成交价做 8% 价格弹性测试，需人工确认后执行。",
            },
            "content_strategy": "围绕已成交商品生成复购和使用场景内容。",
            "ad_strategy": "建议建立人工审核的低预算复购测试计划，不自动投放。",
            "optimization_focus": "复购转化",
            "requires_human_approval": True,
        }
    if event_type == "content_metrics":
        content = analysis.get("content") or {}
        rate = safe_number(content.get("engagement_rate"))
        return {
            "selected_product": "由人工从相关商品池选择",
            "pricing_strategy": {"suggested_price": None, "reason": "内容数据不直接改价。"},
            "content_strategy": "复用高互动主题，生成短视频脚本和商品详情页角度。",
            "ad_strategy": "互动率达到阈值后建议人工创建投放实验。",
            "optimization_focus": "内容转化" if rate >= 0.03 else "内容钩子优化",
            "requires_human_approval": True,
        }
    if event_type == "file_upload":
        file_info = analysis.get("file") or {}
        return {
            "selected_product": "从上传文件中人工确认候选商品",
            "pricing_strategy": {"suggested_price": None, "reason": "上传文件仅用于研究，不自动改价。"},
            "content_strategy": f"基于 {file_info.get('filename')} 生成数据洞察摘要。",
            "ad_strategy": "仅输出投放研究建议，不修改预算。",
            "optimization_focus": "数据清洗与候选机会识别",
            "requires_human_approval": True,
        }
    if event_type == "feedback_replay":
        return {
            "selected_product": "沿用上一轮业务对象",
            "pricing_strategy": {"suggested_price": None, "reason": "反馈循环只生成二次优化建议。"},
            "content_strategy": "根据反馈收敛内容卖点和执行顺序。",
            "ad_strategy": "根据反馈调整人工审核的实验方案。",
            "optimization_focus": "反馈闭环优化",
            "requires_human_approval": True,
        }
    return {
        "selected_product": None,
        "pricing_strategy": {"suggested_price": None, "reason": "未知事件不自动定价。"},
        "content_strategy": "先进入人工研究。",
        "ad_strategy": "不自动投放。",
        "optimization_focus": "风险识别",
        "requires_human_approval": True,
    }


def mock_execute_sprint18_decision(decision: dict) -> dict:
    return {
        "status": "mock_executed",
        "writes_database": True,
        "external_actions": [],
        "task_status_updated": True,
        "records": [
            {
                "action": "write_strategy_result",
                "status": "completed",
                "detail": "策略结果已写入 TaskCenterResult。",
            },
            {
                "action": "manual_review_required",
                "status": "pending_human",
                "detail": "定价、投放、发布、付款均需人工确认。",
            },
        ],
        "safety_boundary": [
            "不调用外部 API",
            "不自动付款",
            "不自动投放广告",
            "不自动发布内容",
            "不修改权限",
        ],
        "decision_snapshot": decision,
    }


def create_sprint18_feedback_task_if_needed(db, task: TaskCenterTask, metadata: dict, previous_result: dict) -> None:
    if not metadata.get("auto_optimize"):
        return
    loop_iteration = int(metadata.get("loop_iteration") or 0)
    if loop_iteration >= 1:
        return

    next_metadata = {
        "sprint18": True,
        "event_type": "feedback_replay",
        "input": {
            "previous_result": previous_result,
            "feedback": {"source": "auto_optimize", "note": "一次性闭环优化任务"},
        },
        "loop_id": metadata.get("loop_id"),
        "loop_iteration": loop_iteration + 1,
        "auto_optimize": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    next_task = TaskCenterTask(
        title="Sprint 18 business loop: feedback_replay",
        description=json.dumps({"input": next_metadata["input"]}, ensure_ascii=False),
        status="assigned",
        priority="normal",
        source="sprint18_business_loop",
        parent_task_id=task.id,
        assigned_ai_employee_code=DEFAULT_STRATEGY_EMPLOYEE,
        assigned_ai_employee_name=employee_name(DEFAULT_STRATEGY_EMPLOYEE),
        split_plan=json.dumps(next_metadata, ensure_ascii=False),
    )
    bind_task_ownership_from_task(next_task, parent=task)
    db.add(next_task)
    db.commit()
    db.refresh(next_task)
    enqueue_task(
        SPRINT18_QUEUE_TYPE,
        {
            "task_center_id": next_task.id,
            "metadata": next_metadata,
            "ownership": task_ownership_context(next_task),
        },
        max_retries=1,
        delay_note="Sprint 18 feedback loop queued",
    )


def safe_number(value, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def create_next_flow_task_if_needed(db, task: TaskCenterTask, metadata: dict, previous_result: dict) -> None:
    steps = metadata.get("flow_steps") or []
    index = metadata.get("flow_index")
    if not steps or index is None or int(index) >= len(steps) - 1:
        return

    next_index = int(index) + 1
    next_employee = normalize_employee_code(steps[next_index]) or steps[next_index]
    next_type = FLOW_TASK_TYPES.get(next_employee, "mock_task")
    next_metadata = {
        "sprint17": True,
        "type": next_type,
        "input": previous_result,
        "flow_id": metadata.get("flow_id"),
        "flow_steps": steps,
        "flow_index": next_index,
        "business_loop": metadata.get("business_loop", False),
    }
    next_task = TaskCenterTask(
        title=f"Sprint 17 flow {metadata.get('flow_id')} step {next_index + 1}/{len(steps)}",
        description=json.dumps({"input": previous_result}, ensure_ascii=False),
        status="assigned",
        priority="normal",
        source="sprint17_ai_execution",
        parent_task_id=task.id,
        assigned_ai_employee_code=next_employee,
        assigned_ai_employee_name=employee_name(next_employee) or next_employee,
        split_plan=json.dumps(next_metadata, ensure_ascii=False),
    )
    bind_task_ownership_from_task(next_task, parent=task)
    db.add(next_task)
    db.commit()
    db.refresh(next_task)
    enqueue_task(
        SPRINT17_QUEUE_TYPE,
        {
            "task_center_id": next_task.id,
            "assigned_to": next_employee,
            "metadata": next_metadata,
            "ownership": task_ownership_context(next_task),
        },
        max_retries=1,
        delay_note="Sprint 17 flow next step queued",
    )


def parse_json(value: str | None) -> dict:
    try:
        data = json.loads(value or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


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
    require_service_role("worker")
    last_jd_schedule = 0.0
    while True:
        update_worker_heartbeat()
        if time.monotonic() - last_jd_schedule >= JD_SCHEDULER_POLL_SECONDS:
            reconcile_completed_jd_workbench_tasks()
            reap_jd_workbench_tasks()
            run_jd_workbench_scheduler()
            last_jd_schedule = time.monotonic()
        run_daily_scheduler()
        if not process_next_tian_shang_worker_execution() and not process_next_employee_execution() and not process_next_brain_runtime_execution():
            process_next_task()
        time.sleep(0.1)


def process_next_tian_shang_worker_execution():
    db = SessionLocal()
    try:
        return process_next_tian_shang_execution(db, timeout=1)
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("tian_shang_queue_warning: %s: %s", type(exc).__name__, exc)
        return False
    except Exception as exc:
        logger.exception("tian_shang_execution_failed: %s", exc)
        return False
    finally:
        db.close()


def process_next_employee_execution():
    db = SessionLocal()
    try:
        return process_next_execution_task(db, timeout=1, worker_id="employee_worker")
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("execution_queue_warning: %s: %s", type(exc).__name__, exc)
        return False
    except Exception as exc:
        logger.exception("employee_execution_failed: %s", exc)
        return False
    finally:
        db.close()


def process_next_brain_runtime_execution():
    db = SessionLocal()
    try:
        result = process_next_brain_execution(db, timeout=1, worker_id=f"brain-{_worker_id()}")
        return bool(result.get("processed"))
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("brain_execution_queue_warning: %s: %s", type(exc).__name__, exc)
        return False
    except Exception as exc:
        logger.exception("brain_execution_failed: %s", exc)
        return False
    finally:
        db.close()


def process_next_task():
    worker_id = _worker_id()
    try:
        task = claim_task(worker_id=worker_id, timeout=5, visibility_timeout=JD_TASK_VISIBILITY_SECONDS)
    except (RedisTimeoutError, RedisConnectionError) as exc:
        logger.warning("redis_queue_warning: %s: %s", type(exc).__name__, exc)
        time.sleep(2)
        return False
    if not task:
        return False
    raw = task.pop("_processing_raw")
    claim_result = _claim_jd_workbench_task(task, worker_id, datetime.now(timezone.utc))
    if claim_result == "nack":
        nack_task(task, worker_id, raw)
        return True
    if claim_result in {"completed", "discard"}:
        ack_task(task, worker_id, raw)
        return True
    success = False
    task_error = None
    task["_worker_id"] = worker_id
    logger.info("worker_task_claimed task_id=%s worker_id=%s", task["task_id"], worker_id)
    try:
        with _TaskHeartbeat(task, worker_id):
            handle_task(task)
        success = True
    except JdCollectorError as exc:
        task_error = exc
        logger.warning("collector_task_incomplete: %s", exc)
    except Exception as exc:
        task_error = exc
        logger.exception("worker_task_failed: %s", exc)
    finally:
        cloud = task.get("task_type") == "sync_jd_smart" and task.get("payload", {}).get("source") == "cloud_scheduler"
        if not success and not cloud and int(task.get("attempt", 0)) < int(task.get("max_retries", 3)):
            retry_claimed_task(task, worker_id, raw, f"执行失败，准备重试: {task_error}")
        else:
            finished = _finish_jd_workbench_task(task, worker_id, success=success, now=datetime.now(timezone.utc))
            if finished and not task.get("_redis_notification_pending"):
                try:
                    ack_task(task, worker_id, raw)
                except RedisError as exc:
                    logger.warning("task_ack_pending task_id=%s error=%s", task["task_id"], type(exc).__name__)
    return True


if __name__ == "__main__":
    main()
