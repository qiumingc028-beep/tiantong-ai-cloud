from __future__ import annotations

from typing import Any

from backend.security.tian_shen import evaluate_command
from backend.workflow.router import route_event

from .knowledge_storage import save_many


def learn_from_execution(learning_report: dict[str, Any]) -> dict[str, Any]:
    report = learning_report if isinstance(learning_report, dict) else {}
    entries = build_knowledge_entries(report)
    stored = save_many(entries)
    approval_gate = knowledge_approval_preview(report, stored)
    return {
        "center": "TianCang Knowledge Center",
        "mode": "long_term_memory_append_only",
        "stored_knowledge": stored,
        "generated_sop": [row for row in stored if row.get("knowledge_type") == "sop"],
        "best_practices": [row for row in stored if row.get("knowledge_type") == "best_practice"],
        "experience_rules": [row for row in stored if row.get("knowledge_type") == "experience_rule"],
        "approval_gate": approval_gate,
        "safety": {
            "append_only": True,
            "can_auto_modify_production_rule": False,
            "can_auto_modify_prompt": False,
            "requires_tian_shen_approval_for_prompt_update": True,
        },
    }


def build_knowledge_entries(report: dict[str, Any]) -> list[dict[str, Any]]:
    analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
    prompt_optimization = report.get("prompt_optimization") if isinstance(report.get("prompt_optimization"), dict) else {}
    employee_scores = report.get("employee_scores") if isinstance(report.get("employee_scores"), list) else []
    goal = analysis.get("goal") or report.get("goal") or "执行复盘"
    status = analysis.get("status") or "unknown"
    entries = [
        {
            "knowledge_type": "execution_case",
            "title": f"{goal} 执行案例",
            "summary": analysis.get("result_summary") or "执行案例复盘",
            "content": {"analysis": analysis, "employee_scores": employee_scores},
            "tags": ["execution_case", status],
        },
        {
            "knowledge_type": "sop",
            "title": f"{goal} 复盘 SOP",
            "summary": "按任务、执行、评价、学习、优化、下一次执行沉淀 SOP。",
            "content": {"steps": analysis.get("learning_loop") or []},
            "tags": ["sop", "learning_loop"],
        },
        {
            "knowledge_type": "best_practice" if status == "success" else "failure_case",
            "title": f"{goal} {'成功经验' if status == 'success' else '失败案例'}",
            "summary": "; ".join((analysis.get("success_reasons") if status == "success" else analysis.get("failure_reasons")) or []),
            "content": {"status": status, "reasons": analysis.get("success_reasons") if status == "success" else analysis.get("failure_reasons")},
            "tags": ["best_practice" if status == "success" else "failure_case", status],
        },
        {
            "knowledge_type": "experience_rule",
            "title": f"{goal} 经验规则",
            "summary": "执行前必须明确输入、输出、风险和验收标准。",
            "content": {"rule": "每个 AI 员工输出必须包含依据、风险、下一步和验收条件。"},
            "tags": ["experience_rule", "tianwu"],
        },
    ]
    for suggestion in prompt_optimization.get("optimization_suggestions") or []:
        entries.append(
            {
                "knowledge_type": "prompt_version",
                "title": suggestion.get("title") or "Prompt 优化建议",
                "summary": suggestion.get("reason") or "来自天悟复盘的 Prompt 优化建议",
                "content": {"suggestion": suggestion, "apply_mode": "approval_required"},
                "tags": ["prompt_version", "suggestion_only"],
            }
        )
    return entries


def knowledge_approval_preview(report: dict[str, Any], stored: list[dict[str, Any]]) -> dict[str, Any]:
    event = {
        "source": "knowledge_center",
        "target": "orchestrator",
        "action": "review_knowledge_learning",
        "requires_boss_confirmation": True,
        "payload": {
            "knowledge_count": len(stored),
            "review_only": True,
            "append_only": True,
            "can_auto_modify_prompt": False,
            "can_auto_modify_production_rule": False,
            "goal": (report.get("analysis") or {}).get("goal") if isinstance(report.get("analysis"), dict) else report.get("goal"),
        },
    }
    route = route_event(event)
    return evaluate_command(
        event,
        {
            "source": route.source,
            "target": route.target,
            "handler": route.handler,
            "queue_required": route.queue_required,
        },
    )
