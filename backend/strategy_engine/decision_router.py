from __future__ import annotations

from typing import Any

from backend.security.tian_shen import evaluate_command
from backend.strategy_engine.execution_planner import plan_execution_steps
from backend.workflow.router import route_event


def route_strategy(best_strategy: dict[str, Any], submit_to_queue: bool = False) -> dict[str, Any]:
    steps = plan_execution_steps(best_strategy)
    approvals = []
    dispatches = []
    for step in steps:
        event = build_step_event(best_strategy, step)
        route = route_event(event)
        route_payload = {
            "source": route.source,
            "target": route.target,
            "handler": route.handler,
            "queue_required": route.queue_required,
        }
        approval = evaluate_command(event, route_payload)
        approvals.append({"step_id": step["step_id"], "employee_code": step["employee_code"], "approval": approval, "route": route_payload})
        if submit_to_queue and approval.get("allowed"):
            from backend.core.orchestrator import handle_event

            dispatches.append(handle_event(event))
        elif submit_to_queue:
            dispatches.append({"ok": False, "queued": False, "step_id": step["step_id"], "tian_shen": approval})
    return {
        "mode": "strategy_route_preview" if not submit_to_queue else "strategy_route_to_queue",
        "steps": steps,
        "approvals": approvals,
        "dispatches": dispatches,
        "submit_to_queue": submit_to_queue,
        "can_auto_execute": False,
        "requires_approval_center": True,
    }


def build_step_event(best_strategy: dict[str, Any], step: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "strategy_engine",
        "target": step["employee_code"],
        "action": "execute_employee_skill",
        "requires_boss_confirmation": bool(best_strategy.get("requires_approval") or best_strategy.get("blocked_by_default")),
        "payload": {
            "task_id": 0,
            "task_type": step["task_type"],
            "task_input": {
                "strategy_code": best_strategy.get("strategy_code"),
                "strategy_name": best_strategy.get("strategy_name"),
                "goal": best_strategy.get("goal"),
                "role": step["role"],
                "forbidden_actions": best_strategy.get("forbidden_actions") or [],
                "can_auto_execute": False,
                "can_delete_database": False,
                "can_git_push": False,
                "can_deploy_production": False,
                "budget_action_allowed": False,
            },
        },
    }
