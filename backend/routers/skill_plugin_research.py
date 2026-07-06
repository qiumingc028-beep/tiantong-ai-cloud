from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from .skill_plugin_research_data import CANDIDATES, COST_LEVELS, NEXT_UPGRADES, RISK_LEVELS


router = APIRouter()

PRIVILEGED_ROLES = {"owner", "admin"}


def require_research_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in PRIVILEGED_ROLES:
        raise HTTPException(status_code=403, detail="no skill plugin research permission")
    return user


def not_found(kind: str, code: str):
    raise HTTPException(status_code=404, detail={"error": "not_found", "kind": kind, "code": code})


def candidates_by_type(candidate_type: str) -> list[dict]:
    return [candidate for candidate in CANDIDATES if candidate["candidate_type"] == candidate_type]


def employee_bindings() -> list[dict]:
    employees: dict[str, dict[str, set[str]]] = {}
    for candidate in CANDIDATES:
        code = candidate["target_employee"]
        data = employees.setdefault(
            code,
            {
                "recommended_candidates": set(),
                "candidate_types": set(),
                "risk_levels": set(),
                "approval_required_candidates": set(),
                "forbidden_candidates": set(),
                "next_step_suggestions": set(),
            },
        )
        data["recommended_candidates"].add(candidate["candidate_code"])
        data["candidate_types"].add(candidate["candidate_type"])
        data["risk_levels"].add(candidate["risk_level"])
        data["next_step_suggestions"].add(candidate["next_step_suggestion"])
        if candidate["approval_required"]:
            data["approval_required_candidates"].add(candidate["candidate_code"])
        if candidate["recommended_stage"] == "blocked" or candidate["permission_level"] == "forbidden":
            data["forbidden_candidates"].add(candidate["candidate_code"])
    return [
        {
            "employee_code": code,
            "recommended_candidates": sorted(values["recommended_candidates"]),
            "candidate_types": sorted(values["candidate_types"]),
            "risk_levels": sorted(values["risk_levels"]),
            "approval_required_candidates": sorted(values["approval_required_candidates"]),
            "forbidden_candidates": sorted(values["forbidden_candidates"]),
            "next_step_suggestions": sorted(values["next_step_suggestions"]),
            "can_auto_execute": False,
        }
        for code, values in sorted(employees.items())
    ]


def department_bindings() -> list[dict]:
    departments: dict[str, dict[str, set[str]]] = {}
    for candidate in CANDIDATES:
        department = candidate["target_department"]
        data = departments.setdefault(
            department,
            {
                "recommended_candidates": set(),
                "candidate_types": set(),
                "risk_levels": set(),
                "approval_required_candidates": set(),
                "forbidden_candidates": set(),
            },
        )
        data["recommended_candidates"].add(candidate["candidate_code"])
        data["candidate_types"].add(candidate["candidate_type"])
        data["risk_levels"].add(candidate["risk_level"])
        if candidate["approval_required"]:
            data["approval_required_candidates"].add(candidate["candidate_code"])
        if candidate["recommended_stage"] == "blocked" or candidate["permission_level"] == "forbidden":
            data["forbidden_candidates"].add(candidate["candidate_code"])
    return [
        {
            "department": department,
            "recommended_candidates": sorted(values["recommended_candidates"]),
            "candidate_types": sorted(values["candidate_types"]),
            "risk_levels": sorted(values["risk_levels"]),
            "approval_required_candidates": sorted(values["approval_required_candidates"]),
            "forbidden_candidates": sorted(values["forbidden_candidates"]),
            "can_auto_execute": False,
        }
        for department, values in sorted(departments.items())
    ]


def approval_suggestions() -> list[dict]:
    rows = []
    for candidate in CANDIDATES:
        rows.append(
            {
                "candidate_code": candidate["candidate_code"],
                "candidate_name": candidate["candidate_name"],
                "approval_status": "requires_boss_review" if candidate["approval_required"] else "research_only",
                "approval_reason": "需要老板确认风险、成本和下一阶段范围。" if candidate["approval_required"] else "可继续只读研究。",
                "required_reviewers": ["boss", "tianjian_audit"] if candidate["approval_required"] else ["tiandao"],
                "next_step_suggestion": candidate["next_step_suggestion"],
                "can_auto_execute": False,
            }
        )
    return rows


