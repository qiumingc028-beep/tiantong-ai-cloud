from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import current_user, require_permission_user
from ..auth_data import normalize_role
from ..database import get_db
from ..dispatch_models import DispatchRecord, EmployeeCapability, EmployeeExecutionLog, TaskRoutingRule
from ..models import AiEmployee, TaskCenterAuditLog, TaskCenterTask, User


router = APIRouter(prefix="/api/auto-dispatch")

RISK_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}
HIGH_RISK_KEYWORDS = {
    "deploy",
    "deployment",
    "上线",
    "部署",
    "权限",
    "permission",
    "password",
    "secret",
    "token",
    "支付",
    "扣费",
    "删除",
    "drop",
    "truncate",
    "git push",
    "systemctl",
    "docker",
}
MEDIUM_RISK_KEYWORDS = {"广告", "投放", "预算", "价格", "调价", "客服", "订单", "库存"}

DEFAULT_CAPABILITIES = [
    {
        "employee_code": "tiandao",
        "employee_name": "天道：产品设计中心",
        "skills": ["product_analysis", "requirement_design", "business_process"],
        "supported_tasks": ["product", "planning", "analysis", "market_research"],
        "priority": 80,
        "risk_level": "medium",
    },
    {
        "employee_code": "tianwang",
        "employee_name": "天王：后端开发中心",
        "skills": ["backend", "api", "database", "pytest"],
        "supported_tasks": ["backend", "api", "database", "development"],
        "priority": 90,
        "risk_level": "high",
    },
    {
        "employee_code": "tianyan",
        "employee_name": "天颜：前端联调优化",
        "skills": ["frontend", "html", "ui", "dashboard"],
        "supported_tasks": ["frontend", "ui", "page", "dashboard"],
        "priority": 85,
        "risk_level": "medium",
    },
    {
        "employee_code": "tianjian",
        "employee_name": "天检：测试验收中心",
        "skills": ["testing", "acceptance", "pytest", "regression"],
        "supported_tasks": ["test", "acceptance", "qa", "validation"],
        "priority": 88,
        "risk_level": "medium",
    },
    {
        "employee_code": "tianjian_audit",
        "employee_name": "天监：AI审计中心",
        "skills": ["security", "audit", "risk_review"],
        "supported_tasks": ["security", "audit", "risk"],
        "priority": 92,
        "risk_level": "critical",
    },
    {
        "employee_code": "tiandun",
        "employee_name": "天盾：Deploy Center",
        "skills": ["deploy_review", "health_check", "ops"],
        "supported_tasks": ["deploy", "deployment", "ops", "health_check"],
        "priority": 90,
        "risk_level": "critical",
    },
    {
        "employee_code": "tiance",
        "employee_name": "天策：战略规划中心",
        "skills": ["strategy", "growth", "business_analysis"],
        "supported_tasks": ["strategy", "planning", "promotion", "marketing"],
        "priority": 82,
        "risk_level": "medium",
    },
    {
        "employee_code": "tianchuang",
        "employee_name": "天创：视觉创意中心",
        "skills": ["creative", "visual", "content"],
        "supported_tasks": ["creative", "visual", "content", "promotion"],
        "priority": 78,
        "risk_level": "low",
    },
    {
        "employee_code": "tiantou",
        "employee_name": "天投：广告投放中心",
        "skills": ["ads", "budget_review", "marketing"],
        "supported_tasks": ["ads", "marketing", "promotion"],
        "priority": 76,
        "risk_level": "high",
    },
]

DEFAULT_RULES = [
    {"task_type": "backend", "keyword_rules": ["后端", "api", "database", "数据库"], "recommended_employee": "tianwang", "priority": 90, "risk_level": "medium"},
    {"task_type": "frontend", "keyword_rules": ["前端", "页面", "ui", "dashboard"], "recommended_employee": "tianyan", "priority": 85, "risk_level": "low"},
    {"task_type": "testing", "keyword_rules": ["测试", "验收", "pytest", "回归"], "recommended_employee": "tianjian", "priority": 88, "risk_level": "low"},
    {"task_type": "security", "keyword_rules": ["安全", "审计", "权限", "secret"], "recommended_employee": "tianjian_audit", "priority": 92, "risk_level": "high"},
    {"task_type": "deploy", "keyword_rules": ["部署", "上线", "deploy", "docker"], "recommended_employee": "tiandun", "priority": 95, "risk_level": "critical"},
    {"task_type": "strategy", "keyword_rules": ["策略", "推广", "增长", "方案"], "recommended_employee": "tiance", "priority": 82, "risk_level": "medium"},
    {"task_type": "creative", "keyword_rules": ["视觉", "创意", "素材", "内容"], "recommended_employee": "tianchuang", "priority": 78, "risk_level": "low"},
    {"task_type": "ads", "keyword_rules": ["广告", "投放", "预算"], "recommended_employee": "tiantou", "priority": 80, "risk_level": "high"},
]


