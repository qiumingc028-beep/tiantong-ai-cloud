from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.models import (
    Company,
    JdSyncLog,
    JdWorkbenchDevice,
    JdWorkbenchStoreStatus,
    JdWorkbenchSyncPolicy,
    Store,
    Tenant,
    User,
)
from backend.services.jd_collectors import JdCollectorError


class SchedulerRedis:
    def __init__(self):
        self.lock = threading.Lock()
        self.values = {}
        self.lists = {}

    def set(self, key, value, nx=False, ex=None):
        with self.lock:
            if nx and key in self.values:
                return False
            self.values[key] = value
            return True

    def delete(self, key):
        with self.lock:
            self.values.pop(key, None)

    def rpush(self, key, value):
        with self.lock:
            self.lists.setdefault(key, []).append(value)

    def setex(self, key, _ttl, value):
        with self.lock:
            self.values[key] = value

    def lpush(self, key, value):
        with self.lock:
            self.lists.setdefault(key, []).insert(0, value)

    def ltrim(self, key, start, end):
        with self.lock:
            self.lists[key] = self.lists.get(key, [])[start : end + 1]


def test_task_attempt_has_persistent_database_idempotency_key(postgres_database_factory):
    from tests.conftest import _alembic

    database_url = postgres_database_factory("r297_task_idempotency")
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    task_id = str(uuid.uuid4())
    db = sessions()
    try:
        db.add(JdSyncLog(task_id=task_id, task_type="sync_jd_smart", attempt=0, status="success"))
        db.commit()
        db.add(JdSyncLog(task_id=task_id, task_type="sync_jd_smart", attempt=0, status="running"))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("duplicate task_id/attempt must be rejected")
        assert db.query(JdSyncLog).filter(JdSyncLog.task_id == task_id, JdSyncLog.attempt == 0).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_migration_rejects_historical_duplicate_task_attempts(postgres_database_factory):
    from tests.conftest import _alembic

    database_url = postgres_database_factory("r297_duplicate_preflight")
    _alembic(database_url, "upgrade", "0050_r297_reliable_sync_queue")
    engine = create_engine(database_url)
    task_id = str(uuid.uuid4())
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO jd_sync_logs (task_id, task_type, status, attempt) VALUES (%s, %s, %s, 0), (%s, %s, %s, 0)",
                (task_id, "sync_jd_smart", "failed", task_id, "sync_jd_smart", "failed"),
            )
        with pytest.raises(subprocess.CalledProcessError) as failure:
            _alembic(database_url, "upgrade", "0051_r297_queue_fencing_and_idempotency")
        assert "R297_DUPLICATE_TASK_ATTEMPT" in (failure.value.stdout + failure.value.stderr)
    finally:
        engine.dispose()


def test_non_cloud_successful_task_replay_is_ack_only(postgres_database_factory, monkeypatch):
    from backend import worker
    from tests.conftest import _alembic

    database_url = postgres_database_factory("r297_non_cloud_replay")
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    task_id = str(uuid.uuid4())
    db = sessions()
    try:
        db.add(JdSyncLog(task_id=task_id, task_type="ai_store_manager_daily", attempt=0, status="success"))
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(worker, "SessionLocal", sessions)
    task = {
        "task_id": task_id,
        "task_type": "ai_store_manager_daily",
        "payload": {"date": "2026-09-03"},
        "attempt": 0,
        "claim_generation": 1,
    }
    try:
        assert worker._claim_jd_workbench_task(task, "worker-replay", datetime.now(timezone.utc)) == "completed"
    finally:
        engine.dispose()


