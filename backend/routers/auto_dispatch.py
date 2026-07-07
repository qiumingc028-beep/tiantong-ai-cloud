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
from ..execution_engine import ExecutionEngineError, ExecutionSafetyError, enqueue_execution_task
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
ECOMMERCE_KEYWORDS = {"爆款", "手表", "商品", "选品", "销量", "趋势", "竞品", "电商", "转化", "利润"}
DATA_KEYWORDS = {"数据", "采集", "抓取", "指标", "报表", "分析", "趋势"}
STRATEGY_KEYWORDS = {"策略", "方案", "增长", "推广", "优化", "计划", "建议"}
CREATIVE_KEYWORDS = {"内容", "素材", "视觉", "脚本", "短视频", "种草"}

DEFAULT_CAPABILITIES = [
    {
        "employee_code": "tianshang",
        "employee_name": "天商：商品中心",
        "skills": ["商品分析", "选品", "爆款", "手表", "电商", "ecommerce_operation", "product_analysis"],
        "supported_tasks": ["ecommerce", "product", "trend", "analysis", "ecommerce_operation"],
        "department": "电商经营军团",
        "capability": "商品分析、选品策略、爆款趋势判断",
        "priority": 94,
        "risk_level": "medium",
    },
    {
        "employee_code": "tiancai_data",
        "employee_name": "天采：数据采集平台",
        "skills": ["数据采集", "数据抓取", "趋势数据", "竞品数据", "data_collection"],
        "supported_tasks": ["data", "collection", "trend", "analysis", "data_collection"],
        "department": "数据资产军团",
        "capability": "采集电商、内容、趋势和竞品基础数据",
        "priority": 91,
        "risk_level": "medium",
    },
    {
        "employee_code": "tianshu",
        "employee_name": "天数：数据分析中心",
        "skills": ["数据分析", "趋势分析", "指标分析", "data_analysis"],
        "supported_tasks": ["data", "analysis", "trend", "data_analysis"],
        "department": "数据资产军团",
        "capability": "分析业务数据、趋势变化和异常原因",
        "priority": 89,
        "risk_level": "medium",
    },
    {
        "employee_code": "tiance_strategy",
        "employee_name": "天策：策略分析中心",
        "skills": ["策略分析", "增长策略", "推广计划", "趋势策略", "分析", "strategy_planning"],
        "supported_tasks": ["strategy", "planning", "analysis", "strategy_planning"],
        "department": "经营策略军团",
        "capability": "输出策略方案、增长建议和执行优先级",
        "priority": 87,
        "risk_level": "medium",
    },
    {
        "employee_code": "tiandao",
        "employee_name": "天道：产品设计中心",
        "skills": ["product_analysis", "requirement_design", "business_process"],
        "supported_tasks": ["product", "planning", "analysis", "market_research"],
        "department": "产品设计军团",
        "capability": "产品分析、需求设计、业务流程梳理",
        "priority": 80,
        "risk_level": "medium",
    },
    {
        "employee_code": "tianwang",
        "employee_name": "天王：后端开发中心",
        "skills": ["backend", "api", "database", "pytest"],
        "supported_tasks": ["backend", "api", "database", "development"],
        "department": "研发交付军团",
        "capability": "后端 API、数据库、迁移和测试",
        "priority": 90,
        "risk_level": "high",
    },
    {
        "employee_code": "tianyan",
        "employee_name": "天颜：前端联调优化",
        "skills": ["frontend", "html", "ui", "dashboard"],
        "supported_tasks": ["frontend", "ui", "page", "dashboard"],
        "department": "研发交付军团",
        "capability": "前端页面、交互联调和看板展示",
        "priority": 85,
        "risk_level": "medium",
    },
    {
        "employee_code": "tianjian",
        "employee_name": "天检：测试验收中心",
        "skills": ["testing", "acceptance", "pytest", "regression"],
        "supported_tasks": ["test", "acceptance", "qa", "validation"],
        "department": "质量验收军团",
        "capability": "测试验收、回归检查和质量确认",
        "priority": 88,
        "risk_level": "medium",
    },
    {
        "employee_code": "tianjian_audit",
        "employee_name": "天监：AI审计中心",
        "skills": ["security", "audit", "risk_review"],
        "supported_tasks": ["security", "audit", "risk"],
        "department": "安全审计军团",
        "capability": "安全审计、风险识别和权限边界检查",
        "priority": 92,
        "risk_level": "critical",
    },
    {
        "employee_code": "tiandun",
        "employee_name": "天盾：Deploy Center",
        "skills": ["deploy_review", "health_check", "ops"],
        "supported_tasks": ["deploy", "deployment", "ops", "health_check"],
        "department": "部署运维军团",
        "capability": "部署验证、健康检查和运维修复",
        "priority": 90,
        "risk_level": "critical",
    },
    {
        "employee_code": "tiance",
        "employee_name": "天策：战略规划中心",
        "skills": ["strategy", "growth", "business_analysis"],
        "supported_tasks": ["strategy", "planning", "promotion", "marketing"],
        "department": "经营策略军团",
        "capability": "战略规划、增长分析和业务策略",
        "priority": 82,
        "risk_level": "medium",
    },
    {
        "employee_code": "tianchuang",
        "employee_name": "天创：视觉创意中心",
        "skills": ["creative", "visual", "content"],
        "supported_tasks": ["creative", "visual", "content", "promotion"],
        "department": "内容创意军团",
        "capability": "内容创意、视觉方案和素材规划",
        "priority": 78,
        "risk_level": "low",
    },
    {
        "employee_code": "tiantou",
        "employee_name": "天投：广告投放中心",
        "skills": ["ads", "budget_review", "marketing"],
        "supported_tasks": ["ads", "marketing", "promotion"],
        "department": "增长投放军团",
        "capability": "广告投放、预算复核和投放策略",
        "priority": 76,
        "risk_level": "high",
    },
]

