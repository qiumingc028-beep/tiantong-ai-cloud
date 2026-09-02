from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from backend import queue


class ReliableFakeRedis:
    def __init__(self):
        self.lists: dict[str, list[str]] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start : end + 1]

    def setex(self, key, _ttl, value):
        self.hashes[key] = {"value": value}

    def blmove(self, source, destination, timeout, src="LEFT", dest="RIGHT"):
        values = self.lists.get(source, [])
        if not values:
            return None
        value = values.pop(0)
        self.lists.setdefault(destination, []).append(value)
        return value

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update({name: str(value) for name, value in mapping.items()})

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def expire(self, _key, _ttl):
        return True

    def zadd(self, key, mapping):
        self.sorted_sets.setdefault(key, {}).update(mapping)

    def zrangebyscore(self, key, minimum, maximum):
        minimum = float("-inf") if minimum == "-inf" else float(minimum)
        maximum = float("inf") if maximum == "+inf" else float(maximum)
        return [value for value, score in self.sorted_sets.get(key, {}).items() if minimum <= score <= maximum]

    def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        return values[start:] if end == -1 else values[start : end + 1]

    def lrem(self, key, count, value):
        values = self.lists.get(key, [])
        if value not in values:
            return 0
        values.remove(value)
        return 1

    def delete(self, key):
        self.hashes.pop(key, None)

    def zrem(self, key, value):
        self.sorted_sets.get(key, {}).pop(value, None)

    def pipeline(self):
        return Pipeline(self)

    def eval(self, script, _key_count, *args):
        if script == queue._CLAIM_SCRIPT:
            ready, processing, deadlines, prefix, worker_id, now, deadline, _ttl, score = args
            values = self.lists.get(ready, [])
            if not values:
                return None
            raw = values.pop(0)
            task = json.loads(raw)
            payload = task.get("payload") or {}
            metadata = prefix + task["task_id"]
            self.lists.setdefault(processing, []).append(raw)
            self.hashes[metadata] = {
                "task_id": task["task_id"],
                "tenant_id": str(payload.get("tenant_id") or ""),
                "company_id": str(payload.get("company_id") or ""),
                "store_id": str(payload.get("store_id") or ""),
                "sync_window_started_at": str(payload.get("sync_window_started_at") or ""),
                "claimed_by": worker_id,
                "started_at": now,
                "heartbeat_at": now,
                "visibility_deadline": deadline,
            }
            self.zadd(deadlines, {task["task_id"]: float(score)})
            return raw
        if script == queue._HEARTBEAT_SCRIPT:
            metadata, deadlines, worker_id, heartbeat, deadline, _ttl, task_id, score = args
            if self.hashes.get(metadata, {}).get("claimed_by") != worker_id:
                return 0
            self.hashes[metadata].update({"heartbeat_at": heartbeat, "visibility_deadline": deadline})
            self.zadd(deadlines, {task_id: float(score)})
            return 1
        if script == queue._ACK_SCRIPT:
            processing, metadata, deadlines, raw, worker_id, task_id = args
            if self.hashes.get(metadata, {}).get("claimed_by") != worker_id:
                return 0
            if not self.lrem(processing, 1, raw):
                return 0
            self.delete(metadata)
            self.zrem(deadlines, task_id)
            return 1
        processing, ready, metadata, deadlines, raw, task_id, now = args
        deadline = self.hashes.get(metadata, {}).get("visibility_deadline")
        if deadline and deadline > now:
            return 0
        if not self.lrem(processing, 1, raw):
            return 0
        self.rpush(ready, raw)
        self.delete(metadata)
        self.zrem(deadlines, task_id)
        return 1


class Pipeline:
    def __init__(self, client):
        self.client = client
        self.operations = []

    def __getattr__(self, name):
        def queue_operation(*args, **kwargs):
            self.operations.append((name, args, kwargs))
            return self

        return queue_operation

    def execute(self):
        return [getattr(self.client, name)(*args, **kwargs) for name, args, kwargs in self.operations]


def test_claim_moves_ready_task_to_processing_and_ack_removes_it(monkeypatch):
    redis = ReliableFakeRedis()
    monkeypatch.setattr(queue, "get_redis", lambda: redis)
    item = queue.enqueue_task(
        "sync_jd_smart",
        {
            "tenant_id": 11,
            "company_id": 22,
            "store_id": 33,
            "sync_window_started_at": "2026-09-02T00:00:00+00:00",
        },
    )

    claimed = queue.claim_task(worker_id="worker-1", timeout=0, visibility_timeout=60)

    assert claimed["task_id"] == item["task_id"]
    assert redis.lists[queue.QUEUE_NAME] == []
    assert len(redis.lists[queue.PROCESSING_QUEUE_NAME]) == 1
    metadata = redis.hgetall(f"{queue.PROCESSING_METADATA_PREFIX}{item['task_id']}")
    assert metadata["task_id"] == item["task_id"]
    assert metadata["tenant_id"] == "11"
    assert metadata["company_id"] == "22"
    assert metadata["store_id"] == "33"
    assert metadata["claimed_by"] == "worker-1"
    assert metadata["started_at"]
    assert metadata["visibility_deadline"]

    assert queue.ack_task(claimed, "worker-1") is True
    assert redis.lists[queue.PROCESSING_QUEUE_NAME] == []
    assert redis.hgetall(f"{queue.PROCESSING_METADATA_PREFIX}{item['task_id']}") == {}


