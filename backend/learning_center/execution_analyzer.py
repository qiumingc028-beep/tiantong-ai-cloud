from __future__ import annotations

from typing import Any


def analyze_execution(execution: dict[str, Any]) -> dict[str, Any]:
    normalized = execution if isinstance(execution, dict) else {}
    logs = normalized.get("logs") if isinstance(normalized.get("logs"), list) else []
    goal = normalized.get("goal") or normalized.get("command") or "unknown_goal"
    total_steps = len(logs)
    successful_steps = sum(1 for row in logs if step_success(row))
    failed_steps = sum(1 for row in logs if step_failed(row))
    risk_steps = sum(1 for row in logs if str(row.get("risk_decision") or "").upper() in {"YELLOW", "RED"})
    completion_rate = round(successful_steps / total_steps, 4) if total_steps else 0
    status = "success" if total_steps and failed_steps == 0 else "failed" if failed_steps else "incomplete"
    return {
        "goal": goal,
        "process_summary": summarize_process(logs),
        "result_summary": summarize_result(logs),
        "status": status,
        "total_steps": total_steps,
        "successful_steps": successful_steps,
        "failed_steps": failed_steps,
        "risk_steps": risk_steps,
        "completion_rate": completion_rate,
        "success_reasons": success_reasons(logs),
        "failure_reasons": failure_reasons(logs),
        "learning_loop": ["task", "execution", "evaluation", "learning", "optimization", "next_run"],
        "can_auto_update_prompt": False,
    }


def step_success(row: dict[str, Any]) -> bool:
    return str(row.get("status") or "").lower() in {"completed", "success", "done"}


def step_failed(row: dict[str, Any]) -> bool:
    return str(row.get("status") or "").lower() in {"failed", "error"}


def summarize_process(logs: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "employee_code": str(row.get("employee_code") or "unknown"),
            "role": str(row.get("role") or "unknown"),
            "status": str(row.get("status") or "unknown"),
        }
        for row in logs
    ]


def summarize_result(logs: list[dict[str, Any]]) -> str:
    if not logs:
        return "暂无执行结果，无法形成复盘结论。"
    completed = [row for row in logs if step_success(row)]
    failed = [row for row in logs if step_failed(row)]
    return f"共 {len(logs)} 个步骤，成功 {len(completed)} 个，失败 {len(failed)} 个。"


def success_reasons(logs: list[dict[str, Any]]) -> list[str]:
    reasons = []
    for row in logs:
        if step_success(row):
            reasons.append(f"{row.get('employee_code', 'unknown')} 完成 {row.get('role', 'task')}")
    return reasons or ["暂无明确成功原因"]


def failure_reasons(logs: list[dict[str, Any]]) -> list[str]:
    reasons = []
    for row in logs:
        if step_failed(row):
            reason = row.get("failure_reason") or "未记录失败原因"
            reasons.append(f"{row.get('employee_code', 'unknown')}: {reason}")
    return reasons or ["暂无失败记录"]
