from __future__ import annotations

from typing import Any

from backend.knowledge_center import learn_from_execution


def distill_growth_knowledge(
    growth_profile: dict[str, Any],
    tianbrain_analysis: dict[str, Any],
    persist: bool = False,
) -> dict[str, Any]:
    report = build_learning_report(growth_profile, tianbrain_analysis)
    knowledge = learn_from_execution(report) if persist else preview_knowledge(report)
    return {
        "center": "TianCang Knowledge Center",
        "mode": "append_only" if persist else "preview_only",
        "knowledge": knowledge,
        "best_practices": best_practices(growth_profile, tianbrain_analysis),
        "sop_suggestions": sop_suggestions(growth_profile),
        "prompt_optimization_rules": prompt_rules(tianbrain_analysis),
        "experience_rules": experience_rules(growth_profile),
        "safety": {
            "append_only": True,
            "can_auto_modify_production_rule": False,
            "can_auto_modify_prompt": False,
            "can_auto_expand_permission": False,
            "requires_tian_shen_approval_for_rule_change": True,
        },
    }


def build_learning_report(growth_profile: dict[str, Any], tianbrain_analysis: dict[str, Any]) -> dict[str, Any]:
    execution_analysis = tianbrain_analysis.get("execution_analysis") or {}
    return {
        "center": "AI Employee Growth Center",
        "analysis": {
            **execution_analysis,
            "goal": execution_analysis.get("goal") or f"{growth_profile.get('employee_code', 'unknown')} 成长复盘",
            "success_reasons": tianbrain_analysis.get("success_analysis") or [],
            "failure_reasons": tianbrain_analysis.get("failure_analysis") or [],
            "learning_loop": ["profile", "execution", "tianbrain_analysis", "tiancang_memory", "suggestion", "next_task"],
        },
        "employee_scores": tianbrain_analysis.get("employee_scores") or [],
        "prompt_optimization": tianbrain_analysis.get("prompt_optimization") or {},
    }


def preview_knowledge(report: dict[str, Any]) -> dict[str, Any]:
    analysis = report.get("analysis") or {}
    return {
        "center": "TianCang Knowledge Center",
        "mode": "preview_only",
        "would_generate": ["execution_case", "sop", "best_practice_or_failure_case", "experience_rule", "prompt_version"],
        "goal": analysis.get("goal"),
        "can_auto_store": False,
        "can_auto_modify_production_rule": False,
        "can_auto_modify_prompt": False,
    }


def best_practices(growth_profile: dict[str, Any], tianbrain_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    if growth_profile.get("completed_task_count", 0) <= 0:
        return []
    return [
        {
            "title": "成功任务复盘为最佳实践",
            "summary": "保留成功任务的输入、输出、风险检查和验收条件。",
            "source": "employee_growth",
            "can_auto_apply": False,
        }
    ]


def sop_suggestions(growth_profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "sop_code": f"{growth_profile.get('employee_code', 'employee')}_growth_review_sop",
            "title": "AI员工成长复盘 SOP",
            "steps": ["统计任务", "分析成功失败", "识别风险", "生成优化建议", "提交人工审批"],
            "can_auto_publish": False,
        }
    ]


def prompt_rules(tianbrain_analysis: dict[str, Any]) -> list[dict[str, Any]]:
    prompt = tianbrain_analysis.get("prompt_optimization") or {}
    return [
        {
            "rule": row.get("title") or "Prompt 优化建议",
            "reason": row.get("reason") or "来自 TianBrain 成长复盘。",
            "can_auto_apply": False,
            "requires_tian_shen_approval": True,
        }
        for row in prompt.get("optimization_suggestions") or []
    ]


def experience_rules(growth_profile: dict[str, Any]) -> list[dict[str, Any]]:
    rules = [
        {
            "rule": "所有任务都必须记录输入、输出、验收结果和风险决策。",
            "can_auto_apply": False,
        }
    ]
    if growth_profile.get("risk_records"):
        rules.append(
            {
                "rule": "涉及部署、权限、预算、广告或代码提交的任务必须经过 TianShen。",
                "can_auto_apply": False,
            }
        )
    return rules