def test_stale_worker_cannot_ack_reassigned_task(monkeypatch):
    redis = ReliableFakeRedis()
    monkeypatch.setattr(queue, "get_redis", lambda: redis)
    item = queue.enqueue_task("sync_jd_smart", {"tenant_id": 1, "company_id": 2, "store_id": 3})
    claimed = queue.claim_task(worker_id="worker-old", timeout=0, visibility_timeout=30)
    metadata_key = f"{queue.PROCESSING_METADATA_PREFIX}{item['task_id']}"
    redis.hashes[metadata_key]["claimed_by"] = "worker-new"

    assert queue.ack_task(claimed, "worker-old") is False
    assert len(redis.lists[queue.PROCESSING_QUEUE_NAME]) == 1


def test_worker_heartbeat_extends_database_lease_before_redis(monkeypatch):
    from backend import worker

    calls = []
    heartbeat = worker._TaskHeartbeat({"task_id": "task-1"}, "worker-1")
    monkeypatch.setattr(heartbeat.stop, "wait", lambda _seconds: False)
    monkeypatch.setattr(
        worker,
        "_heartbeat_jd_workbench_task",
        lambda *_args: calls.append("database") or True,
    )
    monkeypatch.setattr(
        worker,
        "heartbeat_task",
        lambda *_args, **_kwargs: calls.append("redis") or False,
    )

    heartbeat._run()

    assert calls == ["database", "redis"]


def test_heartbeat_extends_visibility_and_reaper_recovers_only_expired_task(monkeypatch):
    redis = ReliableFakeRedis()
    monkeypatch.setattr(queue, "get_redis", lambda: redis)
    item = queue.enqueue_task("sync_jd_smart", {"tenant_id": 1, "company_id": 2, "store_id": 3})
    claimed = queue.claim_task(worker_id="worker-1", timeout=0, visibility_timeout=30)
    metadata_key = f"{queue.PROCESSING_METADATA_PREFIX}{item['task_id']}"
    original_deadline = redis.hashes[metadata_key]["visibility_deadline"]

    future = datetime.now(timezone.utc) + timedelta(seconds=10)
    assert queue.heartbeat_task(claimed, worker_id="worker-1", now=future, visibility_timeout=60) is True
    assert redis.hashes[metadata_key]["visibility_deadline"] > original_deadline
    assert queue.reap_expired_tasks(now=future) == []

    expired_at = future + timedelta(seconds=61)
    callback_states = []
    recovered = queue.reap_expired_tasks(
        now=expired_at,
        before_requeue=lambda _task: callback_states.append(
            len(redis.lists[queue.PROCESSING_QUEUE_NAME])
        ) or True,
    )
    assert [task["task_id"] for task in recovered] == [item["task_id"]]
    assert callback_states == [1]
    assert redis.lists[queue.PROCESSING_QUEUE_NAME] == []
    assert json.loads(redis.lists[queue.QUEUE_NAME][0])["task_id"] == item["task_id"]


def test_retry_backoff_contract_is_exactly_five_levels():
    from backend.worker import JD_RETRY_BACKOFF_SECONDS

    assert JD_RETRY_BACKOFF_SECONDS == (30, 120, 300, 900, 1800)


def test_worker_process_identity_is_used_for_brain_worker(monkeypatch):
    from backend import worker

    captured = {}
    monkeypatch.setattr(worker, "SessionLocal", lambda: type("Session", (), {"close": lambda self: None})())
    monkeypatch.setattr(worker, "_worker_id", lambda: "host:123")
    monkeypatch.setattr(
        worker,
        "process_next_brain_execution",
        lambda _db, timeout, worker_id: captured.update(timeout=timeout, worker_id=worker_id) or {"processed": False},
    )

    assert worker.process_next_brain_runtime_execution() is False
    assert captured == {"timeout": 1, "worker_id": "brain-host:123"}


def test_sync_policy_persists_one_active_task_lease_per_store():
    from backend.models import JdWorkbenchSyncPolicy

    columns = JdWorkbenchSyncPolicy.__table__.columns
    assert columns["active_task_id"].unique is True
    for name in (
        "queue_state",
        "lease_worker_id",
        "lease_started_at",
        "lease_heartbeat_at",
        "visibility_deadline",
        "sync_window_started_at",
    ):
        assert name in columns


def test_machine_evidence_entrypoints_bind_checkout_head_and_write_hashes():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    process = (root / "ops" / "r297_process_acceptance.py").read_text()
    windows = (root / "ops" / "r297_windows_acceptance.ps1").read_text()
    ci = (root / ".github" / "workflows" / "ci.yml").read_text()
    windows_ci = (root / ".github" / "workflows" / "r291-windows-workbench.yml").read_text()

    assert 'head = run("git", "rev-parse", "HEAD")' in process
    assert 'head != os.environ.get("RELEASE_SOURCE_SHA")' in process
    assert "R297_PROCESS_ACCEPTANCE_EVIDENCE.json.sha256" in ci
    assert "python ops/r297_process_acceptance.py" in ci
    assert "$env:GITHUB_SHA -eq $head" in windows
    assert '"$evidencePath.sha256"' in windows
    assert "ops/r297_windows_acceptance.ps1" in windows_ci
