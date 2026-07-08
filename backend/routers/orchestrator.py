from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_permission_user
from ..brain_orchestrator import router as brain_orchestrator_router
from ..brain_orchestrator.schemas import AnalyzePayload as BrainAnalyzePayload
from ..brain_orchestrator.schemas import PlanPayload as BrainPlanPayload
from ..database import get_db
from ..models import AiEmployee
from ..orchestrator_models import OrchestratorAnalysisRecord, OrchestratorPromptConfirmation


router = APIRouter(prefix="/api/orchestrator")

CONFIRM_STATUSES = {"confirmed", "copied", "cancelled"}
EXCERPT_LIMIT = 1500
PROMPT_LIMIT = 4000

STAGE_CHAIN = ["product", "architecture", "backend", "frontend", "test", "audit", "deploy", "summary"]
STAGE_TO_CODEX = {
    "product": "tiandao",
    "architecture": "tiangong",
    "backend": "tianwang",
    "frontend": "tianyan_frontend",
    "test": "tianjian_test",
    "audit": "tianjian_audit",
    "deploy": "tiandun_ops",
    "summary": "tiantong",
}
NEXT_STAGE = {
    "product": "architecture",
    "architecture": "backend",
    "backend": "frontend",
    "frontend": "test",
    "test": "audit",
    "audit": "deploy",
    "deploy": "summary",
}

EMPLOYEE_FALLBACKS = {
    "tiantong": {
        "name": "天统：AI总指挥",
        "stage": "summary",
        "keywords": ["天统", "AI总指挥", "汇总", "summarized", "总指挥"],
    },
    "tiangong": {
        "name": "天工：系统架构中心",
        "stage": "architecture",
        "keywords": ["天工", "系统架构中心", "架构设计", "数据库设计", "API设计", "模块边界"],
    },
    "tianwang": {
        "name": "天王：后端开发中心",
        "stage": "backend",
        "keywords": ["天王", "后端开发中心", "后端", "API", "数据库", "Alembic", "模型", "迁移"],
    },
    "tianyan_frontend": {
        "name": "天颜：前端联调优化",
        "stage": "frontend",
        "keywords": ["天颜", "前端联调", "前端", "页面", "联调"],
    },
    "tianjian_test": {
        "name": "天检：测试验收中心",
        "stage": "test",
        "keywords": ["天检", "测试验收", "测试", "验收", "回归", "pytest"],
    },
    "tianjian_audit": {
        "name": "天监：AI审计中心",
        "stage": "audit",
        "keywords": ["天监", "AI审计", "审计", "风险", "权限", "安全边界"],
    },
    "tiandun_ops": {
        "name": "天盾：部署运维修复",
        "stage": "deploy",
        "keywords": ["天盾", "部署运维", "部署", "回滚", "健康检查", "迁移版本"],
    },
    "tiandun_deploy": {
        "name": "天盾：Deploy Center",
        "stage": "deploy",
        "keywords": ["Deploy Center", "deploy center", "部署中心"],
    },
    "tiandao": {
        "name": "天道：AI产品经理中心",
        "stage": "product",
        "keywords": ["天道", "AI产品经理", "产品设计", "PRD", "产品经理"],
    },
}

STAGE_KEYWORDS = {
    "product": ["产品设计", "PRD", "产品经理", "天道"],
    "architecture": ["架构设计", "数据库设计", "API设计", "模块边界", "天工"],
    "backend": ["后端实现", "后端", "API", "模型", "迁移", "Alembic", "天王"],
    "frontend": ["页面", "前端", "联调", "天颜"],
    "test": ["测试", "验收", "回归", "pytest", "天检"],
    "audit": ["审计", "风险", "权限", "安全边界", "天监"],
    "deploy": ["部署", "回滚", "健康检查", "迁移版本", "天盾"],
    "summary": ["汇总", "完成报告", "summarized", "天统"],
}

COMPLETED_KEYWORDS = ["已完成", "测试通过", "验收通过", "审计通过", "已实现", "已交付", "最终状态 summarized", "可以进入下一步"]
BLOCKED_KEYWORDS = ["阻断", "无法继续", "缺少权限", "缺少环境变量", "连接失败", "依赖缺失", "测试无法运行", "部署失败", "需要老板确认"]
NEEDS_FIX_KEYWORDS = ["测试失败", "回归失败", "验收不通过", "审计发现风险", "需要修复", "bug", "failing", "regression"]
INCOMPLETE_KEYWORDS = ["还未完成", "待实现", "下一步继续", "部分完成", "暂未"]