def test_pending_status_reconciler_uses_postgresql_skip_locked(postgres_database_factory, monkeypatch):
    from backend import worker
    from tests.conftest import _alembic

    database_url = postgres_database_factory("r297_pending_status_lock")
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    task_id = str(uuid.uuid4())
    db = sessions()
    try:
        db.add(JdSyncLog(
            task_id=task_id, task_type="ai_store_manager_daily", attempt=0,
            status="success", redis_notification_pending=True,
            redis_notification_payload=json.dumps({
                "task_id": task_id, "status": "success",
                "task_type": "ai_store_manager_daily",
            }),
        ))
        db.commit()
        db.connection().exec_driver_sql(
            "SELECT id FROM jd_sync_logs WHERE task_id = %s FOR UPDATE",
            (task_id,),
        ).one()
        monkeypatch.setattr(worker, "SessionLocal", sessions)
        monkeypatch.setattr(worker, "update_task_status", lambda *_args, **_kwargs: None)

        assert worker._reconcile_pending_task_statuses() == 0
        db.rollback()
        assert worker._reconcile_pending_task_statuses() == 1
    finally:
        db.close()
        engine.dispose()


def test_0052_downgrade_reupgrade_preserves_queue_identity(postgres_database_factory):
    from tests.conftest import _alembic

    database_url = postgres_database_factory("r297_0052_roundtrip")
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    window = datetime.now(timezone.utc).replace(microsecond=0)
    task_id = str(uuid.uuid4())
    with engine.begin() as connection:
        tenant_id = connection.exec_driver_sql(
            "INSERT INTO tenants (tenant_code, tenant_name, active) VALUES ('R297-RT', 'R297 roundtrip', true) RETURNING id"
        ).scalar_one()
        company_id = connection.exec_driver_sql(
            "INSERT INTO companies (tenant_id, company_code, company_name, active) VALUES (%s, 'R297-RT', 'R297 roundtrip', true) RETURNING id",
            (tenant_id,),
        ).scalar_one()
        store_id = connection.exec_driver_sql(
            "INSERT INTO stores (tenant_id, company_id, platform, store_code, store_name, active) VALUES (%s, %s, 'jd', 'R297-RT', 'R297 roundtrip', true) RETURNING id",
            (tenant_id, company_id),
        ).scalar_one()
        connection.exec_driver_sql(
            "INSERT INTO jd_sync_logs (tenant_id, company_id, store_id, task_id, task_type, source, status, attempt, claim_generation, redis_notification_pending, redis_notification_payload, sync_window_started_at) VALUES (%s, %s, %s, %s, 'sync_jd_smart', 'cloud_scheduler', 'success', 0, 7, true, %s, %s)",
            (tenant_id, company_id, store_id, task_id, '{"status":"success"}', window),
        )
    engine.dispose()

    _alembic(database_url, "downgrade", "0051_r297_queue_fencing_and_idempotency")
    legacy_task_id = str(uuid.uuid4())
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO jd_sync_logs (store_id, task_id, task_type, status, attempt) VALUES (%s, %s, 'sync_jd_smart', 'failed', 0)",
            (store_id, legacy_task_id),
        )
    engine.dispose()
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT source, claim_generation, redis_notification_pending, redis_notification_payload, sync_window_started_at FROM jd_sync_logs WHERE task_id = %s",
                (task_id,),
            ).one()
        assert row[0] == "cloud_scheduler"
        assert row[1] == 7
        assert row[2] is True
        assert row[3] == '{"status":"success"}'
        assert row[4] == window
        with engine.connect() as connection:
            legacy = connection.exec_driver_sql(
                "SELECT tenant_id, company_id, source, sync_window_started_at FROM jd_sync_logs WHERE task_id = %s",
                (legacy_task_id,),
            ).one()
        assert legacy[0:3] == (tenant_id, company_id, "legacy")
        assert legacy[3] is not None
    finally:
        engine.dispose()


