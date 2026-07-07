from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .growth_profile import build_employee_growth_profile
from .knowledge_distillation import distill_growth_knowledge
from .tianbrain_insights import analyze_growth_with_tianbrain


def build_employee_growth_report(db: Session, employee_code: str, persist_knowledge: bool = False) -> dict[str, Any]:
    profile = build_employee_growth_profile(db, employee_code)
    tianbrain = analyze_growth_with_tianbrain(profile)
    tiancang = distill_growth_knowledge(profile, tianbrain, persist=persist_knowledge)
    return {
        "center": "AI Employee Growth Center",
        "employee_code": employee_code,
        "growth_profile": profile,
        "tianbrain_analysis": tianbrain,
        "tiancang_distillation": tiancang,
        "next_growth_plan": build_next_growth_plan(profile, tianbrain),
        "safety": {
            "suggestion_only": True,
            "can_auto_modify_production_rule": False,
            "can_auto_modify_prompt": False,
            "can_auto_expand_permission": False,
            "can_auto_execute": False,
            "requires_tian_shen_for_rule_change": True,
        },
    }


def build_next_growth_plan(growth_profile: dict[str, Any], tianbrain: dict[str, Any]) -> list[dict[str, Any]]:
    plan = [
        {
            "stage": "next_task",
            "action": "下次任务前补齐输入、输出、风险和验收清单。",
            "can_auto_apply": False,
        }
    ]
    for skill in growth_profile.get("skill_growth", {}).get("suggested_new_skills", []):
        plan.append(
            {
                "stage": "skill_growth",
                "action": f"建议学习技能：{skill}",
                "can_auto_apply": False,
                "can_auto_expand_permission": False,
            }
        )
    if growth_profile.get("risk_records"):
        plan.append(
            {
                "stage": "risk_review",
                "action": "高风险任务必须先准备 TianShen 审批材料。",
                "can_auto_apply": False,
                "requires_tian_shen_approval": True,
            }
        )
    for suggestion in tianbrain.get("next_optimization") or []:
        plan.append(
            {
                "stage": suggestion.get("target") or "optimization",
                "action": suggestion.get("suggestion") or "继续优化执行流程。",
                "can_auto_apply": False,
                "requires_tian_shen_approval": bool(suggestion.get("requires_tian_shen_approval")),
            }
        )
    return plan
