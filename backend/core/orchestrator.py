from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.security.tian_shen import APPROVAL_RED, APPROVAL_YELLOW, TianShenApprovalError, evaluate_command
from backend.task_queue import push_queue
from backend.workflow.router import WorkflowRoute, route_event


logger = logging.getLogger("tiantong.orchestrator")


class Orchestrator:
    def run(self, event: dict) -> dict:
        normalized = self.normalize_event(event)
        route = route_event(normalized)
        route_payload = self.route_to_dict(route)
        approval = self.review_before_execution(normalized, route_payload)
        normalized["tian_shen"] = approval
        if not approval["allowed"]:
            return self.blocked_response(normalized, route_payload, approval)

        if not normalized.get("force_sync"):
            queued = push_queue(normalized, route_payload)
            return {
                "ok": True,
                "orchestrated": True,
                "queued": True,
                "event_id": queued["event_id"],
                "route": route_payload,
                "event": normalized,
                "tian_shen": approval,
                "handled_at": datetime.now(timezone.utc).isoformat(),
            }

        result = self.dispatch(route, normalized)
        return {
            "ok": True,
            "orchestrated": True,
            "queued": False,
            "route": {
                "source": route.source,
                "target": route.target,
                "handler": route.handler,
                "queue_required": route.queue_required,
            },
            "event": normalized,
            "result": result,
            "tian_shen": approval,
            "handled_at": datetime.now(timezone.utc).isoformat(),
        }

    def normalize_event(self, event: dict) -> dict:
        if not isinstance(event, dict):
            raise TypeError("orchestrator event must be a dict")
        normalized = dict(event)
        normalized.setdefault("source", "unknown")
        normalized.setdefault("target", "orchestrator")
        normalized.setdefault("action", normalized.get("event_type") or "dispatch")
        normalized["orchestrator_required"] = True
        return normalized

    def route_to_dict(self, route: WorkflowRoute) -> dict:
        return {
            "source": route.source,
            "target": route.target,
            "handler": route.handler,
            "queue_required": route.queue_required,
        }

    def review_before_execution(self, event: dict, route_payload: dict) -> dict:
        approval = evaluate_command(event, route_payload)
        if approval["decision"] == APPROVAL_RED:
            logger.warning("tian_shen_red_block source=%s target=%s action=%s", approval["source"], approval["target"], approval["action"])
        elif approval["decision"] == APPROVAL_YELLOW and approval["requires_confirmation"]:
            logger.info("tian_shen_yellow_waiting source=%s target=%s action=%s", approval["source"], approval["target"], approval["action"])
        return approval

    def blocked_response(self, event: dict, route_payload: dict, approval: dict) -> dict:
        return {
            "ok": False,
            "orchestrated": True,
            "queued": False,
            "blocked": approval["decision"] == APPROVAL_RED,
            "approval_required": approval["requires_confirmation"],
            "route": route_payload,
            "event": event,
            "tian_shen": approval,
            "error": approval["message"],
            "handled_at": datetime.now(timezone.utc).isoformat(),
        }

    def dispatch(self, route: WorkflowRoute, event: dict) -> Any:
        if route.handler == "autonomy.coordinate":
            from backend.autonomy.ai_team_coordinator import coordinate_task

            coordination = coordinate_task(event.get("payload") or {})
            queued_children = []
            for child_event in coordination["child_events"]:
                queued_children.append(self.run(child_event))
            coordination["queued_children"] = queued_children
            return coordination

        if route.handler == "worker.process_task":
            from backend import worker

            return worker._handle_task_direct(event["payload"])

        if route.handler == "ai_employee.execute":
            from backend.ai_employees.executors import execute_employee_skill

            payload = event.get("payload") or {}
            return execute_employee_skill(
                int(payload.get("task_id") or 0),
                payload.get("task_type") or "mock_task",
                route.target,
                payload.get("task_input"),
            )

        if route.handler == "business.ecommerce_order":
            from backend.services.ecommerce_engine import analyze_order

            return analyze_order(event.get("payload") or {})

        if route.handler == "business.ecommerce_metrics":
            from backend.services.ecommerce_engine import analyze_metrics

            return analyze_metrics(event.get("payload") or {})

        if route.handler == "business.dual_engine_decision":
            from backend.services.dual_engine_orchestrator import orchestrate_dual_engine

            return orchestrate_dual_engine(event.get("payload") or {})

        if route.handler == "business.content_video":
            from backend.services.content_ai import build_video_content

            return build_video_content(event.get("payload") or {})

        if route.handler == "business.content_xiaohongshu":
            from backend.services.content_ai import build_xiaohongshu_content

            return build_xiaohongshu_content(event.get("payload") or {})

        if route.handler == "business.content_trend":
            from backend.services.trend_analyzer import analyze_trend

            return analyze_trend(event.get("payload") or {})

        if route.handler == "business.decision_center":
            from backend.services.decision_center import decide

            return decide(event.get("payload") or {})

        if route.handler == "money.loop_start":
            from backend.services.master_money_orchestrator import start_loop

            payload = event.get("payload") or {}
            return start_loop(payload.get("seed") or {}, payload.get("cycles") or 1)

        if route.handler == "money.loop_stop":
            from backend.services.master_money_orchestrator import stop_loop

            return stop_loop()

        if route.handler == "money.loop_status":
            from backend.services.master_money_orchestrator import status

            return status()

        if route.handler == "money.optimize":
            from backend.services.master_money_orchestrator import optimize

            return optimize(event.get("payload") or {})

        logger.info("orchestrator_noop handler=%s target=%s", route.handler, route.target)
        return {"status": "noop", "handler": route.handler, "target": route.target}


def handle_event(event: dict) -> dict:
    return Orchestrator().run(event)


def execute_queued_event(item: dict) -> dict:
    event = dict(item.get("event") or {})
    event["force_sync"] = True
    result = Orchestrator().run(event)
    if not result.get("ok"):
        raise TianShenApprovalError(result.get("tian_shen") or {})
    return result