def forbidden_list() -> list[dict]:
    return [
        {
            "candidate_code": candidate["candidate_code"],
            "candidate_name": candidate["candidate_name"],
            "forbidden_reason": "当前阶段禁止接入或禁止自动化。",
            "risk_level": candidate["risk_level"],
            "forbidden_actions": candidate["forbidden_actions"],
            "can_auto_execute": False,
        }
        for candidate in CANDIDATES
        if candidate["recommended_stage"] == "blocked" or candidate["permission_level"] == "forbidden"
    ]


def sprint16_candidates() -> list[dict]:
    return [
        {
            "candidate_code": candidate["candidate_code"],
            "candidate_name": candidate["candidate_name"],
            "candidate_type": candidate["candidate_type"],
            "recommended_reason": candidate["use_case"],
            "required_preconditions": ["boss_confirmation", "test_acceptance", "security_audit"],
            "can_auto_execute": False,
        }
        for candidate in CANDIDATES
        if candidate["recommended_stage"] == "sprint16_candidate"
    ]


@router.get("/overview")
def get_skill_plugin_research_overview(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    return {
        "total_candidates": len(CANDIDATES),
        "skill_candidates": len(candidates_by_type("skill")),
        "plugin_candidates": len(candidates_by_type("plugin")),
        "mcp_candidates": len(candidates_by_type("mcp")),
        "external_tool_candidates": len(candidates_by_type("external_tool")),
        "high_risk_candidates": sum(1 for row in CANDIDATES if row["risk_level"] == "high"),
        "critical_risk_candidates": sum(1 for row in CANDIDATES if row["risk_level"] == "critical"),
        "boss_confirmation_required_count": sum(1 for row in CANDIDATES if row["requires_boss_confirmation"]),
        "sprint16_candidate_count": len(sprint16_candidates()),
        "forbidden_candidate_count": len(forbidden_list()),
        "safe_readonly_mode": True,
        "all_auto_actions_disabled": True,
    }


@router.get("/candidates")
def get_skill_plugin_research_candidates(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    return {"candidates": CANDIDATES}


@router.get("/candidates/{id}")
def get_skill_plugin_research_candidate(id: str, request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    candidate = next((row for row in CANDIDATES if row["candidate_code"] == id), None)
    if not candidate:
        not_found("candidate", id)
    return candidate


@router.get("/skills")
def get_skill_plugin_research_skills(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    return {"candidates": candidates_by_type("skill")}


@router.get("/plugins")
def get_skill_plugin_research_plugins(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    return {"candidates": candidates_by_type("plugin")}


@router.get("/mcps")
def get_skill_plugin_research_mcps(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    return {"candidates": candidates_by_type("mcp")}


@router.get("/external-tools")
def get_skill_plugin_research_external_tools(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    return {"candidates": candidates_by_type("external_tool")}


@router.get("/employees")
def get_skill_plugin_research_employees(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    return {"employees": employee_bindings()}


@router.get("/departments")
def get_skill_plugin_research_departments(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    return {"departments": department_bindings()}


@router.get("/risk-levels")
def get_skill_plugin_research_risk_levels(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    return {"risk_levels": RISK_LEVELS}


@router.get("/cost-levels")
def get_skill_plugin_research_cost_levels(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    return {"cost_levels": COST_LEVELS}


@router.get("/approval-suggestions")
def get_skill_plugin_research_approval_suggestions(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    return {"approval_suggestions": approval_suggestions()}


@router.get("/forbidden-list")
def get_skill_plugin_research_forbidden_list(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    return {"forbidden_list": forbidden_list()}


@router.get("/sprint16-candidates")
def get_skill_plugin_research_sprint16_candidates(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    return {"sprint16_candidates": sprint16_candidates()}


@router.get("/next-upgrades")
def get_skill_plugin_research_next_upgrades(request: Request, db: Session = Depends(get_db)):
    require_research_user(request, db)
    return {"next_upgrades": NEXT_UPGRADES}
