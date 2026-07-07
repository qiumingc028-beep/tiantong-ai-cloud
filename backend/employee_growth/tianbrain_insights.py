from __future__ import annotations

from typing import Any

from backend.learning_center import analyze_execution, optimize_prompt_suggestions, score_employees
from backend.security.tian_brain.risk_predictor import predict_risk


def analyze_growth_with_tianbrain(growth_profile: dict[str, Any]) -> dict[str, Any]:
    logs = growth_profile.get("learning_logs") if isinstance(growth_profile.get("learning_logs"), list) else []
    execution = {
        "goal": f"{growth_profile.get('employee_code', 'unknown')} 长期成长复盘",
        "logs": logs,
    }
    execution_analysis = analyze_execution(execution)
    employee_scores = score_employees(logs)
    prompt_optimization = optimize_prompt_suggestions(execution_analysis, employee_scores, logs)
    risk_prediction = predict_risk(
        {
            "source": "employee_growth",
            "target": "tianbrain",
            "action": "analyze_employee_growth",
            "payload": {
                "employee_code": growth_profile.get("employee_code"),
                "risk_records": growth_profile.get("risk_records"),
                "suggestion_only": True,
                "can_auto_modify_production_rule": False,
                "can_auto_expand_permission": False,
            },
        },
        {"source": "employee_growth", "target": "tianbrain", "handler": "growth_review"},
    )
    return {
        "center": "TianBrain",
        "success_analysis": why_success(growth_profile, execution_analysis),
        "failure_analysis": why_failed(growth_profile, execution_analysis),
        "next_optimization": next_optimization(growth_profile, execution_analysis, prompt_optimization),
        "execution_analysis": execution_analysis,
        "employee_scores": employee_scores,
        "prompt_optimization": prompt_optimization,
        "risk_prediction": risk_prediction,
        "safety": {
            "suggestion_only": True,
            "can_auto_modify_production_rule": False,
            "can_auto_expand_permission": False,
            "requires_tian_shen_approval_for_rule_change": True,
        },
    }


def why_success(growth_profile: dict[str, Any], execution_analysis: dict[str, Any]) -> list[str]:
    if growth_profile.get("completed_task_count", 0) <= 0:
        return ["暂无成功任务样本，暂不形成成功归因。"]
    reasons = execution_analysis.get("success_reasons") or []
    return reasons + ["成功经验应沉淀到 TianCang，用于后续 SOP 和最佳实践。"]


def why_failed(growth_profile: dict[str, Any], execution_analysis: dict[str, Any]) -> list[str]:
    if growth_profile.get("failed_task_count", 0) <= 0:
        return ["暂无失败任务样本。"]
    reasons = execution_analysis.get("failure_reasons") or growth_profile.get("failure_reasons") or []
    return reasons + ["失败原因应转化为下次任务的输入检查、风险检查和验收规则。"]


def next_optimization(
    growth_profile: dict[str, Any],
    execution_analysis: dict[str, Any],
    prompt_optimization: dict[str, Any],
) -> list[dict[str, Any]]:
    suggestions = [
        {
            "target": "task_input",
            "suggestion": "执行前补齐目标、输入、输出格式、验收标准和风险边界。",
            "can_auto_apply": False,
            "requires_tian_shen_approval": False,
        }
    ]
    if growth_profile.get("failed_task_count", 0):
        suggestions.append(
            {
                "target": "failure_prevention",
                "suggestion": "将失败原因加入任务前置检查清单。",
                "can_auto_apply": False,
                "requires_tian_shen_approval": True,
            }
        )
    if growth_profile.get("risk_records"):
        suggestions.append(
            {
                "target": "risk_control",
                "suggestion": "高风险任务必须先生成 TianShen 审批材料，不允许直接执行。",
                "can_auto_apply": False,
                "requires_tian_shen_approval": True,
            }
        )
    for row in prompt_optimization.get("optimization_suggestions") or []:
        suggestions.append(
            {
                "target": "prompt",
                "suggestion": row.get("title") or "Prompt 优化建议",
                "can_auto_apply": False,
                "requires_tian_shen_approval": True,
            }
        )
    return suggestions
