from __future__ import annotations

import logging
import time

from .autonomy.self_healing_worker import detect_worker_error
from .core.orchestrator import execute_queued_event
from .task_queue import pop_queue, requeue_event, update_event_status


logger = logging.getLogger("tiantong.queue_worker")


def process_next_event(timeout: int = 5, raise_errors: bool = False) -> bool:
    item = pop_queue(timeout=timeout)
    if not item:
        return False
    try:
        update_event_status(item["event_id"], "running", item)
        result = execute_queued_event(item)
        item["result"] = result
        update_event_status(item["event_id"], "completed", item)
        return True
    except Exception as exc:
        item["self_healing"] = detect_worker_error(item, exc)
        attempt = int(item.get("attempt", 0))
        max_retries = int(item.get("max_retries", 3))
        if attempt < max_retries:
            requeue_event(item, str(exc))
        else:
            update_event_status(item["event_id"], "failed", item, str(exc))
        logger.exception("queue_worker_event_failed: %s", exc)
        if raise_errors:
            raise
        return False


def main() -> None:
    while True:
        process_next_event(timeout=5)
        time.sleep(0.1)


if __name__ == "__main__":
    main()
