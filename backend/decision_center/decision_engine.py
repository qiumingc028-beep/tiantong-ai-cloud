from __future__ import annotations

from typing import Any

from backend.decision_center.decision_memory import record_decision
from backend.decision_center.strategy_ranker import build_strategy_candidates, rank_strategies
from backend.security.tian_shen import evaluate_command
from backend.workflow.router import route_event


def evaluate_business_decisions(opportunities: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = [evaluate_opportunity(opportunity) for opportunity in opportunities]
    return {
        "center": "TianBrain AI Decision Center",
        "mode": "recommendation_only",
        "decisions": decisions,
        "recommended_strategy": first_recommended_strategy(decisions),
        "safety": {
            "can_auto_execute": False,
            "requires_approval_center": True,
            "uses_tian_shen": True,
            "uses_tian_brain": True,
            "uses_orchestrator_route_preview": True,
        },
    }


def evaluate_opportunity(opportunity: dict[str, Any]) -> dict[str, Any]:
    ranked = rank_strategies(build_strategy_candidates(opportunity))
    recommended = ranked[0] if ranked else {}
    approval_event = build_approval_preview_event(opportunity, recommended)
    route = route_event(approval_event)
    route_payload = {
        "source": route.source,
        "target": route.target,
        "handler": route.handler,
        "queue_required": route.queue_required,
    }
    approval = evaluate_command(approval_event, route_payload)
    decision = {
        "opportunity_id": opportunity.get("opportunity_id") or "",
        "source_signal": opportunity.get("source_signal") or {},
        "candidate_strategies": ranked,
        "recommended_strategy": recommended,
        "approval_gate": approval,
        "route_preview": route_payload,
        "decision_summary": summarize_decision(opportunity, recommended, approval),
        "can_auto_execute": False,
        "requires_approval": True,
    }
    return record_decision(decision)


def build_approval_preview_event(opportunity: dict[str, Any], strategy: dict[str, Any]) -> dict[str, Any]:
    signal = opportunity.get("source_signal") or {}
    return {
        "source": "decision_center",
        "target": "orchestrator",
        "action": "recommend_strategy",
        "requires_boss_confirmation": bool(strategy.get("requires_approval") or opportunity.get("approval_required")),
        "payload": {
            "opportunity_id": opportunity.get("opportunity_id"),
            "signal_type": signal.get("signal_type"),
            "strategy_code": strategy.get("strategy_code"),
            "strategy_name": strategy.get("strategy_name"),
            "total_score": strategy.get("total_score"),
            "can_auto_execute": False,
            "can_modify_data": False,
            "budget_action_allowed": False,
        },
    }


def summarize_decision(opportunity: dict[str, Any], strategy: dict[str, Any], approval: dict[str, Any]) -> str:
    signal = opportunity.get("source_signal") or {}
    return (
        f"针对{signal.get('store', '目标业务')}{signal.get('title', '业务异常')}，"
        f"建议采用{strategy.get('strategy_name', '候选方案')}，"
        f"综合评分{strategy.get('total_score', 0)}，审批状态{approval.get('decision')}。"
    )


def first_recommended_strategy(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    for decision in decisions:
        strategy = decision.get("recommended_strategy")
        if strategy:
            return strategy
    return {}
