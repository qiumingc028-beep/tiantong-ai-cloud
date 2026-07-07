from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .task_allocator import allocate_task


def coordinate_task(payload: dict[str, Any]) -> dict[str, Any]:
    task = payload if isinstance(payload, dict) else {}
    allocation = allocate_task(task)
    decision_log = build_decision_log(task, allocation)
    child_events = build_child_events(task, allocation, decision_log)
    return {
        "mode": "multi_agent_autonomous_coordination",
        "consensus": "approved_for_queue",
        "allocation": allocation,
        "decision_log": decision_log,
        "child_events": child_events,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def build_decision_log(task: dict[str, Any], allocation: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for assignment in allocation["assignments"]:
        rows.append(
            {
                "employee_code": assignment["employee_code"],
                "role": assignment["role"],
                "decision": "accept",
                "reason": f"{assignment['employee_code']} accepts {assignment['role']} for {allocation['task_type']}",
                "input_summary": summarize_task(task),
            }
        )
    rows.append(
        {
            "employee_code": "orchestrator",
            "role": "consensus",
            "decision": "approved_for_queue",
            "reason": "All planned AI employees share the same decision log before execution.",
            "input_summary": summarize_task(task),
        }
    )
    return rows


def build_child_events(task: dict[str, Any], allocation: dict[str, Any], decision_log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    task_id = int(task.get("task_id") or task.get("id") or 0)
    task_input = task.get("input") if isinstance(task.get("input"), dict) else task
    events = []
    for assignment in allocation["assignments"]:
        events.append(
            {
                "source": "autonomy",
                "target": assignment["employee_code"],
                "action": "execute_employee_skill",
                "payload": {
                    "task_id": task_id,
                    "task_type": assignment["task_type"],
                    "task_input": {
                        "source_task": task_input,
                        "autonomy_role": assignment["role"],
                        "decision_log": decision_log,
                    },
                },
            }
        )
    return events


def summarize_task(task: dict[str, Any]) -> str:
    task_type = task.get("task_type") or task.get("type") or "unknown"
    title = task.get("title") or task.get("name") or "autonomous_task"
    return f"{task_type}:{title}"
