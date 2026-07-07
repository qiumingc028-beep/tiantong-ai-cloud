from __future__ import annotations

from typing import Any

from backend.knowledge_center import search_knowledge
from backend.security.tian_shen import evaluate_command
from backend.workflow.router import route_event

from .employee_profile import list_employee_profiles
from .skill_registry import get_skill, list_skills


TASK_KEYWORDS = {
    "sales_decline": ["销量下降", "sales_decline", "销售下降"],
    "conversion_decline": ["转化下降", "conversion_decline", "转化"],
    "ad_anomaly": ["广告异常", "ad_anomaly", "投放", "roi"],
    "product_issue": ["商品问题", "product_issue", "商品", "详情页"],
    "learning": ["复盘", "学习", "sop", "prompt"],
    "deploy": ["部署", "上线", "deploy"],
}


TASK_SKILLS = {
    "sales_decline": ["data_collection", "strategy_planning", "ecommerce_operation", "quality_acceptance"],
    "conversion_decline": ["data_collection", "strategy_planning", "ecommerce_operation", "ad_performance_check", "quality_acceptance"],
    "ad_anomaly": ["data_collection", "ad_performance_check", "strategy_planning", "quality_acceptance"],
    "product_issue": ["data_collection", "ecommerce_operation", "strategy_planning", "quality_acceptance"],
    "learning": ["knowledge_learning", "strategy_planning", "quality_acceptance"],
    "deploy": ["security_approval", "quality_acceptance"],
}


def match_employee_for_task(task: dict[str, Any]) -> dict[str, Any]:
    normalized = task if isinstance(task, dict) else {}
    task_type = infer_task_type(normalized)
    required_skills = TASK_SKILLS.get(task_type, ["strategy_planning", "quality_acceptance"])
    profiles = list_employee_profiles(normalized.get("history") if isinstance(normalized.get("history"), dict) else None)
    candidates = [score_employee(profile, required_skills, normalized, task_type) for profile in profiles]
    ranked = sorted(candidates, key=lambda row: row["match_score"], reverse=True)
    best = ranked[0] if ranked else {}
    approval = approval_preview(task_type, required_skills, best, normalized)
    knowledge = search_knowledge(str(normalized.get("goal") or normalized.get("task") or task_type), limit=3)
    return {
        "task_type": task_type,
        "required_skills": required_skills,
        "best_employee": best,
        "ranked_candidates": ranked,
        "assigned_agents": [row["employee_code"] for row in ranked[: min(3, len(ranked))]],
        "knowledge_references": knowledge["matches"],
        "approval_gate": approval,
        "safety": {
            "recommendation_only": True,
            "can_auto_assign": False,
            "can_expand_permission": False,
            "requires_tian_shen_for_high_risk_skill": any((get_skill(skill) or {}).get("requires_tian_shen_approval") for skill in required_skills),
        },
    }


def infer_task_type(task: dict[str, Any]) -> str:
    explicit = task.get("task_type") or task.get("type")
    if explicit:
        return str(explicit)
    text = f"{task.get('goal', '')} {task.get('task', '')} {task.get('description', '')}".lower()
    for task_type, keywords in TASK_KEYWORDS.items():
        if any(keyword.lower() in text for keyword in keywords):
            return task_type
    return "business_strategy"


def score_employee(profile: dict[str, Any], required_skills: list[str], task: dict[str, Any], task_type: str) -> dict[str, Any]:
    employee_skills = set(profile.get("skills") or [])
    matched_skills = [skill for skill in required_skills if skill in employee_skills]
    performance = profile.get("historical_performance") or {}
    skill_score = len(matched_skills) / len(required_skills) if required_skills else 0
    completion = float(performance.get("completion_rate") or 0)
    accuracy = float(performance.get("accuracy_rate") or 0)
    risk_penalty = float(performance.get("risk_rate") or 0)
    efficiency = float(performance.get("efficiency") or 0)
    focus_bonus = task_focus_bonus(task_type, employee_skills)
    match_score = round(skill_score * 55 + focus_bonus + completion * 15 + accuracy * 15 + efficiency * 10 - risk_penalty * 20, 2)
    return {
        "employee_code": profile["employee_code"],
        "employee_name": profile["employee_name"],
        "department": profile["department"],
        "matched_skills": matched_skills,
        "missing_skills": [skill for skill in required_skills if skill not in employee_skills],
        "capability_tags": profile.get("capability_tags") or [],
        "permissions": profile.get("permissions") or [],
        "historical_performance": performance,
        "match_score": match_score,
        "recommended_role": recommended_role(profile, task_type),
        "can_expand_permission": False,
    }


def recommended_role(profile: dict[str, Any], task_type: str) -> str:
    if task_type == "ad_anomaly" and "ad_performance_check" in profile.get("skills", []):
        return "广告异常检查负责人"
    if "data_collection" in profile.get("skills", []):
        return "数据证据负责人"
    if "strategy_planning" in profile.get("skills", []):
        return "策略分析负责人"
    if "quality_acceptance" in profile.get("skills", []):
        return "验收验证负责人"
    return "协作成员"


def task_focus_bonus(task_type: str, employee_skills: set[str]) -> int:
    focus_skills = {
        "product_issue": "ecommerce_operation",
        "conversion_decline": "ecommerce_operation",
        "ad_anomaly": "ad_performance_check",
        "learning": "knowledge_learning",
        "deploy": "security_approval",
    }
    focus = focus_skills.get(task_type)
    if not focus or focus not in employee_skills:
        return 0
    return 45 if task_type in {"ad_anomaly", "deploy"} else 18


def approval_preview(task_type: str, required_skills: list[str], best: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    high_risk_skills = [skill for skill in required_skills if (get_skill(skill) or {}).get("requires_tian_shen_approval")]
    event = {
        "source": "employee_capability_center",
        "target": best.get("employee_code") or "orchestrator",
        "action": "recommend_employee",
        "requires_boss_confirmation": bool(high_risk_skills),
        "payload": {
            "task_type": task_type,
            "goal": task.get("goal") or task.get("task"),
            "recommended_employee": best.get("employee_code"),
            "high_risk_skills": high_risk_skills,
            "recommendation_only": True,
            "can_auto_assign": False,
            "can_expand_permission": False,
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