DEFAULT_RULES = [
    {"task_type": "ecommerce", "keyword_rules": ["爆款", "手表", "商品", "选品", "销量", "电商"], "recommended_employee": "tianshang", "priority": 96, "risk_level": "medium"},
    {"task_type": "data_analysis", "keyword_rules": ["数据", "分析", "趋势", "指标"], "recommended_employee": "tianshu", "priority": 90, "risk_level": "medium"},
    {"task_type": "data_collection", "keyword_rules": ["采集", "抓取", "竞品", "趋势"], "recommended_employee": "tiancai_data", "priority": 88, "risk_level": "medium"},
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
    priority: str | None = None
    risk_level: str | None = None
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
    department: str = ""
    capability: str = ""


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
    analysis = match_input(db, title, description, payload.task_type, payload.keywords, payload.capability_tags, payload.priority, payload.risk_level)
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
    try:
        queue_item = enqueue_execution_task(
            db,
            task,
            boss_confirmed=payload.boss_confirmed,
            security_audited=payload.security_audited,
        )
    except ExecutionSafetyError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ExecutionEngineError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.refresh(task)
    return {
        "ok": True,
        "task": task_to_dispatch_dict(task),
        "confirmed_employee": {"employee_code": employee_code, "employee_name": employee_name},
        "risk_level": analysis["risk_level"],
        "queue_item": queue_item,
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
    priority: str | None = None,
    risk_level_override: str | None = None,
) -> dict:
    text = " ".join([title or "", description or "", " ".join(keywords or []), " ".join(capability_tags or [])]).lower()
    if not text.strip() and not task_type:
        return {"task_type": "general", "risk_level": risk_level_override or "low", "recommended_employees": []}
    inferred_type = task_type or infer_task_type(db, text)
    risk_level = risk_level_override or infer_risk_level(text, inferred_type)
    if inferred_type == "general" and not has_capability_match(db, text):
        recommendations = []
    else:
        recommendations = [
            {
                "employee_code": item["employee_code"],
                "employee_name": item["employee_name"],
                "match_reason": item["reason"],
                "score": item["score"],
                "risk_level": item["risk_level"],
            }
            for item in recommend_employees(db, inferred_type, text, risk_level, priority)
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
        if any(keyword in text for keyword in department_keywords(cap.department)):
            return True
        if any(keyword in text for keyword in tokenize_profile_text(cap.capability)):
            return True
    return False


def infer_risk_level(text: str, task_type: str) -> str:
    if task_type in {"deploy", "security"} or any(keyword in text for keyword in HIGH_RISK_KEYWORDS):
        return "critical" if task_type == "deploy" or "部署" in text or "deploy" in text else "high"
    if task_type in {"ads"} or any(keyword in text for keyword in MEDIUM_RISK_KEYWORDS):
        return "medium"
    return "low"


def recommend_employees(db: Session, task_type: str, text: str, risk_level: str, priority: str | None = None) -> list[dict]:
    capabilities = load_capabilities(db)
    rules = load_rules(db)
    rule_employee_boost = {rule.recommended_employee: rule.priority for rule in rules if rule.task_type == task_type}
    items = []
    for cap in capabilities:
        score = cap.priority
        reasons = []
        matched = False
        if task_type in cap.supported_tasks:
            score += 40
            reasons.append(f"支持任务类型 {task_type}")
            matched = True
        department_hits = [word for word in department_keywords(cap.department) if word and word in text]
        if department_hits:
            score += 18
            reasons.append("部门匹配：" + "、".join(department_hits[:3]))
            matched = True
        capability_hits = [word for word in tokenize_profile_text(cap.capability) if word and word in text]
        if capability_hits:
            score += 8 * min(len(capability_hits), 4)
            reasons.append("能力匹配：" + "、".join(capability_hits[:4]))
            matched = True
        skill_hits = [skill for skill in cap.skills if skill.lower() in text or skill in task_type]
        if skill_hits:
            score += 10 * len(skill_hits)
            reasons.append("技能匹配：" + "、".join(skill_hits))
            matched = True
        if cap.employee_code in rule_employee_boost:
            score += rule_employee_boost[cap.employee_code]
            reasons.append("命中路由规则")
            matched = True
        history_score = employee_history_score(db, cap.employee_code, task_type)
        if history_score:
            score += history_score
            reasons.append(f"历史执行记录加权 {history_score}")
            matched = True
        if priority in {"high", "urgent"}:
            score += max(cap.priority // 10, 1)
            reasons.append(f"优先级 {priority} 加权")
        if RISK_ORDER.get(cap.risk_level, 1) >= RISK_ORDER.get(risk_level, 1):
            score += 15
            reasons.append(f"风险等级可覆盖 {risk_level}")
        else:
            score -= 30
            reasons.append(f"风险等级不足，仅支持 {cap.risk_level}")
        if matched and score > 0:
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
    items_by_code: dict[str, CapabilityItem] = {}
    for item in DEFAULT_CAPABILITIES:
        items_by_code[item["employee_code"]] = CapabilityItem(
            employee_code=item["employee_code"],
            employee_name=item["employee_name"],
            skills=item["skills"],
            supported_tasks=item["supported_tasks"],
            priority=item["priority"],
            risk_level=item["risk_level"],
            department=item.get("department", ""),
            capability=item.get("capability", ""),
        )

    rows = db.query(EmployeeCapability).order_by(EmployeeCapability.priority.desc(), EmployeeCapability.id.asc()).all()
    for row in rows:
        items_by_code[row.employee_code] = CapabilityItem(
            employee_code=row.employee_code,
            employee_name=row.employee_name,
            skills=parse_json_list(row.skills),
            supported_tasks=parse_json_list(row.supported_tasks),
            priority=row.priority,
            risk_level=row.risk_level,
            department=items_by_code.get(row.employee_code, CapabilityItem("", "", [], [], 0, "")).department,
            capability=items_by_code.get(row.employee_code, CapabilityItem("", "", [], [], 0, "")).capability,
        )

    employees = db.query(AiEmployee).filter(AiEmployee.status == "active", AiEmployee.is_legacy.is_(False)).all()
    for employee in employees:
        existing = items_by_code.get(employee.employee_code)
        skills = sorted(set((existing.skills if existing else []) + parse_json_list(employee.task_types) + tokenize_profile_text(employee.duty)))
        supported_tasks = sorted(set((existing.supported_tasks if existing else []) + parse_json_list(employee.task_types)))
        items_by_code[employee.employee_code] = CapabilityItem(
            employee_code=employee.employee_code,
            employee_name=employee.employee_name,
            skills=skills,
            supported_tasks=supported_tasks,
            priority=existing.priority if existing else max(60, 100 - employee.sort_order),
            risk_level=existing.risk_level if existing else infer_employee_risk(employee.default_permissions, employee.duty),
            department=employee.legion or (existing.department if existing else ""),
            capability=employee.duty or (existing.capability if existing else ""),
        )

    return sorted(items_by_code.values(), key=lambda item: (-item.priority, item.employee_code))


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


def tokenize_profile_text(raw: str | None) -> list[str]:
    if not raw:
        return []
    text = str(raw).lower()
    tokens = {item.strip() for item in text.replace("、", ",").replace("，", ",").replace("/", ",").split(",") if item.strip()}
    known_terms = [
        "商品", "商品分析", "选品", "爆款", "手表", "电商", "趋势", "趋势分析", "数据", "数据采集", "数据分析",
        "策略", "策略分析", "推广", "推广计划", "广告", "投放", "预算", "前端", "后端", "测试", "验收",
        "审计", "部署", "运维", "内容", "视觉", "素材",
    ]
    for term in known_terms:
        if term in text:
            tokens.add(term)
    return sorted(tokens)


def department_keywords(department: str | None) -> list[str]:
    mapping = {
        "电商经营军团": ["电商", "商品", "选品", "销量", "爆款", "利润"],
        "数据资产军团": ["数据", "采集", "分析", "趋势", "指标"],
        "经营策略军团": ["策略", "推广", "增长", "方案", "计划"],
        "增长投放军团": ["广告", "投放", "预算", "增长"],
        "内容创意军团": ["内容", "视觉", "素材", "脚本"],
        "研发交付军团": ["前端", "后端", "api", "数据库", "页面"],
        "质量验收军团": ["测试", "验收", "回归"],
        "安全审计军团": ["安全", "审计", "权限", "风险"],
        "部署运维军团": ["部署", "运维", "健康检查"],
    }
    return mapping.get(department or "", [])


def infer_employee_risk(default_permissions: str | None, duty: str | None) -> str:
    text = f"{default_permissions or ''} {duty or ''}".lower()
    if any(word in text for word in ("deploy", "部署", "权限", "manage", "audit", "审计")):
        return "high"
    if any(word in text for word in ("execute", "执行", "投放", "预算")):
        return "medium"
    return "low"


def employee_history_score(db: Session, employee_code: str, task_type: str) -> int:
    dispatch_count = db.query(DispatchRecord).filter(DispatchRecord.employee_code == employee_code).count()
    complete_count = (
        db.query(EmployeeExecutionLog)
        .filter(EmployeeExecutionLog.employee_code == employee_code, EmployeeExecutionLog.action == "complete")
        .count()
    )
    task_query = db.query(TaskCenterTask).filter(TaskCenterTask.assigned_ai_employee_code == employee_code)
    if task_type != "general":
        task_query = task_query.filter(TaskCenterTask.description.ilike(f"%{task_type}%"))
    task_count = task_query.count()
    return min(dispatch_count * 2 + complete_count * 4 + task_count * 2, 20)


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
        "capability": item.capability,
        "department": item.department,
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
