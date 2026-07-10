from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..evolution_models import EmployeeGrowth, RiskEvent
from ..models import (
    AiEmployee,
    KnowledgeArticle,
    KnowledgeFile,
    PromptLibrary,
    SopLibrary,
    TaskCenterTask,
)
from ..services.ai_workforce_task_flow import (
    build_employee_task_flow,
    build_task_lifecycle,
    build_waiting_confirm_tasks,
)


router = APIRouter(prefix="/api/ai-workforce")

ALLOWED_ROLES = {"owner", "admin", "boss"}
WORKING_TASK_STATUSES = {"assigned", "running", "in_progress"}
PENDING_TASK_STATUSES = {"created", "split", "result_submitted", "accepted"}
BLOCKED_TASK_STATUSES = {"rejected", "failed", "blocked"}
FROZEN_EMPLOYEE_STATUSES = {"inactive", "frozen"}


@router.get("/overview")
def get_ai_workforce_overview(request: Request, db: Session = Depends(get_db)):
    require_ai_workforce_user(request, db)
    employees = (
        db.query(AiEmployee)
        .filter(AiEmployee.is_legacy.is_(False))
        .order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc())
        .all()
    )
    task_counts = task_status_counts(db)
    risk_count = task_counts["blocked"] + db.query(RiskEvent).count()
    employee_cards = build_employee_cards(db, employees)
    return {
        "mode": "readonly",
        "employees": employee_summary(db, employees),
        "employee_cards": employee_cards,
        "departments": department_summary(employees),
        "skills": {"total": count_skills(employees)},
        "knowledge": {
            "files": db.query(KnowledgeFile).count(),
            "articles": db.query(KnowledgeArticle).count(),
            "sop": db.query(SopLibrary).count(),
            "prompt": db.query(PromptLibrary).count(),
        },
        "tasks": task_counts,
        "growth": {"available": db.query(EmployeeGrowth).count() > 0},
        "audit": {"risk_count": risk_count},
        "security": {
            "readonly": True,
            "execution_engine_called": False,
            "openclaw_connected": False,
            "n8n_connected": False,
        },
        "empty_state": {
            "no_real_business_data": no_real_business_data(employees, task_counts),
            "message": "当前未接入真实业务数据",
        },
    }


@router.get("/employees/{employee_id}/task-flow")
def get_employee_task_flow(employee_id: str, request: Request, db: Session = Depends(get_db)):
    require_ai_workforce_user(request, db)
    return build_employee_task_flow(db, employee_id)


@router.get("/tasks/waiting-confirm")
def get_waiting_confirm_task_flow(request: Request, db: Session = Depends(get_db)):
    require_ai_workforce_user(request, db)
    return build_waiting_confirm_tasks(db)


@router.get("/tasks/{task_id}/lifecycle")
def get_ai_workforce_task_lifecycle(task_id: int, request: Request, db: Session = Depends(get_db)):
    require_ai_workforce_user(request, db)
    lifecycle = build_task_lifecycle(db, task_id)
    if lifecycle is None:
        raise HTTPException(status_code=404, detail="task not found")
    return lifecycle


def require_ai_workforce_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="no ai workforce permission")
    return user


def employee_summary(db: Session, employees: list[AiEmployee]) -> dict:
    active_codes = [employee.employee_code for employee in employees if employee.status == "active"]
    working_codes: set[str] = set()
    if active_codes:
        rows = (
            db.query(TaskCenterTask.assigned_ai_employee_code)
            .filter(TaskCenterTask.assigned_ai_employee_code.in_(active_codes))
            .filter(TaskCenterTask.status.in_(WORKING_TASK_STATUSES))
            .all()
        )
        working_codes = {row.assigned_ai_employee_code for row in rows if row.assigned_ai_employee_code}
    frozen = sum(1 for employee in employees if employee.status in FROZEN_EMPLOYEE_STATUSES)
    active = sum(1 for employee in employees if employee.status == "active")
    working = len(working_codes)
    return {
        "total": len(employees),
        "working": working,
        "idle": max(active - working, 0),
        "frozen": frozen,
    }


def build_employee_cards(db: Session, employees: list[AiEmployee]) -> list[dict]:
    latest_tasks = latest_task_by_employee(db)
    risk_levels = risk_level_by_employee(db)
    return [employee_card(employee, latest_tasks.get(employee.employee_code), risk_levels.get(employee.employee_code, "low")) for employee in employees]


