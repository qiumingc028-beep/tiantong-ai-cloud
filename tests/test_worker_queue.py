from backend.models import EmployeeLog, JdSyncLog
from backend.queue import QUEUE_NAME, enqueue_task, get_queue_status
from backend.worker import SUPPORTED_TASK_TYPES, handle_task


def test_queue_uses_tiantong_tasks_and_keeps_retry_metadata(client, owner_headers):
    task = enqueue_task("sync_jd_smart", {"store_id": 1})
    status = get_queue_status()

    assert status["name"] == QUEUE_NAME
    assert status["pending"] == 1
    assert task["max_retries"] == 3
    assert status["recent"][0]["task_type"] == "sync_jd_smart"
    assert status["recent"][0]["max_retries"] == 3

    response = client.get("/api/jd/sync/status", headers=owner_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["queue"]["name"] == QUEUE_NAME
    assert data["queue"]["pending"] == 1
    assert data["queue"]["recent"][0]["max_retries"] == 3


def test_worker_task_type_whitelist_is_complete():
    assert SUPPORTED_TASK_TYPES == {
        "sync_jd_smart",
        "sync_jzt",
        "sync_jd_orders",
        "sync_jd_products",
        "ai_store_manager_daily",
        "sprint17_ai_task",
        "sprint18_business_loop",
    }


def test_worker_writes_jd_and_employee_logs_for_ai_manager_task(monkeypatch, test_db):
    monkeypatch.setattr("backend.worker.SessionLocal", test_db)
    task = {
        "task_id": "ai-worker-1",
        "task_type": "ai_store_manager_daily",
        "payload": {},
        "attempt": 0,
        "max_retries": 3,
    }

    handle_task(task)

    db = test_db()
    try:
        jd_log = db.query(JdSyncLog).filter(JdSyncLog.task_id == "ai-worker-1").one()
        employee_log = db.query(EmployeeLog).filter(EmployeeLog.action == "ai_store_manager_daily").one()

        assert jd_log.status == "success"
        assert jd_log.finished_at is not None
        assert "success" in employee_log.detail
        assert "last_executed_at" in employee_log.detail
    finally:
        db.close()


def test_worker_records_failure_reason_and_requeues(monkeypatch, test_db):
    from backend import worker

    def fail_sync(db, store_id, **_kwargs):
        raise RuntimeError("collector unavailable")

    monkeypatch.setattr("backend.worker.SessionLocal", test_db)
    monkeypatch.setattr("backend.worker.sync_jd_smart", fail_sync)
    enqueue_task("sync_jd_smart", {"store_id": 1}, task_id="jd-worker-1")

    assert worker.process_next_task() is True

    status = get_queue_status()
    db = test_db()
    try:
        jd_log = db.query(JdSyncLog).filter(JdSyncLog.task_id == "jd-worker-1").one()

        assert jd_log.status == "failed"
        assert jd_log.message == "collector unavailable"
        assert jd_log.attempt == 0
        assert jd_log.finished_at is not None
        assert status["pending"] == 1
        assert status["recent"][0]["status"] == "retrying"
        assert status["recent"][0]["retry_count"] == 1
        assert status["recent"][0]["max_retries"] == 3
    finally:
        db.close()


def test_successful_database_terminal_state_survives_redis_status_failure(monkeypatch, test_db):
    from backend import worker
    from redis.exceptions import ConnectionError as RedisConnectionError

    monkeypatch.setattr(worker, "SessionLocal", test_db)
    monkeypatch.setattr(worker, "analyze_store_health", lambda _db: [])

    def publish(task_id, status, *_args, **_kwargs):
        if status == "success":
            raise RedisConnectionError("expected status transport outage")

    monkeypatch.setattr(worker, "update_task_status", publish)
    task = {
        "task_id": "ai-worker-redis-outage",
        "task_type": "ai_store_manager_daily",
        "payload": {},
        "attempt": 0,
        "max_retries": 3,
    }

    worker._handle_task_direct(task)

    db = test_db()
    try:
        log = db.query(JdSyncLog).filter(JdSyncLog.task_id == task["task_id"]).one()
        assert log.status == "success"
        assert log.redis_notification_pending is True
    finally:
        db.close()


def test_status_notification_failure_never_escapes_when_rollback_also_fails(monkeypatch):
    from backend import worker

    class BrokenNotificationSession:
        def rollback(self):
            raise RuntimeError("notification connection lost")

    monkeypatch.setattr(
        worker,
        "_publish_staged_task_status",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("notification commit failed")),
    )
    task = {}

    assert worker._publish_task_status_best_effort(BrokenNotificationSession(), 1, task) is False
    assert task["_redis_notification_pending"] is True