BLOCKER_RULES = [
    ("permission", "warning", ["缺少权限", "权限不足", "403"]),
    ("environment", "warning", ["缺少环境变量", "环境变量", "依赖缺失"]),
    ("database", "critical", ["数据库", "migration failed", "alembic error"]),
    ("redis", "warning", ["redis", "Redis"]),
    ("test_failure", "warning", ["测试失败", "回归失败", "pytest failed", "failing"]),
    ("deploy_failure", "critical", ["部署失败", "deploy failed", "上线失败"]),
    ("requirement_unclear", "warning", ["需求不明确", "需要老板确认", "无法判断"]),
    ("security_risk", "critical", ["安全风险", "密钥泄露", "权限风险"]),
    ("git_risk", "warning", ["GitHub main", "git 冲突", "commit 缺失", "origin/main"]),
    ("scope_risk", "warning", ["扩大范围", "跳过天检", "跳过天监", "跳过天盾"]),
]

SENSITIVE_PATTERNS = [
    re.compile(r"(?i)\b(set-cookie|cookie)\s*[:=]\s*['\"]?[^'\";\s]+"),
    re.compile(r"(?i)\b(tiantong_session|session|sessionid|session_id|csrftoken|csrf_token)\s*=\s*['\"]?[^'\";\s]+"),
    re.compile(r"(?i)\b(database_url|redis_url)\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"(?i)bearer\s+[a-z0-9._-]+"),
    re.compile(r"(?i)(mysql|postgresql|redis)://[^\s]+"),
]


class AnalyzeReplyPayload(BaseModel):
    reply_text: str
    context: dict | None = None


class ConfirmPromptPayload(BaseModel):
    analysis_id: int
    target_codex: str
    confirmed_prompt: str
    confirm_status: str = "confirmed"
    note: str | None = None


@router.post("/analyze")
def analyze_brain_orchestrator(payload: BrainAnalyzePayload, request: Request, db: Session = Depends(get_db)):
    return brain_orchestrator_router.analyze(payload, request, db)


@router.post("/plan")
def plan_brain_orchestrator(payload: BrainPlanPayload, request: Request, db: Session = Depends(get_db)):
    return brain_orchestrator_router.plan(payload, request, db)


@router.get("/tasks/{graph_id}")
def get_brain_orchestrator_task(graph_id: str, request: Request, db: Session = Depends(get_db)):
    return brain_orchestrator_router.get_task(graph_id, request, db)


@router.get("/logs")
def get_brain_orchestrator_logs(request: Request, db: Session = Depends(get_db)):
    return brain_orchestrator_router.logs(request, db)


@dataclass
class EmployeeDetection:
    code: str | None
    name: str | None
    confidence: str
    manual_review_required: bool
    warning: str | None = None


@router.post("/analyze-reply")
def analyze_reply(payload: AnalyzeReplyPayload, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "orchestrator.analyze")
    text = (payload.reply_text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="reply_text is required")

    context = payload.context or {}
    safe_text = redact_sensitive_text(text)
    employee = detect_employee(db, safe_text)
    sprint = detect_sprint(safe_text, context)
    stage = detect_stage(safe_text, employee)
    completion_status = detect_completion_status(safe_text)
    blockers = detect_blockers(safe_text)
    safety_flags = detect_safety_flags(text, employee, sprint, stage)

    has_blocker = bool(blockers) or completion_status == "blocked"
    needs_fix = completion_status in {"blocked", "needs_fix"} or any(item["type"] in {"test_failure", "security_risk", "deploy_failure"} for item in blockers)
    manual_review_required = (
        employee.manual_review_required
        or sprint == "unknown"
        or stage == "unknown"
        or completion_status == "unclear"
        or bool(safety_flags)
    )
    recommendation = recommend_next(db, employee, stage, completion_status, has_blocker, needs_fix, safe_text)
    prompt_draft = build_prompt_draft(
        db=db,
        target_codex=recommendation["target_codex"],
        detected_sprint=sprint,
        detected_employee=employee,
        detected_stage=stage,
        completion_status=completion_status,
        has_blocker=has_blocker,
        blockers=blockers,
        text=safe_text,
        action=recommendation["action"],
    )

    record = OrchestratorAnalysisRecord(
        input_excerpt=safe_text[:EXCERPT_LIMIT],
        input_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        detected_employee_code=employee.code,
        detected_employee_name=employee.name,
        detected_sprint=sprint,
        detected_stage=stage,
        completion_status=completion_status,
        has_blocker=has_blocker,
        needs_fix=needs_fix,
        confidence=employee.confidence,
        recommended_codex=recommendation["target_codex"],
        recommended_action=recommendation["action"],
        prompt_draft=prompt_draft,
        safety_flags_json=json.dumps(safety_flags, ensure_ascii=False),
        created_by_id=user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "analysis_id": record.id,
        "detected_employee": {
            "employee_code": employee.code or "unknown",
            "employee_name": employee.name or "unknown",
        },
        "detected_sprint": sprint,
        "detected_stage": stage,
        "completion_status": completion_status,
        "has_blocker": has_blocker,
        "needs_fix": needs_fix,
        "blockers": blockers,
        "recommended_next": {
            "target_codex": recommendation["target_codex"],
            "target_name": recommendation["target_name"],
            "action": recommendation["action"],
            "is_suggestion": True,
        },
        "prompt_draft": prompt_draft,
        "safety_flags": safety_flags,
        "confidence": employee.confidence,
        "manual_review_required": manual_review_required,
    }


@router.get("/sprints/current")
def get_current_sprint(request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "orchestrator.read")
    latest = db.query(OrchestratorAnalysisRecord).order_by(OrchestratorAnalysisRecord.id.desc()).first()
    current_stage = latest.detected_stage if latest and latest.detected_stage in STAGE_CHAIN else "backend"
    latest_status = latest.completion_status if latest else "incomplete"
    chain = []
    current_index = STAGE_CHAIN.index(current_stage) if current_stage in STAGE_CHAIN else 0
    next_stage = NEXT_STAGE.get(current_stage) if latest_status == "completed" else None
    for index, stage in enumerate(STAGE_CHAIN):
        status = "pending"
        if index < current_index:
            status = "completed"
        elif stage == current_stage:
            status = latest_status if latest_status in {"blocked", "needs_fix"} else "current"
        elif stage == next_stage:
            status = "next"
        chain.append(
            {
                "stage": stage,
                "codex": STAGE_TO_CODEX[stage],
                "status": status,
            }
        )
    return {
        "sprint": latest.detected_sprint if latest and latest.detected_sprint else "Sprint 5",
        "chain": chain,
        "latest_analysis": analysis_summary(latest) if latest else None,
    }


@router.post("/confirm-next-prompt")
def confirm_next_prompt(payload: ConfirmPromptPayload, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "orchestrator.confirm")
    status = payload.confirm_status.strip()
    if status not in CONFIRM_STATUSES:
        raise HTTPException(status_code=400, detail="invalid confirm_status")
    if status in {"sent_to_codex", "executed", "deployed", "merged"}:
        raise HTTPException(status_code=400, detail="execution status is not allowed")
    analysis = db.get(OrchestratorAnalysisRecord, payload.analysis_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="analysis record not found")
    target_codex = payload.target_codex.strip()
    confirmed_prompt = redact_sensitive_text(payload.confirmed_prompt.strip())[:PROMPT_LIMIT]
    if not target_codex:
        raise HTTPException(status_code=400, detail="target_codex is required")
    if not confirmed_prompt:
        raise HTTPException(status_code=400, detail="confirmed_prompt is required")
    safe_note = redact_sensitive_text(payload.note.strip()) if payload.note else None

    confirmation = OrchestratorPromptConfirmation(
        analysis_record_id=analysis.id,
        confirmed_prompt=confirmed_prompt,
        target_codex=target_codex,
        confirm_status=status,
        confirmed_by_id=user.id,
        note=safe_note,
    )
    db.add(confirmation)
    db.commit()
    db.refresh(confirmation)
    return {
        "ok": True,
        "confirmation_id": confirmation.id,
        "message": "Prompt recorded. Boss must copy and send manually.",
    }


@router.get("/analysis-records")
def list_analysis_records(request: Request, limit: int = 20, db: Session = Depends(get_db)):
    require_permission_user(request, db, "orchestrator.read")
    safe_limit = max(1, min(limit, 100))
    rows = db.query(OrchestratorAnalysisRecord).order_by(OrchestratorAnalysisRecord.id.desc()).limit(safe_limit).all()
    return [analysis_summary(row) for row in rows]


def redact_sensitive_text(text: str) -> str:
    safe = text
    for pattern in SENSITIVE_PATTERNS:
        safe = pattern.sub("[REDACTED]", safe)
    return safe


def detect_employee(db: Session, text: str) -> EmployeeDetection:
    lower_text = text.lower()
    employees = db.query(AiEmployee).order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc()).all()
    for employee in employees:
        code = (employee.employee_code or "").strip()
        name = (employee.employee_name or "").strip()
        if code and code.lower() in lower_text:
            return employee_detection_from_row(employee, "high")
        if name and name in text:
            return employee_detection_from_row(employee, "high")

    for employee in employees:
        keywords = employee_keywords(employee)
        if any(keyword and keyword in text for keyword in keywords):
            return employee_detection_from_row(employee, "medium")

    for code, fallback in EMPLOYEE_FALLBACKS.items():
        if code.lower() in lower_text or any(keyword in text for keyword in fallback["keywords"]):
            row = db.query(AiEmployee).filter(AiEmployee.employee_code == code).one_or_none()
            if row:
                return employee_detection_from_row(row, "medium")
            return EmployeeDetection(code=code, name=fallback["name"], confidence="medium", manual_review_required=False)

    return EmployeeDetection(code=None, name=None, confidence="unknown", manual_review_required=True)


