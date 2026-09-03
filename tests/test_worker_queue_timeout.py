from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from backend.queue import claim_task
from backend import worker


class EmptyRedis:
    def eval(self, *_args):
        return None


class TimeoutRedis:
    def eval(self, *_args):
        raise RedisTimeoutError("Timeout reading from socket")


class ConnectionErrorRedis:
    def eval(self, *_args):
        raise RedisConnectionError("Redis connection lost")


def test_dequeue_task_returns_none_when_queue_empty(monkeypatch):
    monkeypatch.setattr("backend.queue.get_redis", lambda: EmptyRedis())

    assert claim_task(worker_id="test-worker", timeout=1) is None


def test_dequeue_task_returns_none_on_redis_timeout(monkeypatch):
    monkeypatch.setattr("backend.queue.get_redis", lambda: TimeoutRedis())

    assert claim_task(worker_id="test-worker", timeout=1) is None


def test_dequeue_task_returns_none_on_redis_connection_error(monkeypatch):
    monkeypatch.setattr("backend.queue.get_redis", lambda: ConnectionErrorRedis())

    assert claim_task(worker_id="test-worker", timeout=1) is None


def test_worker_process_next_task_does_not_exit_on_redis_timeout(monkeypatch):
    def raise_timeout(worker_id, timeout=5, visibility_timeout=120):
        raise RedisTimeoutError("Timeout reading from socket")

    monkeypatch.setattr("backend.worker.claim_task", raise_timeout)
    monkeypatch.setattr("backend.worker.time.sleep", lambda seconds: None)

    assert worker.process_next_task() is False


def test_worker_process_next_task_does_not_exit_on_redis_connection_error(monkeypatch):
    def raise_connection_error(worker_id, timeout=5, visibility_timeout=120):
        raise RedisConnectionError("Redis connection lost")

    monkeypatch.setattr("backend.worker.claim_task", raise_connection_error)
    monkeypatch.setattr("backend.worker.time.sleep", lambda seconds: None)

    assert worker.process_next_task() is False


def test_worker_does_not_ack_after_database_lease_was_recovered(monkeypatch):
    class NoopHeartbeat:
        def __init__(self, *_args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    acked = []
    monkeypatch.setattr(
        "backend.worker.claim_task",
        lambda **_kwargs: {"task_id": "task-1", "task_type": "sync_jd_smart", "payload": {}, "_processing_raw": "raw"},
    )
    monkeypatch.setattr("backend.worker._claim_jd_workbench_task", lambda *_args: True)
    monkeypatch.setattr("backend.worker._TaskHeartbeat", NoopHeartbeat)
    monkeypatch.setattr("backend.worker.handle_task", lambda _task: None)
    monkeypatch.setattr("backend.worker._finish_jd_workbench_task", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("backend.worker.ack_task", lambda *_args: acked.append(True))

    assert worker.process_next_task() is True
    assert acked == []
