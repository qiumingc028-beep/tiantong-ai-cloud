from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.ai_employees.registry import AI_EMPLOYEE_REGISTRY
from backend.employee_capability import get_employee_profile
from backend.employee_growth import build_employee_growth_report
from backend.employee_organization import build_employee_organization_center
from backend.employee_performance import build_ai_employee_business_board, build_employee_performance_stats
from backend.employee_workspace.task_linkage import build_task_linkage
from backend.models import AiEmployee, TaskCenterTask
from backend.security.tian_brain.risk_predictor import predict_risk


CORE_ORG_CHILDREN = [
    ("tiangong", "天工（架构）", "研发交付军团", ["architecture_design", "system_planning"]),
    ("tianwang", "天王（后端）", "研发交付军团", ["backend_development", "api_design"]),
    ("tianyan_frontend", "天颜（前端）", "研发交付军团", ["frontend_integration", "ui_quality"]),
    ("tianjian_test", "天检（测试）", "质量验收军团", ["quality_acceptance", "regression_check"]),
    ("tiandun_ops", "天盾（部署）", "部署运维军团", ["ops_safety", "deploy_review"]),
    ("tianjian_audit", "天监（审计）", "质量验收军团", ["security_audit", "risk_review"]),
    ("tiancai_data", "天采（数据）", "数据资产军团", ["data_collection", "business_monitoring"]),
    ("tiancang", "天藏（知识）", "知识资产军团", ["knowledge_storage", "case_search"]),
]


def build_employee_command_dashboard(db: Session) -> dict[str, Any]:
    stats = build_employee_performance_stats(db)
    organization = build_employee_organization_center(db)
    performance_board = build_ai_employee_business_board(db)
    task_rows = db.query(TaskCenterTask).order_by(TaskCenterTask.id.desc()).limit(500).all()
    summary = build_overview_summary(stats, task_rows)
    organization_view = build_organization_view(db, organization)
    details = [build_employee_detail(db, row["employee_code"], raise_missing=False) for row in stats]
    return {
        "center": "AI Employee Command Dashboard",
        "mode": "readonly_command_dashboard",
        "overview": summary,
        "organization_view": organization_view,
        "employee_details": details,
        "ceo_dashboard_connection": {
            "source": "CEO Dashboard",
            "business_board": performance_board,
        },
        "workspace_connection": {
            "source": "Employee Workspace",
            "detail_count": len(details),
            "can_auto_execute_task": False,
        },
        "tianbrain_connection": build_tianbrain_dashboard_signal(summary),
        "tianshen_connection": {
            "source": "TianShen Approval Center",
            "pending_approval_tasks": summary["pending_approval_tasks"],
            "high_risk_requires_approval": True,
            "can_auto_approve": False,
        },
        "safety": {
            "readonly": True,
            "can_auto_modify_permission": False,
            "can_auto_create_employee": False,
            "can_auto_execute_task": False,
        },
    }


def build_overview_summary(stats: list[dict[str, Any]], tasks: list[TaskCenterTask]) -> dict[str, Any]:
    active_employees = [row for row in stats if row["status"] == "active"]
    running_tasks = [task for task in tasks if task.status in {"running", "in_progress"}]
    risk_tasks = [task for task in tasks if task_requires_approval(task)]
    pending_approval = [task for task in tasks if task.status in {"created", "result_submitted", "accepted"} or task_requires_approval(task)]
    completed = sum(row["completed_task_count"] for row in stats)
    failed = sum(row["failed_task_count"] for row in stats)
    total_finished = completed + failed
    return {
        "total_ai_employees": len(stats),
        "online_employees": len(active_employees),
        "executing_task_count": len(running_tasks),
        "success_rate": round(completed / total_finished, 4) if total_finished else 0,
        "risk_count": len(risk_tasks),
        "pending_approval_tasks": len(pending_approval),
        "can_auto_execute_task": False,
        "can_auto_modify_permission": False,
    }


def build_organization_view(db: Session, organization: dict[str, Any]) -> dict[str, Any]:
    db_employees = {
        employee.employee_code: employee
        for employee in db.query(AiEmployee).filter(AiEmployee.is_legacy.is_(False)).all()
    }
    root = employee_node("tiantong", db_employees)
    children = [employee_node(code, db_employees, label, department, tags) for code, label, department, tags in CORE_ORG_CHILDREN]
    known = {child["employee_code"] for child in children} | {"tiantong"}
    for relationship in organization.get("employee_relationships") or []:
        code = relationship["employee_code"]
        if code not in known:
            children.append(employee_node(code, db_employees))
            known.add(code)
    root["children"] = children
    return {
        "root": root,
        "tree_text": build_tree_text(root),
        "relationships": organization.get("employee_relationships") or [],
        "departments": organization.get("departments") or [],
        "supports": ["查看上下级", "查看负责人", "查看能力标签"],
        "safety": {
            "readonly_tree": True,
            "can_auto_change_manager": False,
            "can_auto_create_employee": False,
        },
    }