def employee_detection_from_row(employee: AiEmployee, confidence: str) -> EmployeeDetection:
    warning = None
    manual_review_required = False
    if employee.status != "active":
        warning = "Detected employee is inactive. Manual confirmation is required."
        manual_review_required = True
    return EmployeeDetection(
        code=employee.employee_code,
        name=employee.employee_name,
        confidence=confidence,
        manual_review_required=manual_review_required,
        warning=warning,
    )


def employee_keywords(employee: AiEmployee) -> list[str]:
    values = [employee.employee_name or "", employee.legion or "", employee.duty or ""]
    if "：" in (employee.employee_name or ""):
        values.append((employee.employee_name or "").split("：", 1)[-1])
    if ":" in (employee.employee_name or ""):
        values.append((employee.employee_name or "").split(":", 1)[-1])
    return [value.strip() for value in values if value and len(value.strip()) >= 2]


def detect_sprint(text: str, context: dict) -> str:
    match = re.search(r"(?:V1\s*)?Sprint\s*([0-9]+)", text, re.IGNORECASE)
    if match:
        return f"Sprint {match.group(1)}"
    if "AI Orchestrator" in text or "自动派单中心" in text:
        return "Sprint 5"
    sprint = str(context.get("sprint") or "").strip()
    if sprint:
        return sprint
    return "unknown"


