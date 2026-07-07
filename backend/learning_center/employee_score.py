from __future__ import annotations

from collections import defaultdict
from typing import Any

from .execution_analyzer import step_failed, step_success


def score_employees(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in logs:
        groups[str(row.get("employee_code") or "unknown")].append(row)
    return [score_employee(employee_code, rows) for employee_code, rows in sorted(groups.items())]


def score_employee(employee_code: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    completed = sum(1 for row in rows if step_success(row))
    failed = sum(1 for row in rows if step_failed(row))
    risky = sum(1 for row in rows if str(row.get("risk_decision") or "").upper() in {"YELLOW", "RED"})
    completion_rate = completed / total if total else 0
    risk_rate = risky / total if total else 0
    accuracy_rate = max(0, completion_rate - failed * 0.1)
    efficiency = max(0, 1 - failed / total) if total else 0
    overall_score = round((completion_rate * 35 + accuracy_rate * 30 + efficiency * 25 + (1 - risk_rate) * 10), 2)
    return {
        "employee_code": employee_code,
        "total_tasks": total,
        "completion_rate": round(completion_rate, 4),
        "accuracy_rate": round(accuracy_rate, 4),
        "risk_rate": round(risk_rate, 4),
        "efficiency": round(efficiency, 4),
        "overall_score": overall_score,
        "improvement_suggestion": improvement_suggestion(completion_rate, risk_rate, failed),
    }


def improvement_suggestion(completion_rate: float, risk_rate: float, failed: int) -> str:
    if risk_rate > 0:
        return "降低高风险动作，执行前补充 TianShen 审批说明。"
    if failed:
        return "复盘失败步骤，补充输入字段、验收条件和回滚方案。"
    if completion_rate >= 1:
        return "保持当前执行方式，并沉淀为可复用 SOP。"
    return "补充任务上下文，提高完成率。"
