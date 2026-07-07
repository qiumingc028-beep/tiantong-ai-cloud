from __future__ import annotations

from dataclasses import dataclass

from backend.ai_employees import AI_EMPLOYEE_REGISTRY, normalize_employee_code


@dataclass(frozen=True)
class WorkflowRoute:
    source: str
    target: str
    handler: str
    queue_required: bool = False


def route_event(event: dict) -> WorkflowRoute:
    source = safe_text(event.get("source") or "unknown")
    target = safe_text(event.get("target") or event.get("assigned_to") or "")
    action = safe_text(event.get("action") or event.get("event_type") or "")
    normalized_target = normalize_employee_code(target) or target

    if action in {"coordinate_multi_agent", "autonomous_coordinate"} or target == "autonomy":
        return WorkflowRoute(source=source, target="autonomy", handler="autonomy.coordinate", queue_required=True)

    if action == "process_worker_task" or target in {"worker", "worker.task"}:
        return WorkflowRoute(source=source, target="worker.task", handler="worker.process_task", queue_required=True)

    if action == "execute_employee_skill" or normalized_target in AI_EMPLOYEE_REGISTRY:
        return WorkflowRoute(source=source, target=normalized_target, handler="ai_employee.execute")

    business_handlers = {
        "ecommerce_order": "business.ecommerce_order",
        "ecommerce_metrics": "business.ecommerce_metrics",
        "dual_engine_decision": "business.dual_engine_decision",
        "content_video": "business.content_video",
        "content_xiaohongshu": "business.content_xiaohongshu",
        "content_trend": "business.content_trend",
        "decision_center": "business.decision_center",
        "money_loop_start": "money.loop_start",
        "money_loop_stop": "money.loop_stop",
        "money_loop_status": "money.loop_status",
        "money_optimize": "money.optimize",
    }
    if action in business_handlers:
        return WorkflowRoute(source=source, target=target or action, handler=business_handlers[action])

    if target in {"business_loop", "dual_engine", "money_loop"}:
        return WorkflowRoute(source=source, target=target, handler="business.noop")

    return WorkflowRoute(source=source, target=normalized_target or "orchestrator", handler="orchestrator.noop")


def safe_text(value) -> str:
    return str(value or "").strip()