def detect_stage(text: str, employee: EmployeeDetection) -> str:
    scores = {}
    for stage, keywords in STAGE_KEYWORDS.items():
        scores[stage] = sum(1 for keyword in keywords if keyword in text)
    if employee.code in EMPLOYEE_FALLBACKS:
        fallback_stage = EMPLOYEE_FALLBACKS[employee.code]["stage"]
        scores[fallback_stage] = scores.get(fallback_stage, 0) + 2
    best_stage, best_score = max(scores.items(), key=lambda item: (item[1], -STAGE_CHAIN.index(item[0])))
    return best_stage if best_score > 0 else "unknown"


def detect_completion_status(text: str) -> str:
    completed = any(keyword in text for keyword in COMPLETED_KEYWORDS)
    blocked = any(keyword in text for keyword in BLOCKED_KEYWORDS)
    needs_fix = any(keyword in text for keyword in NEEDS_FIX_KEYWORDS)
    incomplete = any(keyword in text for keyword in INCOMPLETE_KEYWORDS)
    if completed and (blocked or needs_fix):
        return "unclear"
    if blocked:
        return "blocked"
    if needs_fix:
        return "needs_fix"
    if completed:
        return "completed"
    if incomplete:
        return "incomplete"
    return "unclear"


def detect_blockers(text: str) -> list[dict]:
    blockers = []
    for blocker_type, level, keywords in BLOCKER_RULES:
        evidence = next((keyword for keyword in keywords if keyword in text), None)
        if evidence:
            blockers.append(
                {
                    "type": blocker_type,
                    "level": level,
                    "evidence": evidence[:80],
                    "recommended_action": "Generate a fix prompt for manual confirmation.",
                }
            )
    return blockers


def detect_safety_flags(text: str, employee: EmployeeDetection, sprint: str, stage: str) -> list[dict]:
    flags = []
    if any(pattern.search(text) for pattern in SENSITIVE_PATTERNS):
        flags.append({"type": "sensitive_text_redacted", "level": "warning"})
    if employee.warning:
        flags.append({"type": "inactive_employee", "level": "warning", "message": employee.warning})
    if sprint == "unknown":
        flags.append({"type": "unknown_sprint", "level": "warning"})
    if stage == "unknown":
        flags.append({"type": "unknown_stage", "level": "warning"})
    if "自动发送" in text or "自动部署" in text or "跳过天检" in text or "跳过天监" in text or "跳过天盾" in text:
        flags.append({"type": "unsafe_flow_request", "level": "critical"})
    return flags