class AnalyzePayload(BaseModel):
    title: str
    description: str | None = None
    task_type: str | None = None


class MatchPayload(BaseModel):
    task_title: str | None = None
    task_description: str | None = None
    task_type: str | None = None
    keywords: list[str] | None = None
    capability_tags: list[str] | None = None
    title: str | None = None
    description: str | None = None


class ConfirmPayload(BaseModel):
    employee_code: str | None = None
    boss_confirmed: bool = False
    security_audited: bool = False
    detail: str | None = None


class TrackingPayload(BaseModel):
    employee_code: str
    action: str
    result: str | None = None


@dataclass
class CapabilityItem:
    employee_code: str
    employee_name: str
    skills: list[str]
    supported_tasks: list[str]
    priority: int
    risk_level: str


@dataclass
class RoutingRuleItem:
    task_type: str
    keyword_rules: list[str]
    recommended_employee: str
    priority: int
    risk_level: str


@router.post("/analyze")
def analyze_task(payload: AnalyzePayload, request: Request, db: Session = Depends(get_db)):
    require_auto_dispatch_read(request, db)
    return analyze_input(db, payload.title, payload.description, payload.task_type)


@router.post("/match")
def match_employee(payload: MatchPayload, request: Request, db: Session = Depends(get_db)):
    require_auto_dispatch_read(request, db)
    title = payload.task_title or payload.title or " ".join(payload.keywords or []) or payload.task_type or ""
    description = payload.task_description or payload.description or " ".join(payload.capability_tags or [])
    analysis = match_input(db, title, description, payload.task_type, payload.keywords, payload.capability_tags)
    return {
        "task_type": analysis["task_type"],
        "risk_level": analysis["risk_level"],
        "recommended_employees": analysis["recommended_employees"],
        "best_employee": analysis["recommended_employees"][0] if analysis["recommended_employees"] else None,
    }