def test_store_window_task_type_is_a_persistent_business_idempotency_key(postgres_database_factory):
    from tests.conftest import _alembic

    database_url = postgres_database_factory("r297_business_idempotency")
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = sessions()
    try:
        tenant = Tenant(tenant_code="R297-I", tenant_name="R297 idempotency")
        db.add(tenant)
        db.flush()
        company = Company(tenant_id=tenant.id, company_code="R297-I", company_name="R297 idempotency")
        db.add(company)
        db.flush()
        store = Store(
            tenant_id=tenant.id,
            company_id=company.id,
            platform="jd",
            store_code="R297-I",
            store_name="R297 idempotency",
            active=True,
        )
        db.add(store)
        db.flush()
        window = datetime.now(timezone.utc).replace(microsecond=0)
        values = {
            "tenant_id": tenant.id,
            "company_id": company.id,
            "store_id": store.id,
            "sync_window_started_at": window,
            "task_type": "sync_jd_smart",
            "source": "cloud_scheduler",
            "attempt": 0,
            "status": "success",
        }
        task_id = str(uuid.uuid4())
        db.add(JdSyncLog(task_id=task_id, **values))
        db.commit()
        db.add(JdSyncLog(task_id=str(uuid.uuid4()), **values))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        retry_values = dict(values, attempt=1, status="running")
        db.add(JdSyncLog(task_id=task_id, **retry_values))
        db.commit()
        other_company = Company(
            tenant_id=tenant.id,
            company_code="R297-OTHER",
            company_name="R297 other company",
        )
        db.add(other_company)
        db.commit()
        db.add(JdSyncLog(
            task_id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            company_id=other_company.id,
            store_id=store.id,
            sync_window_started_at=window + timedelta(minutes=5),
            task_type="sync_jd_smart",
            attempt=0,
            status="success",
        ))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    finally:
        db.close()
        engine.dispose()