def recommend_next(db: Session, employee: EmployeeDetection, stage: str, completion_status: str, has_blocker: bool, needs_fix: bool, text: str) -> dict:
    if employee.confidence in {"low", "unknown"} or stage == "unknown":
        target = "tiantong"
        action = "建议天统人工判断下一步，不自动执行。"
    elif has_blocker or needs_fix or completion_status in {"blocked", "needs_fix"}:
        target = employee.code or STAGE_TO_CODEX.get(stage, "tiantong")
        action = "建议生成修复 Prompt，由老板人工确认后复制发送。"
    elif completion_status == "completed":
        if stage == "backend" and ("前端" not in text and "页面" not in text):
            target = "tianjian_test"
            action = "建议进入天检测试验收，不跳过验收。"
        else:
            next_stage = NEXT_STAGE.get(stage)
            target = STAGE_TO_CODEX.get(next_stage or "summary", "tiantong")
            action = "建议进入下一阶段，由老板人工确认后复制发送。"
    else:
        target = employee.code or STAGE_TO_CODEX.get(stage, "tiantong")
        action = "建议继续当前阶段，并由老板人工确认范围。"

    target_row = db.query(AiEmployee).filter(AiEmployee.employee_code == target, AiEmployee.status == "active").one_or_none()
    if not target_row and target != "tiantong":
        target = "tiantong"
        action = "建议天统人工判断，因为目标员工未启用。"
        target_row = db.query(AiEmployee).filter(AiEmployee.employee_code == target, AiEmployee.status == "active").one_or_none()
    return {
        "target_codex": target,
        "target_name": target_row.employee_name if target_row else EMPLOYEE_FALLBACKS.get(target, {}).get("name", target),
        "action": action,
    }


def build_prompt_draft(
    db: Session,
    target_codex: str,
    detected_sprint: str,
    detected_employee: EmployeeDetection,
    detected_stage: str,
    completion_status: str,
    has_blocker: bool,
    blockers: list[dict],
    text: str,
    action: str,
) -> str:
    target = db.query(AiEmployee).filter(AiEmployee.employee_code == target_codex).one_or_none()
    target_name = target.employee_name if target else EMPLOYEE_FALLBACKS.get(target_codex, {}).get("name", target_codex)
    sprint_number = detected_sprint.replace("Sprint", "").strip() if detected_sprint != "unknown" else "5"
    previous_summary = text[:500]
    risk_summary = ", ".join(item["type"] for item in blockers) if blockers else "none"
    task_title = "AI Orchestrator MVP 下一阶段建议任务"
    return (
        f"你是【{target_name}】。\n\n"
        f"现在执行《天统AI公司 V1 Sprint {sprint_number}》的下一阶段任务：\n\n"
        f"【{task_title}】\n\n"
        f"背景：\n系统根据老板粘贴的上一位 AI 员工回复生成建议，不会自动发送或执行。\n\n"
        f"上一个 AI 员工输出结论：\n{previous_summary}\n\n"
        f"当前判断：\n"
        f"- 来源员工：{detected_employee.name or detected_employee.code or 'unknown'}\n"
        f"- 当前阶段：{detected_stage}\n"
        f"- 完成度：{completion_status}\n"
        f"- 是否阻断：{has_blocker}\n"
        f"- 风险：{risk_summary}\n\n"
        f"你的任务：\n{action}\n\n"
        f"限制：\n"
        f"1. 不扩大范围。\n"
        f"2. 不破坏 Sprint 1 / 2 / 3 / 4。\n"
        f"3. 不跳过天检、天监、天盾。\n"
        f"4. 不执行自动部署、自动发消息、自动 GitHub 操作。\n\n"
        f"完成后输出：\n"
        f"1. 修改文件清单 / 或设计结论\n"
        f"2. 测试结果 / 或验收标准\n"
        f"3. 风险说明\n"
        f"4. 下一步建议"
    )[:PROMPT_LIMIT]


def analysis_summary(row: OrchestratorAnalysisRecord | None):
    if not row:
        return None
    return {
        "id": row.id,
        "detected_employee_name": row.detected_employee_name,
        "detected_sprint": row.detected_sprint,
        "detected_stage": row.detected_stage,
        "completion_status": row.completion_status,
        "recommended_codex": row.recommended_codex,
        "confidence": row.confidence,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
