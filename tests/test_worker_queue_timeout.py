from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from backend.queue import dequeue_task
from backend.worker import process_next_task


class EmptyRedis:
    def blpop(self, key, timeout=0):
        return None


class TimeoutRedis:
    def blpop(self, key, timeout=0):
        raise RedisTimeoutError("Timeout reading from socket")


class ConnectionErrorRedis:
    def blpop(self, key, timeout=0):
        raise RedisConnectionError("Redis connection lost")


def test_dequeue_task_returns_none_when_queue_empty(monkeypatch):
    monkeypatch.setattr("backend.queue.get_redis", lambda: EmptyRedis())

    assert dequeue_task(timeout=1) is None


def test_dequeue_task_returns_none_on_redis_timeout(monkeypatch):
    monkeypatch.setattr("backend.queue.get_redis", lambda: TimeoutRedis())

    assert dequeue_task(timeout=1) is None


def test_dequeue_task_returns_none_on_redis_connection_error(monkeypatch):
    monkeypatch.setattr("backend.queue.get_redis", lambda: ConnectionErrorRedis())

    assert dequeue_task(timeout=1) is None


def test_worker_process_next_task_does_not_exit_on_redis_timeout(monkeypatch):
    def raise_timeout(timeout=5):
        raise RedisTimeoutError("Timeout reading from socket")

    monkeypatch.setattr("backend.worker.dequeue_task", raise_timeout)
    monkeypatch.setattr("backend.worker.time.sleep", lambda seconds: None)

    assert process_next_task() is False


def test_worker_process_next_task_does_not_exit_on_redis_connection_error(monkeypatch):
    def raise_connection_error(timeout=5):
        raise RedisConnectionError("Redis connection lost")

    monkeypatch.setattr("backend.worker.dequeue_task", raise_connection_error)
    monkeypatch.setattr("backend.worker.time.sleep", lambda seconds: None)

    assert process_next_task() is False