@router.post("/tasks/{task_id}/plan")
def create_dispatch_plan(task_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_auto_dispatch_manage(request, db)
    task = get_task_or_404(db, task_id)
    analysis = analyze_input(db, task.title, task.description, None)
    recommendations = analysis["recommended_employees"]
    if not recommendations:
        raise HTTPException(status_code=400, detail="no dispatch candidate found")

    existing = db.query(DispatchRecord).filter(DispatchRecord.task_id == task.id).all()
    for row in existing:
        row.dispatch_status = "superseded"

    records = []
    for rank, item in enumerate(recommendations[:3], start=1):
        record = DispatchRecord(
            task_id=task.id,
            employee_code=item["employee_code"],
            dispatch_reason=f"rank={rank}; score={item['score']}; {item['reason']}",
            dispatch_status="pending_confirmation" if analysis["requires_boss_confirmation"] else "planned",
        )
        db.add(record)
        records.append(record)
    write_task_audit_log(db, task, user, "dispatch_plan_generated", task.status, task.status, analysis["risk_level"])
    db.commit()
    for record in records:
        db.refresh(record)
    return {
        "dispatch_plan": {
            "task_id": task.id,
            "risk_level": analysis["risk_level"],
            "requires_boss_confirmation": analysis["requires_boss_confirmation"],
            "requires_security_audit": analysis["requires_security_audit"],
            "can_auto_execute": analysis["can_auto_execute"],
            "execution_order": [item["employee_code"] for item in recommendations[:3]],
            "employees": recommendations[:3],
        },
        "dispatch_records": [dispatch_record_to_dict(record) for record in records],
    }


@router.post("/tasks/{task_id}/confirm")
def confirm_dispatch(task_id: int, payload: ConfirmPayload, request: Request, db: Session = Depends(get_db)):
    user = require_auto_dispatch_manage(request, db)
    task = get_task_or_404(db, task_id)
    analysis = analyze_input(db, task.title, task.description, None)
    if analysis["risk_level"] in {"high", "critical"}:
        require_boss_role(user)
        if not payload.boss_confirmed:
            raise HTTPException(status_code=400, detail="high risk dispatch requires boss confirmation")
        if not payload.security_audited:
            raise HTTPException(status_code=400, detail="high risk dispatch requires security audit")

    employee_code = payload.employee_code or (analysis["recommended_employees"][0]["employee_code"] if analysis["recommended_employees"] else None)
    if not employee_code:
        raise HTTPException(status_code=400, detail="employee_code is required")

    employee_name = resolve_employee_name(db, employee_code)
    task.assigned_ai_employee_code = employee_code
    task.assigned_ai_employee_name = employee_name
    old_status = task.status
    task.status = "assigned"
    task.updated_by_id = user.id
    db.add(
        DispatchRecord(
            task_id=task.id,
            employee_code=employee_code,
            dispatch_reason=payload.detail or "boss confirmed dispatch",
            dispatch_status="confirmed",
        )
    )
    write_task_audit_log(db, task, user, "auto_dispatch_confirmed", old_status, "assigned", employee_code)
    db.commit()
    db.refresh(task)
    return {
        "ok": True,
        "task": task_to_dispatch_dict(task),
        "confirmed_employee": {"employee_code": employee_code, "employee_name": employee_name},
        "risk_level": analysis["risk_level"],
    }


@router.post("/tasks/{task_id}/tracking")
def create_execution_tracking(task_id: int, payload: TrackingPayload, request: Request, db: Session = Depends(get_db)):
    require_auto_dispatch_manage(request, db)
    get_task_or_404(db, task_id)
    clean_action = payload.action.strip()
    if clean_action not in {"start", "execute", "complete", "fail"}:
        raise HTTPException(status_code=400, detail="invalid tracking action")
    log = EmployeeExecutionLog(
        task_id=task_id,
        employee_code=payload.employee_code.strip(),
        action=clean_action,
        result=payload.result,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return {"ok": True, "log": execution_log_to_dict(log)}


@router.get("/tasks/{task_id}/tracking")
def get_execution_tracking(task_id: int, request: Request, db: Session = Depends(get_db)):
    require_auto_dispatch_read(request, db)
    get_task_or_404(db, task_id)
    records = db.query(DispatchRecord).filter(DispatchRecord.task_id == task_id).order_by(DispatchRecord.id.asc()).all()
    logs = db.query(EmployeeExecutionLog).filter(EmployeeExecutionLog.task_id == task_id).order_by(EmployeeExecutionLog.id.asc()).all()
    return {
        "task_id": task_id,
        "dispatch_records": [dispatch_record_to_dict(record) for record in records],
        "execution_logs": [execution_log_to_dict(log) for log in logs],
    }


@router.get("/employee-capabilities")
def list_employee_capabilities(request: Request, db: Session = Depends(get_db)):
    require_auto_dispatch_read(request, db)
    return [capability_to_dict(item) for item in load_capabilities(db)]


@router.get("/routing-rules")
def list_routing_rules(request: Request, db: Session = Depends(get_db)):
    require_auto_dispatch_read(request, db)
    return [routing_rule_to_dict(item) for item in load_rules(db)]


@router.get("/overview")
def auto_dispatch_overview(request: Request, db: Session = Depends(get_db)):
    require_auto_dispatch_read(request, db)
    return {
        "employee_capability_count": len(load_capabilities(db)),
        "routing_rule_count": len(load_rules(db)),
        "dispatch_record_count": db.query(DispatchRecord).count(),
        "execution_log_count": db.query(EmployeeExecutionLog).count(),
        "readonly_safety": {
            "high_risk_requires_boss_confirmation": True,
            "high_risk_requires_security_audit": True,
            "auto_deploy_allowed": False,
            "permission_mutation_allowed": False,
            "git_submit_allowed": False,
        },
    }


def analyze_input(db: Session, title: str, description: str | None, task_type: str | None = None) -> dict:
    text = f"{title or ''} {description or ''}".lower()
    inferred_type = task_type or infer_task_type(db, text)
    risk_level = infer_risk_level(text, inferred_type)
    recommendations = recommend_employees(db, inferred_type, text, risk_level)
    return {
        "task_type": inferred_type,
        "risk_level": risk_level,
        "recommended_employees": recommendations,
        "requires_boss_confirmation": risk_level in {"high", "critical"},
        "requires_security_audit": risk_level in {"high", "critical"},
        "can_auto_execute": risk_level == "low",
        "safety_notes": "高风险任务禁止自动执行，必须老板确认并经过天监审计。" if risk_level in {"high", "critical"} else "低风险任务允许进入执行队列。",
    }


def match_input(
    db: Session,
    title: str,
    description: str | None,
    task_type: str | None = None,
    keywords: list[str] | None = None,
    capability_tags: list[str] | None = None,
) -> dict:
    text = " ".join([title or "", description or "", " ".join(keywords or []), " ".join(capability_tags or [])]).lower()
    inferred_type = task_type or infer_task_type(db, text)
    risk_level = infer_risk_level(text, inferred_type)
    if inferred_type == "general" and not has_capability_match(db, text):
        recommendations = []
    else:
        recommendations = [
            {
                "employee_code": item["employee_code"],
                "employee_name": item["employee_name"],
                "match_reason": item["reason"],
                "risk_level": item["risk_level"],
            }
            for item in recommend_employees(db, inferred_type, text, risk_level)
        ]
    return {
        "task_type": inferred_type,
        "risk_level": risk_level,
        "recommended_employees": recommendations,
    }


def infer_task_type(db: Session, text: str) -> str:
    best_rule = None
    best_score = -1
    for rule in load_rules(db):
        score = sum(1 for keyword in rule.keyword_rules if keyword.lower() in text)
        if score > best_score or (score == best_score and best_rule and rule.priority > best_rule.priority):
            best_rule = rule
            best_score = score
    return best_rule.task_type if best_rule and best_score > 0 else "general"


def has_capability_match(db: Session, text: str) -> bool:
    for cap in load_capabilities(db):
        if any(skill.lower() in text for skill in cap.skills):
            return True
        if any(task.lower() in text for task in cap.supported_tasks):
            return True
    return False


def infer_risk_level(text: str, task_type: str) -> str:
    if task_type in {"deploy", "security"} or any(keyword in text for keyword in HIGH_RISK_KEYWORDS):
        return "critical" if task_type == "deploy" or "部署" in text or "deploy" in text else "high"
    if task_type in {"ads"} or any(keyword in text for keyword in MEDIUM_RISK_KEYWORDS):
        return "medium"
    return "low"


def recommend_employees(db: Session, task_type: str, text: str, risk_level: str) -> list[dict]:
    capabilities = load_capabilities(db)
    rules = load_rules(db)
    rule_employee_boost = {rule.recommended_employee: rule.priority for rule in rules if rule.task_type == task_type}
    items = []
    for cap in capabilities:
        score = cap.priority
        reasons = []
        if task_type in cap.supported_tasks:
            score += 40
            reasons.append(f"支持任务类型 {task_type}")
        skill_hits = [skill for skill in cap.skills if skill.lower() in text or skill in task_type]
        if skill_hits:
            score += 10 * len(skill_hits)
            reasons.append("技能匹配：" + "、".join(skill_hits))
        if cap.employee_code in rule_employee_boost:
            score += rule_employee_boost[cap.employee_code]
            reasons.append("命中路由规则")
        if RISK_ORDER.get(cap.risk_level, 1) >= RISK_ORDER.get(risk_level, 1):
            score += 15
            reasons.append(f"风险等级可覆盖 {risk_level}")
        else:
            score -= 30
            reasons.append(f"风险等级不足，仅支持 {cap.risk_level}")
        if score > 0:
            items.append(
                {
                    "employee_code": cap.employee_code,
                    "employee_name": cap.employee_name,
                    "score": score,
                    "risk_level": cap.risk_level,
                    "reason": "；".join(reasons) or "默认能力匹配",
                }
            )
    items.sort(key=lambda item: item["score"], reverse=True)
    return items[:5]


def load_capabilities(db: Session) -> list[CapabilityItem]:
    rows = db.query(EmployeeCapability).order_by(EmployeeCapability.priority.desc(), EmployeeCapability.id.asc()).all()
    if rows:
        return [
            CapabilityItem(
                employee_code=row.employee_code,
                employee_name=row.employee_name,
                skills=parse_json_list(row.skills),
                supported_tasks=parse_json_list(row.supported_tasks),
                priority=row.priority,
                risk_level=row.risk_level,
            )
            for row in rows
        ]
    return [
        CapabilityItem(
            employee_code=item["employee_code"],
            employee_name=item["employee_name"],
            skills=item["skills"],
            supported_tasks=item["supported_tasks"],
            priority=item["priority"],
            risk_level=item["risk_level"],
        )
        for item in DEFAULT_CAPABILITIES
    ]


def load_rules(db: Session) -> list[RoutingRuleItem]:
    rows = db.query(TaskRoutingRule).order_by(TaskRoutingRule.priority.desc(), TaskRoutingRule.id.asc()).all()
    if rows:
        return [
            RoutingRuleItem(
                task_type=row.task_type,
                keyword_rules=parse_json_list(row.keyword_rules),
                recommended_employee=row.recommended_employee,
                priority=row.priority,
                risk_level=row.risk_level,
            )
            for row in rows
        ]
    return [
        RoutingRuleItem(
            task_type=item["task_type"],
            keyword_rules=item["keyword_rules"],
            recommended_employee=item["recommended_employee"],
            priority=item["priority"],
            risk_level=item["risk_level"],
        )
        for item in DEFAULT_RULES
    ]


def parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(item) for item in data]
    except Exception:
        pass
    return [item.strip() for item in raw.split(",") if item.strip()]


def get_task_or_404(db: Session, task_id: int) -> TaskCenterTask:
    task = db.get(TaskCenterTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


def require_auto_dispatch_read(request: Request, db: Session) -> User:
    try:
        return require_permission_user(request, db, "task_center.read")
    except HTTPException as exc:
        if exc.status_code == 403:
            return require_permission_user(request, db, "task_center.manage")
        raise


def require_auto_dispatch_manage(request: Request, db: Session) -> User:
    return require_permission_user(request, db, "task_center.manage")


def require_boss_role(user: User) -> None:
    if normalize_role(user.role) not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="high risk dispatch requires boss permission")


def resolve_employee_name(db: Session, employee_code: str) -> str:
    employee = db.query(AiEmployee).filter(AiEmployee.employee_code == employee_code).one_or_none()
    if employee:
        return employee.employee_name
    for cap in load_capabilities(db):
        if cap.employee_code == employee_code:
            return cap.employee_name
    return employee_code


def write_task_audit_log(
    db: Session,
    task: TaskCenterTask,
    user: User,
    action: str,
    from_status: str | None,
    to_status: str | None,
    detail: str | None,
) -> None:
    db.add(
        TaskCenterAuditLog(
            task_id=task.id,
            action=action,
            from_status=from_status,
            to_status=to_status,
            detail=detail,
            actor_id=user.id,
            actor_role=user.role,
        )
    )


def capability_to_dict(item: CapabilityItem) -> dict:
    return {
        "employee_code": item.employee_code,
        "employee_name": item.employee_name,
        "skills": item.skills,
        "supported_tasks": item.supported_tasks,
        "priority": item.priority,
        "risk_level": item.risk_level,
    }


def routing_rule_to_dict(item: RoutingRuleItem) -> dict:
    return {
        "task_type": item.task_type,
        "keyword_rules": item.keyword_rules,
        "recommended_employee": item.recommended_employee,
        "priority": item.priority,
        "risk_level": item.risk_level,
    }


def dispatch_record_to_dict(record: DispatchRecord) -> dict:
    return {
        "id": record.id,
        "task_id": record.task_id,
        "employee_code": record.employee_code,
        "dispatch_reason": record.dispatch_reason,
        "dispatch_status": record.dispatch_status,
        "created_at": iso(record.created_at),
    }


def execution_log_to_dict(log: EmployeeExecutionLog) -> dict:
    return {
        "id": log.id,
        "task_id": log.task_id,
        "employee_code": log.employee_code,
        "action": log.action,
        "result": log.result,
        "created_at": iso(log.created_at),
    }


def task_to_dispatch_dict(task: TaskCenterTask) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "assigned_ai_employee_code": task.assigned_ai_employee_code,
        "assigned_ai_employee_name": task.assigned_ai_employee_name,
    }


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