def test_two_schedulers_create_one_store_window_task(postgres_database_factory, monkeypatch):
    from backend import queue, worker
    from tests.conftest import _alembic

    database_url = postgres_database_factory("r297_queue_claim")
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = sessions()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        tenant = Tenant(tenant_code="R297-Q", tenant_name="R297 queue")
        db.add(tenant)
        db.flush()
        company = Company(tenant_id=tenant.id, company_code="R297-Q", company_name="R297 queue")
        db.add(company)
        db.flush()
        user = User(
            username="r297-queue-owner",
            password_hash="not-a-real-secret",
            role="owner",
            display_name="R297 queue owner",
            tenant_id=tenant.id,
            company_id=company.id,
            active=True,
        )
        db.add(user)
        db.flush()
        store = Store(
            tenant_id=tenant.id,
            company_id=company.id,
            platform="jd",
            store_code="R297-Q",
            store_name="R297 queue",
            active=True,
        )
        db.add(store)
        db.flush()
        device = JdWorkbenchDevice(
            device_id="00000000-0000-4000-8000-000000000297",
            token_hash="a" * 64,
            public_key_n="a" * 256,
            public_key_e=65537,
            tenant_id=tenant.id,
            company_id=company.id,
            user_id=user.id,
            device_name="queue-test",
            client_version="2.97.0",
            status="ONLINE",
            expires_at=now + timedelta(days=1),
        )
        db.add(device)
        db.flush()
        db.add_all([
            JdWorkbenchStoreStatus(
                device_id=device.device_id,
                store_id=store.id,
                status="IDLE",
                next_sync_at=now,
            ),
            JdWorkbenchSyncPolicy(
                tenant_id=tenant.id,
                company_id=company.id,
                store_id=store.id,
                enabled=True,
                interval_seconds=300,
            ),
        ])
        db.commit()
    finally:
        db.close()

    redis = SchedulerRedis()
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    monkeypatch.setattr(worker, "get_redis", lambda: redis)
    monkeypatch.setattr(queue, "get_redis", lambda: redis)
    barrier = threading.Barrier(3)
    results = []

    def schedule():
        barrier.wait()
        results.append(worker.run_jd_workbench_scheduler(now))

    threads = [threading.Thread(target=schedule) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(results) == [0, 1]
    assert len(redis.lists[queue.QUEUE_NAME]) == 1
    db = sessions()
    try:
        policy = db.query(JdWorkbenchSyncPolicy).one()
        assert policy.queue_state == "ready"
        assert policy.active_task_id
        assert policy.sync_window_started_at == worker._sync_window(now, 300)
        task = json.loads(redis.lists[queue.QUEUE_NAME][0])
        task["claim_generation"] = 1
        policy.queue_state = "processing"
        policy.lease_worker_id = "dead-worker"
        policy.claim_generation = 1
        policy.visibility_deadline = now - timedelta(seconds=1)
        db.query(JdWorkbenchStoreStatus).one().next_sync_at = now - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()

    assert worker.run_jd_workbench_scheduler(now) == 0
    db = sessions()
    try:
        policy = db.query(JdWorkbenchSyncPolicy).one()
        assert policy.queue_state == "processing"
        assert policy.lease_worker_id == "dead-worker"
        assert policy.visibility_deadline == now - timedelta(seconds=1)
    finally:
        db.close()

    assert worker._recover_jd_workbench_task(task, now) is True
    assert worker._recover_jd_workbench_task(task, now) is True
    db = sessions()
    try:
        policy = db.query(JdWorkbenchSyncPolicy).one()
        assert policy.queue_state == "ready"
        assert policy.lease_worker_id is None
        assert policy.visibility_deadline is None
        status = db.query(JdWorkbenchStoreStatus).one()
        window = policy.sync_window_started_at
        completed_task_id = policy.active_task_id
        policy.active_task_id = None
        policy.queue_state = None
        status.next_sync_at = window + timedelta(seconds=10)
        db.add(JdSyncLog(
            task_id=completed_task_id,
            tenant_id=policy.tenant_id,
            company_id=policy.company_id,
            store_id=policy.store_id,
            task_type="sync_jd_smart",
            source="cloud_scheduler",
            attempt=0,
            status="success",
            sync_window_started_at=window,
        ))
        db.commit()
    finally:
        db.close()
    redis.lists[queue.QUEUE_NAME] = []
    assert worker.run_jd_workbench_scheduler(window + timedelta(seconds=20)) == 0
    assert redis.lists[queue.QUEUE_NAME] == []
    db = sessions()
    try:
        policy = db.query(JdWorkbenchSyncPolicy).one()
        policy.active_task_id = "00000000-0000-4000-8000-000000000999"
        policy.queue_state = "processing"
        policy.lease_worker_id = "worker-new"
        policy.claim_generation = 2
        db.commit()
        with pytest.raises(JdCollectorError, match="任务租约已失效"):
            worker._assert_jd_workbench_claim_owned(
                db,
                {
                    "task_id": completed_task_id,
                    "db_claim_generation": 1,
                    "payload": {"tenant_id": policy.tenant_id, "company_id": policy.company_id, "store_id": policy.store_id},
                },
                "worker-old",
            )
        db.rollback()
    finally:
        db.close()
    engine.dispose()


def test_reaper_recovers_expired_postgres_claim_without_redis_processing(
    postgres_database_factory,
    monkeypatch,
):
    from backend import worker
    from tests.conftest import _alembic

    database_url = postgres_database_factory("r297_postgres_reaper")
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    task_id = str(uuid.uuid4())
    db = sessions()
    try:
        tenant = Tenant(tenant_code="R297-R", tenant_name="R297 reaper")
        db.add(tenant)
        db.flush()
        company = Company(
            tenant_id=tenant.id,
            company_code="R297-R",
            company_name="R297 reaper",
        )
        db.add(company)
        db.flush()
        store = Store(
            tenant_id=tenant.id,
            company_id=company.id,
            platform="jd",
            store_code="R297-R",
            store_name="R297 reaper",
            active=True,
        )
        db.add(store)
        db.flush()
        user = User(
            username="r297-reaper-owner",
            password_hash="not-a-real-secret",
            role="owner",
            display_name="R297 reaper owner",
            tenant_id=tenant.id,
            company_id=company.id,
            active=True,
        )
        db.add(user)
        db.flush()
        device = JdWorkbenchDevice(
            device_id="00000000-0000-4000-8000-000000000298",
            token_hash="b" * 64,
            public_key_n="b" * 256,
            public_key_e=65537,
            tenant_id=tenant.id,
            company_id=company.id,
            user_id=user.id,
            device_name="reaper-test",
            client_version="2.97.0",
            status="ONLINE",
            expires_at=now + timedelta(days=1),
        )
        db.add(device)
        db.flush()
        db.add(JdWorkbenchStoreStatus(
            device_id=device.device_id,
            store_id=store.id,
            status="SYNCING",
            next_sync_at=now,
        ))
        db.add(JdWorkbenchSyncPolicy(
            tenant_id=tenant.id,
            company_id=company.id,
            store_id=store.id,
            enabled=True,
            interval_seconds=300,
            active_task_id=task_id,
            queue_state="processing",
            lease_worker_id="dead-worker",
            claim_generation=3,
            visibility_deadline=now - timedelta(seconds=1),
            sync_window_started_at=now - timedelta(minutes=5),
        ))
        db.commit()
        scope = (tenant.id, company.id, store.id)
    finally:
        db.close()

    delivered = []
    delivery_lock = threading.Lock()

    def ensure_delivery(task, *, now):
        with delivery_lock:
            if any(item["task_id"] == task["task_id"] for item in delivered):
                return False
            delivered.append(task)
            return True

    monkeypatch.setattr(worker, "SessionLocal", sessions)
    monkeypatch.setattr(worker, "ensure_task_delivery", ensure_delivery, raising=False)

    def reap_non_cloud_only(*, before_requeue, **_kwargs):
        assert before_requeue({
            "task_type": "sync_jd_smart",
            "payload": {"source": "cloud_scheduler"},
        }) is False
        return []

    monkeypatch.setattr(worker, "reap_expired_tasks", reap_non_cloud_only)
    try:
        barrier = threading.Barrier(3)
        results = []

        def reap():
            barrier.wait()
            results.append(worker.reap_jd_workbench_tasks(now))

        threads = [threading.Thread(target=reap) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=10)

        assert sorted(results) == [0, 1]
        assert len(delivered) == 1
        task = delivered[0]
        assert task["task_id"] == task_id
        assert task["task_type"] == "sync_jd_smart"
        assert task["payload"]["source"] == "cloud_scheduler"
        assert (
            task["payload"]["tenant_id"],
            task["payload"]["company_id"],
            task["payload"]["store_id"],
        ) == scope
        assert task["claim_generation"] == 3
        db = sessions()
        try:
            policy = db.query(JdWorkbenchSyncPolicy).one()
            assert policy.queue_state == "ready"
            assert policy.lease_worker_id is None
            assert policy.visibility_deadline is None
        finally:
            db.close()
        stale_attempt = {**task, "attempt": 1}
        assert worker._claim_jd_workbench_task(
            stale_attempt,
            "worker-stale-attempt",
            now,
        ) == "discard"
        db = sessions()
        try:
            policy = db.query(JdWorkbenchSyncPolicy).one()
            assert policy.queue_state == "ready"
            assert policy.claim_generation == 3
        finally:
            db.close()
        assert worker.reap_jd_workbench_tasks(now) == 0
        db = sessions()
        try:
            policy = db.query(JdWorkbenchSyncPolicy).one()
            policy.queue_state = "processing"
            policy.lease_worker_id = "worker-after-restart"
            policy.visibility_deadline = now - timedelta(seconds=1)
            db.add(JdSyncLog(
                task_id=task_id,
                tenant_id=scope[0],
                company_id=scope[1],
                store_id=scope[2],
                task_type="sync_jd_smart",
                source="cloud_scheduler",
                status="failed",
                attempt=5,
                claim_generation=policy.claim_generation,
                sync_window_started_at=policy.sync_window_started_at,
            ))
            db.commit()
        finally:
            db.close()
        assert worker.reap_jd_workbench_tasks(now) == 0
        assert len(delivered) == 1
        db = sessions()
        try:
            policy = db.query(JdWorkbenchSyncPolicy).one()
            assert policy.active_task_id is None
            assert policy.queue_state is None
            status = db.query(JdWorkbenchStoreStatus).one()
            assert status.status == "ERROR"
            assert status.reason_code == "COLLECTOR_FAILED"
            assert status.last_error_at == now
        finally:
            db.close()
    finally:
        engine.dispose()


def test_stale_worker_cannot_overwrite_new_claim_with_failed_log(postgres_database_factory, monkeypatch):
    from backend import queue, worker
    from tests.conftest import _alembic

    database_url = postgres_database_factory("r297_stale_failure_fence")
    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    now = datetime.now(timezone.utc)
    task_id = str(uuid.uuid4())
    db = sessions()
    try:
        tenant = Tenant(tenant_code="R297-F", tenant_name="R297 fence")
        db.add(tenant)
        db.flush()
        company = Company(tenant_id=tenant.id, company_code="R297-F", company_name="R297 fence")
        db.add(company)
        db.flush()
        store = Store(
            tenant_id=tenant.id, company_id=company.id, platform="jd",
            store_code="R297-F", store_name="R297 fence", active=True,
        )
        db.add(store)
        db.flush()
        db.add(JdWorkbenchSyncPolicy(
            tenant_id=tenant.id, company_id=company.id, store_id=store.id,
            enabled=True, interval_seconds=300, active_task_id=task_id,
            queue_state="processing", lease_worker_id="worker-old", claim_generation=1,
            visibility_deadline=now + timedelta(minutes=1),
        ))
        db.commit()
        scope = (tenant.id, company.id, store.id)
    finally:
        db.close()

    def takeover_then_fail(_db, _store_id, **_kwargs):
        takeover = sessions()
        try:
            policy = takeover.query(JdWorkbenchSyncPolicy).with_for_update().one()
            policy.lease_worker_id = "worker-new"
            policy.claim_generation = 2
            policy.visibility_deadline = now + timedelta(minutes=2)
            log = takeover.query(JdSyncLog).filter_by(task_id=task_id, attempt=0).one()
            log.claim_generation = 2
            log.status = "running"
            takeover.commit()
        finally:
            takeover.close()
        raise RuntimeError("old worker lost ownership")

    redis = SchedulerRedis()
    monkeypatch.setattr(worker, "SessionLocal", sessions)
    monkeypatch.setattr(worker, "get_redis", lambda: redis)
    monkeypatch.setattr(queue, "get_redis", lambda: redis)
    monkeypatch.setattr(worker, "sync_jd_smart", takeover_then_fail)
    task = {
        "task_id": task_id,
        "task_type": "sync_jd_smart",
        "attempt": 0,
        "max_retries": 5,
        "db_claim_generation": 1,
        "_worker_id": "worker-old",
        "payload": {
            "source": "cloud_scheduler", "tenant_id": scope[0],
            "company_id": scope[1], "store_id": scope[2],
            "sync_window_started_at": now.isoformat(),
        },
    }
    with pytest.raises(JdCollectorError, match="任务租约已失效"):
        worker._handle_task_direct(task)

    db = sessions()
    try:
        log = db.query(JdSyncLog).filter_by(task_id=task_id, attempt=0).one()
        policy = db.query(JdWorkbenchSyncPolicy).one()
        assert (log.status, log.claim_generation) == ("running", 2)
        assert (policy.lease_worker_id, policy.claim_generation) == ("worker-new", 2)
        log.status = "success"
        db.commit()
    finally:
        db.close()

    with pytest.raises(JdCollectorError, match="任务租约已失效"):
        worker._handle_task_direct(task)
    db = sessions()
    try:
        log = db.query(JdSyncLog).filter_by(task_id=task_id, attempt=0).one()
        policy = db.query(JdWorkbenchSyncPolicy).one()
        assert (log.status, log.claim_generation) == ("success", 2)
        policy.active_task_id = None
        policy.queue_state = None
        policy.lease_worker_id = None
        db.commit()
    finally:
        db.close()
    completed_task = {**task, "db_claim_generation": 2}
    assert worker._clear_completed_jd_workbench_policy(completed_task, now) is True
    db = sessions()
    try:
        policy = db.query(JdWorkbenchSyncPolicy).one()
        assert policy.active_task_id is None
        assert policy.claim_generation == 2
    finally:
        db.close()
        engine.dispose()
