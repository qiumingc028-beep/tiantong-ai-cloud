from __future__ import annotations

from typing import Any


def build_employee_leaderboard(stats: list[dict[str, Any]]) -> dict[str, Any]:
    rows = list(stats)
    return {
        "best_employee": best_employee(rows),
        "growth_employee": growth_employee(rows),
        "risk_employee": risk_employee(rows),
        "ranking": sorted([ranking_row(row) for row in rows], key=lambda item: item["performance_score"], reverse=True),
        "safety": {
            "ranking_only": True,
            "can_auto_reward": False,
            "can_auto_penalize": False,
            "can_auto_adjust_permission": False,
        },
    }


def best_employee(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return ranking_row(max(rows, key=performance_score))


def growth_employee(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return ranking_row(max(rows, key=growth_score))


def risk_employee(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return ranking_row(max(rows, key=lambda row: (row.get("risk_count", 0), row.get("risk_rate", 0), row.get("failed_task_count", 0))))


def ranking_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "employee_code": row["employee_code"],
        "employee_name": row["employee_name"],
        "department": row["department"],
        "completed_task_count": row["completed_task_count"],
        "success_rate": row["success_rate"],
        "failed_task_count": row["failed_task_count"],
        "risk_count": row["risk_count"],
        "performance_score": performance_score(row),
        "growth_score": growth_score(row),
    }


def performance_score(row: dict[str, Any]) -> float:
    success_rate = float(row.get("success_rate") or 0)
    completion_bonus = min(int(row.get("completed_task_count") or 0) * 2, 20)
    failure_penalty = min(int(row.get("failed_task_count") or 0) * 8, 30)
    risk_penalty = min(int(row.get("risk_count") or 0) * 5, 30)
    return round(max(success_rate * 100 + completion_bonus - failure_penalty - risk_penalty, 0), 2)


def growth_score(row: dict[str, Any]) -> float:
    # Growth score highlights employees with useful learning opportunities, not just perfect performers.
    completed = int(row.get("completed_task_count") or 0)
    failed = int(row.get("failed_task_count") or 0)
    risk = int(row.get("risk_count") or 0)
    return round(completed * 2 + failed * 4 + risk * 3, 2)
