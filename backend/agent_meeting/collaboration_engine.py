from __future__ import annotations

from typing import Any

from backend.agent_meeting.agent_message import DEFAULT_INVITEES, build_agent_message
from backend.agent_meeting.consensus import build_consensus
from backend.security.tian_shen import evaluate_command
from backend.workflow.router import route_event


def run_ai_meeting(goal: str, context: dict[str, Any] | None = None, invitees: list[str] | None = None) -> dict[str, Any]:
    safe_goal = (goal or "").strip()
    if not safe_goal:
        raise ValueError("meeting goal is required")
    selected_invitees = invitees or DEFAULT_INVITEES
    messages = [build_agent_message(employee_code, safe_goal, context) for employee_code in selected_invitees]
    consensus = build_consensus(safe_goal, messages)
    approval_event = build_approval_event(safe_goal, consensus)
    route = route_event(approval_event)
    route_preview = {
        "source": route.source,
        "target": route.target,
        "handler": route.handler,
        "queue_required": route.queue_required,
    }
    approval_gate = evaluate_command(approval_event, route_preview)
    return {
        "mode": "multi_agent_ai_meeting",
        "goal": safe_goal,
        "invitees": selected_invitees,
        "messages": messages,
        "consensus": consensus,
        "approval_gate": approval_gate,
        "route_preview": route_preview,
        "safety": {
            "discussion_only": True,
            "requires_approval_center": True,
            "uses_tian_shen": True,
            "uses_tian_brain": True,
            "uses_orchestrator_route_preview": True,
            "can_auto_execute": False,
        },
    }


def build_approval_event(goal: str, consensus: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "agent_meeting",
        "target": "orchestrator",
        "action": "review_meeting_consensus",
        "requires_boss_confirmation": True,
        "payload": {
            "goal": goal,
            "consensus": consensus.get("final_consensus"),
            "approval_required": consensus.get("approval_required"),
            "discussion_only": True,
            "can_auto_execute": False,
            "can_modify_data": False,
            "tool_action_allowed": False,
            "budget_action_allowed": False,
        },
    }
