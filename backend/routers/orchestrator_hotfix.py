from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AiEmployee
from . import orchestrator as base


router = APIRouter(prefix="/api/orchestrator")


def _apply_rule_fixes():
    if "可以进入下一阶段" not in base.COMPLETED_KEYWORDS:
        base.COMPLETED_KEYWORDS.append("可以进入下一阶段")

    base.BLOCKER_RULES[:] = [
        item
        for item in base.BLOCKER_RULES
        if item[0] != "database"
    ]
    base.BLOCKER_RULES.insert(
        2,
        (
            "database",
            "critical",
            [
                "数据库连接失败",
                "数据库迁移失败",
                "数据库异常",
                "database failed",
                "database error",
                "migration failed",
                "alembic error",
            ],
        ),
    )


def _extract_explicit_identity(text: str) -> str | None:
    match = base.re.search(r"你是【([^】]+)】", text)
    if match:
        return match.group(1).strip()
    return None


def _detect_employee(db: Session, text: str) -> base.EmployeeDetection:
    explicit_identity = _extract_explicit_identity(text)
    employees = db.query(AiEmployee).order_by(AiEmployee.sort_order.asc(), AiEmployee.id.asc()).all()
    if explicit_identity:
        lower_identity = explicit_identity.lower()
        for employee in employees:
            code = (employee.employee_code or "").strip()
            name = (employee.employee_name or "").strip()
            if code and code.lower() in lower_identity:
                return base.employee_detection_from_row(employee, "high")
            if name and name in explicit_identity:
                return base.employee_detection_from_row(employee, "high")
        for code, fallback in base.EMPLOYEE_FALLBACKS.items():
            if code.lower() in lower_identity or any(keyword in explicit_identity for keyword in fallback["keywords"]):
                row = db.query(AiEmployee).filter(AiEmployee.employee_code == code).one_or_none()
                if row:
                    return base.employee_detection_from_row(row, "high")
                return base.EmployeeDetection(code=code, name=fallback["name"], confidence="high", manual_review_required=False)
    return _original_detect_employee(db, text)


def _recommend_next(db: Session, employee: base.EmployeeDetection, stage: str, completion_status: str, has_blocker: bool, needs_fix: bool, text: str) -> dict:
    if employee.confidence in {"low", "unknown"} or stage == "unknown":
        target = "tiantong"
        action_code = "manual_review"
        action = "建议天统人工判断下一步，不自动执行。"
    elif has_blocker or needs_fix or completion_status in {"blocked", "needs_fix"}:
        target = employee.code or base.STAGE_TO_CODEX.get(stage, "tiantong")
        action_code = "fix"
        action = "建议生成修复 Prompt，由老板人工确认后复制发送。"
    elif completion_status == "completed":
        if stage == "architecture":
            target = "tianwang"
            action_code = "backend_development"
            action = "建议进入天王后端开发阶段，由老板人工确认后复制发送。"
        elif stage == "backend" and ("前端" not in text and "页面" not in text):
            target = "tianjian_test"
            action_code = "test_acceptance"
            action = "建议进入天检测试验收，不跳过验收。"
        else:
            next_stage = base.NEXT_STAGE.get(stage)
            target = base.STAGE_TO_CODEX.get(next_stage or "summary", "tiantong")
            action_code = "continue"
            action = "建议进入下一阶段，由老板人工确认后复制发送。"
    else:
        target = employee.code or base.STAGE_TO_CODEX.get(stage, "tiantong")
        action_code = "continue_current"
        action = "建议继续当前阶段，并由老板人工确认范围。"

    target_row = db.query(AiEmployee).filter(AiEmployee.employee_code == target, AiEmployee.status == "active").one_or_none()
    if not target_row and target != "tiantong":
        target = "tiantong"
        action_code = "manual_review"
        action = "建议天统人工判断，因为目标员工未启用。"
        target_row = db.query(AiEmployee).filter(AiEmployee.employee_code == target, AiEmployee.status == "active").one_or_none()
    return {
        "target_codex": target,
        "target_name": target_row.employee_name if target_row else base.EMPLOYEE_FALLBACKS.get(target, {}).get("name", target),
        "action_code": action_code,
        "action": action,
    }


def _detect_blockers(text: str) -> list[dict]:
    blockers = _original_detect_blockers(text)
    for item in blockers:
        item.setdefault("message", f"{item.get('type')}: {item.get('evidence')}")
    return blockers


_original_detect_employee = base.detect_employee
_original_detect_blockers = base.detect_blockers
_apply_rule_fixes()
base.detect_employee = _detect_employee
base.recommend_next = _recommend_next
base.detect_blockers = _detect_blockers


@router.post("/analyze-reply")
def analyze_reply(payload: base.AnalyzeReplyPayload, request: Request, db: Session = Depends(get_db)):
    data = base.analyze_reply(payload, request, db)
    recommended = data.get("recommended_next", {})
    action_code = "continue"
    if data.get("has_blocker") or data.get("needs_fix"):
        action_code = "fix"
    if data.get("detected_stage") == "architecture" and data.get("completion_status") == "completed" and not data.get("has_blocker"):
        action_code = "backend_development"
    recommended.setdefault("codex", recommended.get("target_codex"))
    recommended.setdefault("codex_name", recommended.get("target_name"))
    recommended.setdefault("recommended_action", action_code)
    recommended.setdefault("action_code", action_code)
    if data.get("has_blocker"):
        data["manual_review_required"] = True
    return data
