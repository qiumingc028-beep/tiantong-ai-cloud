from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.database import get_redis
from backend.task_queue import ORCHESTRATOR_STATUS_PREFIX


COMMAND_PREFIX = "tiantong:command_center:command:"
COMMAND_INDEX_KEY = "tiantong:command_center:commands"
COMMAND_TTL_SECONDS = 7 * 24 * 3600


def new_command_id() -> str:
    return str(uuid.uuid4())


def save_command_record(record: dict[str, Any]) -> dict[str, Any]:
    command_id = record["command_id"]
    record["updated_at"] = utc_now()
    redis_client = get_redis()
    redis_client.setex(f"{COMMAND_PREFIX}{command_id}", COMMAND_TTL_SECONDS, json.dumps(record, ensure_ascii=False))
    redis_client.lpush(COMMAND_INDEX_KEY, command_id)
    redis_client.ltrim(COMMAND_INDEX_KEY, 0, 49)
    return record


def get_command_record(command_id: str) -> dict[str, Any] | None:
    raw = get_redis().get(f"{COMMAND_PREFIX}{command_id}")
    if not raw:
        return None
    return json.loads(raw)


def command_status(command_id: str) -> dict[str, Any] | None:
    record = get_command_record(command_id)
    if not record:
        return None
    events = []
    for event_id in record.get("event_ids", []):
        raw = get_redis().get(f"{ORCHESTRATOR_STATUS_PREFIX}{event_id}")
        events.append(json.loads(raw) if raw else {"event_id": event_id, "status": "unknown"})
    statuses = [row.get("status") for row in events]
    if statuses and all(status == "completed" for status in statuses):
        status = "completed"
    elif any(status in {"failed"} for status in statuses):
        status = "failed"
    elif any(status in {"running", "retrying", "queued"} for status in statuses):
        status = "running"
    else:
        status = record.get("status", "submitted")
    return {**record, "status": status, "events": events}


def command_history(limit: int = 20) -> list[dict[str, Any]]:
    ids = get_redis().lrange(COMMAND_INDEX_KEY, 0, max(limit - 1, 0))
    rows = []
    seen = set()
    for command_id in ids:
        if isinstance(command_id, bytes):
            command_id = command_id.decode("utf-8")
        if command_id in seen:
            continue
        seen.add(command_id)
        record = command_status(str(command_id))
        if record:
            rows.append(record)
    return rows


def operations_snapshot(limit: int = 50) -> dict[str, Any]:
    rows = command_history(limit)
    logs = employee_logs_from_commands(rows)
    status_counts = {
        "running": sum(1 for row in rows if row.get("status") == "running"),
        "completed": sum(1 for row in rows if row.get("status") == "completed"),
        "failed": sum(1 for row in rows if row.get("status") == "failed"),
        "submitted": sum(1 for row in rows if row.get("status") == "submitted"),
    }
    completed_today = sum(1 for row in rows if row.get("status") == "completed" and is_today(row.get("updated_at") or row.get("created_at")))
    terminal = status_counts["completed"] + status_counts["failed"]
    success_rate = round(status_counts["completed"] / terminal, 4) if terminal else 0
    risk_count = count_risks(rows)
    return {
        "summary": {
            "current_tasks": status_counts["running"] + status_counts["submitted"],
            "today_completed": completed_today,
            "success_rate": success_rate,
            "risk_count": risk_count,
            "total_commands": len(rows),
        },
        "employee_statuses": build_employee_statuses(rows),
        "current_tasks": [row for row in rows if row.get("status") in {"running", "submitted"}],
        "recent_logs": logs[:30],
    }


def employee_logs_from_commands(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logs = []
    for command in commands:
        steps = ((command.get("parsed") or {}).get("steps") or [])
        events = command.get("events") or []
        for index, step in enumerate(steps):
            event = events[index] if index < len(events) else {}
            result = event.get("result") or {}
            tian_shen = ((command.get("dispatches") or [{}])[index].get("tian_shen") if index < len(command.get("dispatches") or []) else {}) or {}
            logs.append(
                {
                    "command_id": command.get("command_id"),
                    "employee_code": step.get("employee_code"),
                    "role": step.get("role"),
                    "executed_at": event.get("updated_at") or command.get("updated_at") or command.get("created_at"),
                    "tool": "orchestrator_queue",
                    "status": event.get("status") or "queued",
                    "result": result.get("result") if isinstance(result, dict) else result,
                    "failure_reason": event.get("message") or "",
                    "risk_decision": tian_shen.get("decision") or "",
                }
            )
    return logs


def build_employee_statuses(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    employees = {
        "tiancai_data": ("天采", "idle"),
        "tiance_strategy": ("天策", "idle"),
        "tianchuang": ("天创", "idle"),
        "tianshang": ("天商", "idle"),
        "tiantou": ("天投", "idle"),
        "tianjian_test": ("天检", "idle"),
        "tiandun_ops": ("天盾", "idle"),
        "tian_shen": ("天审", "idle"),
    }
    latest = {code: {"employee_code": code, "employee_name": name, "status": status, "current_task": ""} for code, (name, status) in employees.items()}
    for command in commands:
        steps = ((command.get("parsed") or {}).get("steps") or [])
        events = command.get("events") or []
        for index, step in enumerate(steps):
            code = step.get("employee_code")
            if code not in latest:
                continue
            event = events[index] if index < len(events) else {}
            event_status = event.get("status") or command.get("status")
            latest[code]["status"] = employee_runtime_status(event_status)
            latest[code]["current_task"] = command.get("command") or ""
        for dispatch in command.get("dispatches") or []:
            decision = ((dispatch or {}).get("tian_shen") or {}).get("decision")
            if decision:
                latest["tian_shen"]["status"] = "blocked" if decision == "RED" else "running"
                latest["tian_shen"]["current_task"] = command.get("command") or ""
    return list(latest.values())


def employee_runtime_status(status: str | None) -> str:
    if status in {"failed"}:
        return "error"
    if status in {"retrying"}:
        return "blocked"
    if status in {"queued", "running", "submitted"}:
        return "running"
    return "idle"


def count_risks(commands: list[dict[str, Any]]) -> int:
    count = 0
    for command in commands:
        for dispatch in command.get("dispatches") or []:
            decision = ((dispatch or {}).get("tian_shen") or {}).get("decision")
            if decision in {"YELLOW", "RED"}:
                count += 1
    return count


def is_today(value: str | None) -> bool:
    if not value:
        return False
    try:
        return datetime.fromisoformat(value).date() == datetime.now(timezone.utc).date()
    except Exception:
        return False


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
