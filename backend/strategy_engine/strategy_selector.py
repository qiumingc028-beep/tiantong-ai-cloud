from __future__ import annotations

from typing import Any


DANGEROUS_ACTIONS = (
    "删除数据库",
    "drop database",
    "git push",
    "生产部署",
    "deploy production",
    "付款",
    "花钱",
    "spend money",
)


def select_best_strategy(meeting: dict[str, Any]) -> dict[str, Any]:
    messages = meeting.get("messages") if isinstance(meeting.get("messages"), list) else []
    consensus = meeting.get("consensus") if isinstance(meeting.get("consensus"), dict) else {}
    goal = str(meeting.get("goal") or consensus.get("goal") or "business_goal")
    candidates = build_strategy_options(goal, messages, consensus)
    ranked = sorted(candidates, key=lambda row: row["total_score"], reverse=True)
    best = ranked[0] if ranked else {}
    return {
        "center": "AI Strategy Decision Loop",
        "goal": goal,
        "candidate_strategies": ranked,
        "best_strategy": best,
        "risk_score": best.get("risk_score", 0),
        "assigned_agents": best.get("assigned_agents", []),
        "requires_approval_center": True,
        "can_auto_execute": False,
        "safety_notes": "Strategy Engine 只形成最佳执行策略；提交执行前必须经过 TianShen Approval Center。",
    }


def build_strategy_options(goal: str, messages: list[dict[str, Any]], consensus: dict[str, Any]) -> list[dict[str, Any]]:
    base_agents = assigned_agents_from_messages(messages)
    dangerous = contains_dangerous_action(goal, consensus)
    options = [
        ("safe_diagnosis", "安全诊断优先", 78, 18, 20, 58),
        ("balanced_growth", "平衡增长执行", 72, 32, 38, 76),
        ("aggressive_growth", "激进增长冲刺", 61, 58, 65, 90),
    ]
    strategies = []
    for code, name, success, risk, cost, revenue in options:
        if dangerous:
            risk = max(risk, 95)
        total_score = round(success + revenue * 0.75 - risk * 0.85 - cost * 0.35, 2)
        strategies.append(
            {
                "strategy_code": code,
                "strategy_name": name,
                "goal": goal,
                "success_probability": success / 100,
                "risk_score": risk,
                "cost_score": cost,
                "expected_revenue_score": revenue,
                "total_score": total_score,
                "assigned_agents": base_agents,
                "requires_approval": True,
                "blocked_by_default": dangerous,
                "forbidden_actions": matched_dangerous_actions(goal, consensus),
                "can_auto_execute": False,
                "can_delete_database": False,
                "can_git_push": False,
                "can_deploy_production": False,
                "can_spend_money": False,
            }
        )
    return strategies


def assigned_agents_from_messages(messages: list[dict[str, Any]]) -> list[str]:
    agents = [str(message.get("employee_code")) for message in messages if message.get("employee_code")]
    fallback = ["tiancai_data", "tiance_strategy", "tianshang", "tiantou", "tianjian_test", "tian_shen"]
    return agents or fallback


def contains_dangerous_action(goal: str, consensus: dict[str, Any]) -> bool:
    return bool(matched_dangerous_actions(goal, consensus))


def matched_dangerous_actions(goal: str, consensus: dict[str, Any]) -> list[str]:
    text = f"{goal} {consensus}".lower()
    return [action for action in DANGEROUS_ACTIONS if action.lower() in text]