def build_employee_detail(db: Session, employee_code: str, raise_missing: bool = True) -> dict[str, Any]:
    employee = db.query(AiEmployee).filter(AiEmployee.employee_code == employee_code).first()
    registry_profile = AI_EMPLOYEE_REGISTRY.get(employee_code)
    if not employee and not registry_profile and raise_missing:
        raise HTTPException(status_code=404, detail="employee not found")
    profile = get_employee_profile(employee_code)
    task_linkage = build_task_linkage(db, employee_code)
    growth = build_employee_growth_report(db, employee_code, persist_knowledge=False)
    completed = growth["growth_profile"]["completed_task_count"]
    failed = growth["growth_profile"]["failed_task_count"]
    current_level = capability_level(completed, growth["growth_profile"]["success_rate"], growth["growth_profile"]["risk_records"])
    return {
        "identity": {
            "employee_code": employee_code,
            "employee_name": employee.employee_name if employee else profile["employee_name"],
            "department": employee.legion if employee else profile["department"],
            "status": employee.status if employee else "planned",
            "duty": employee.duty if employee else "",
        },
        "skills": profile.get("skills") or [],
        "capability_tags": profile.get("capability_tags") or [],
        "completed_tasks": completed,
        "success_rate": growth["growth_profile"]["success_rate"],
        "failure_records": growth["growth_profile"]["failure_reasons"],
        "learning_records": {
            "skill_growth": growth["growth_profile"]["skill_growth"],
            "tianbrain_next_optimization": growth["tianbrain_analysis"]["next_optimization"][:3],
            "tiancang_sop_suggestions": growth["tiancang_distillation"]["sop_suggestions"][:2],
        },
        "current_capability_level": current_level,
        "current_task": task_linkage["current_task"],
        "safety": {
            "readonly_detail": True,
            "can_auto_modify_permission": False,
            "can_auto_create_employee": False,
            "can_auto_execute_task": False,
            "high_risk_requires_tian_shen": True,
        },
        "metrics": {
            "failed_task_count": failed,
            "risk_count": len(growth["growth_profile"]["risk_records"]),
        },
    }


def employee_node(
    employee_code: str,
    db_employees: dict[str, AiEmployee],
    fallback_name: str | None = None,
    fallback_department: str | None = None,
    fallback_tags: list[str] | None = None,
) -> dict[str, Any]:
    employee = db_employees.get(employee_code)
    profile = get_employee_profile(employee_code)
    return {
        "employee_code": employee_code,
        "employee_name": employee.employee_name if employee else fallback_name or profile["employee_name"],
        "department": employee.legion if employee else fallback_department or profile["department"],
        "capability_tags": profile.get("capability_tags") if employee_code in AI_EMPLOYEE_REGISTRY else fallback_tags or profile.get("capability_tags") or [],
        "is_planned_node": employee is None,
        "children": [],
    }


def build_tree_text(root: dict[str, Any]) -> list[str]:
    lines = [root["employee_name"]]
    for index, child in enumerate(root.get("children") or []):
        prefix = "└──" if index == len(root["children"]) - 1 else "├──"
        lines.append(f"{prefix} {child['employee_name']}")
    return lines


def task_requires_approval(task: TaskCenterTask) -> bool:
    text = f"{task.title} {task.description or ''}".lower()
    return any(keyword in text for keyword in ["deploy", "部署", "git push", "权限", "花钱", "预算", "广告"])


def capability_level(completed: int, success_rate: float, risk_records: list[dict[str, Any]]) -> str:
    if risk_records:
        return "risk_control_required"
    if completed >= 5 and success_rate >= 0.9:
        return "senior"
    if completed >= 1 and success_rate >= 0.5:
        return "growing"
    return "new"


def build_tianbrain_dashboard_signal(summary: dict[str, Any]) -> dict[str, Any]:
    prediction = predict_risk(
        {
            "source": "employee_command_dashboard",
            "target": "tianbrain",
            "action": "analyze_employee_command_dashboard",
            "payload": {
                "risk_count": summary["risk_count"],
                "pending_approval_tasks": summary["pending_approval_tasks"],
                "readonly": True,
                "can_auto_execute_task": False,
                "can_auto_modify_permission": False,
            },
        },
        {"source": "employee_command_dashboard", "target": "tianbrain", "handler": "dashboard_review"},
    )
    return {
        "source": "TianBrain",
        "risk_prediction": prediction,
        "optimization_mode": "suggestion_only",
        "can_auto_apply": False,
    }
