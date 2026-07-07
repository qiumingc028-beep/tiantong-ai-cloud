from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.employee_growth import build_employee_growth_report

from .leaderboard import build_employee_leaderboard
from .performance_stats import build_employee_performance_stats


def build_ai_employee_business_board(db: Session) -> dict[str, Any]:
    stats = build_employee_performance_stats(db)
    leaderboard = build_employee_leaderboard(stats)
    growth_cards = build_growth_cards(db, stats)
    return {
        "board_name": "AI员工经营看板",
        "mode": "readonly_performance_analysis",
        "current_running_employees": [row for row in stats if row["running_task_count"] > 0],
        "today_tasks": sum(row["today_task_count"] for row in stats),
        "success_rate": overall_success_rate(stats),
        "cost": cost_summary(stats),
        "optimization_suggestions": board_suggestions(stats, leaderboard),
        "employee_performance": stats,
        "leaderboard": leaderboard,
        "growth_cards": growth_cards,
        "connected_centers": ["Employee Growth Center", "TianBrain", "TianCang"],
        "safety": {
            "analysis_only": True,
            "can_auto_adjust_permission": False,
            "can_auto_modify_employee_config": False,
            "can_auto_execute": False,
        },
    }


def build_growth_cards(db: Session, stats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards = []
    for row in sorted(stats, key=lambda item: (item["failed_task_count"], item["risk_count"], item["completed_task_count"]), reverse=True)[:5]:
        report = build_employee_growth_report(db, row["employee_code"], persist_knowledge=False)
        cards.append(
            {
                "employee_code": row["employee_code"],
                "employee_name": row["employee_name"],
                "success_rate": row["success_rate"],
                "risk_count": row["risk_count"],
                "tianbrain_next_optimization": report["tianbrain_analysis"]["next_optimization"][:3],
                "tiancang_sop_suggestions": report["tiancang_distillation"]["sop_suggestions"][:2],
                "can_auto_apply": False,
            }
        )
    return cards


def overall_success_rate(stats: list[dict[str, Any]]) -> float:
    completed = sum(row["completed_task_count"] for row in stats)
    failed = sum(row["failed_task_count"] for row in stats)
    total = completed + failed
    return round(completed / total, 4) if total else 0


def cost_summary(stats: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(float(row["estimated_cost"]["estimated_total"]) for row in stats)
    return {
        "unit": "mock_cost_unit",
        "estimated_total": round(total, 2),
        "calculation_mode": "readonly_estimate",
        "can_auto_spend_money": False,
    }


def board_suggestions(stats: list[dict[str, Any]], leaderboard: dict[str, Any]) -> list[str]:
    suggestions = []
    risk_employee = leaderboard.get("risk_employee")
    growth_employee = leaderboard.get("growth_employee")
    if risk_employee and risk_employee["risk_count"] > 0:
        suggestions.append(f"{risk_employee['employee_name']} 风险次数较高，建议优先复盘审批材料。")
    if growth_employee and growth_employee["growth_score"] > 0:
        suggestions.append(f"{growth_employee['employee_name']} 有明显成长样本，建议沉淀 SOP。")
    if any(row["failed_task_count"] for row in stats):
        suggestions.append("失败任务需要进入 Employee Growth Center 形成优化建议。")
    return suggestions or ["当前样本较少，建议继续积累任务数据。"]