def latest_task_by_employee(db: Session) -> dict[str, TaskCenterTask]:
    rows = db.query(TaskCenterTask).order_by(TaskCenterTask.updated_at.desc(), TaskCenterTask.id.desc()).limit(500).all()
    latest: dict[str, TaskCenterTask] = {}
    for task in rows:
        code = task.assigned_ai_employee_code
        if code and code not in latest:
            latest[code] = task
    return latest


def risk_level_by_employee(db: Session) -> dict[str, str]:
    levels: dict[str, str] = {}
    for task in db.query(TaskCenterTask).filter(TaskCenterTask.assigned_ai_employee_code.isnot(None)).all():
        code = task.assigned_ai_employee_code
        if not code:
            continue
        if task.status in BLOCKED_TASK_STATUSES:
            levels[code] = "high"
        elif task.status in PENDING_TASK_STATUSES and levels.get(code) != "high":
            levels[code] = "medium"
    for event in db.query(RiskEvent).all():
        current = levels.get(event.employee_code, "low")
        levels[event.employee_code] = max_risk(current, event.risk_level)
    return levels


def employee_card(employee: AiEmployee, task: TaskCenterTask | None, risk_level: str) -> dict:
    skills = parse_json_list(employee.task_types)
    status = employee_display_status(employee, task)
    return {
        "employee_name": employee.employee_name or "未命名AI员工",
        "employee_code": employee.employee_code,
        "department": employee.legion or "未分配部门",
        "department_group": department_group(employee.legion or ""),
        "role": employee.duty or "",
        "status": status,
        "skill_count": len(skills),
        "current_task": task.title if task and task.status in WORKING_TASK_STATUSES else None,
        "current_task_count": 1 if task and task.status in WORKING_TASK_STATUSES else 0,
        "risk_level": normalize_risk(risk_level),
        "requires_review": normalize_risk(risk_level) == "high",
        "detail_url": f"/ai-employee-detail.html?code={employee.employee_code}",
    }


def employee_display_status(employee: AiEmployee, task: TaskCenterTask | None) -> str:
    if employee.status in FROZEN_EMPLOYEE_STATUSES:
        return "frozen"
    if employee.status != "active":
        return "offline"
    if task and task.status in WORKING_TASK_STATUSES:
        return "working"
    return "idle"


def department_group(department: str) -> str:
    if any(key in department for key in ["战略", "策略", "天策"]):
        return "战略部门"
    if any(key in department for key in ["数据", "天采", "天数"]):
        return "数据部门"
    if any(key in department for key in ["知识", "天藏"]):
        return "知识部门"
    if any(key in department for key in ["业务", "电商", "商品", "运营", "投放", "内容", "客服", "财", "法", "安"]):
        return "业务部门"
    if any(key in department for key in ["技术", "研发", "部署", "运维", "质量", "测试", "交付", "天盾", "天检", "天智"]):
        return "技术部门"
    return "业务部门"


def max_risk(left: str, right: str | None) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    left_clean = normalize_risk(left)
    right_clean = normalize_risk(right or "low")
    return left_clean if order[left_clean] >= order[right_clean] else right_clean


def normalize_risk(value: str) -> str:
    clean = (value or "low").strip().lower()
    if clean in {"critical", "high"}:
        return "high"
    if clean in {"medium", "warning"}:
        return "medium"
    return "low"


def department_summary(employees: list[AiEmployee]) -> list[dict]:
    grouped: dict[str, int] = {}
    for employee in employees:
        department = employee.legion or "未分配部门"
        grouped[department] = grouped.get(department, 0) + 1
    return [
        {"name": name, "employee_count": count}
        for name, count in sorted(grouped.items(), key=lambda item: item[0])
    ]


def task_status_counts(db: Session) -> dict:
    rows = db.query(TaskCenterTask.status, func.count(TaskCenterTask.id)).group_by(TaskCenterTask.status).all()
    status_counts = {status: int(count) for status, count in rows}
    return {
        "total": sum(status_counts.values()),
        "running": sum(status_counts.get(status, 0) for status in WORKING_TASK_STATUSES),
        "pending": sum(status_counts.get(status, 0) for status in PENDING_TASK_STATUSES),
        "blocked": sum(status_counts.get(status, 0) for status in BLOCKED_TASK_STATUSES),
    }


def count_skills(employees: list[AiEmployee]) -> int:
    skills: set[str] = set()
    for employee in employees:
        skills.update(parse_json_list(employee.task_types))
    return len(skills)


def parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def no_real_business_data(employees: list[AiEmployee], task_counts: dict) -> bool:
    return not employees and task_counts["total"] == 0
