from __future__ import annotations

from typing import Any


ROLE_TASK_TYPES = {
    "tiancai_data": ("collect_business_evidence", "data_collection"),
    "tiance_strategy": ("rank_strategy_causes", "strategy_planning"),
    "tianshang": ("optimize_commerce_plan", "ecommerce_operation"),
    "tiantou": ("review_ad_plan", "ad_performance_check"),
    "tianjian_test": ("validate_strategy", "quality_acceptance"),
    "tian_shen": ("approval_review", "security_approval"),
}


def plan_execution_steps(best_strategy: dict[str, Any]) -> list[dict[str, Any]]:
    agents = best_strategy.get("assigned_agents") if isinstance(best_strategy.get("assigned_agents"), list) else []
    steps = []
    for index, agent in enumerate(agents, start=1):
        role, task_type = ROLE_TASK_TYPES.get(agent, ("contribute_strategy", "strategy_support"))
        steps.append(
            {
                "step_id": index,
                "employee_code": agent,
                "role": role,
                "task_type": task_type,
                "input": {
                    "strategy_code": best_strategy.get("strategy_code"),
                    "strategy_name": best_strategy.get("strategy_name"),
                    "goal": best_strategy.get("goal"),
                    "upstream": "previous_step_result",
                },
                "requires_approval": True,
                "can_auto_execute": False,
            }
        )
    return steps
