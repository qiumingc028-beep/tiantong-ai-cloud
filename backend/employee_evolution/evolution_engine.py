from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..dispatch_models import EmployeeExecutionLog
from ..evolution_models import EmployeeGrowth, ReviewAnalysis, RiskEvent, SkillSuggestion
from ..models import TaskCenterResult, TaskCenterTask
from ..review_models import EmployeeScore, TaskReview


HIGH_RISK_WORDS = {
    "deploy",
    "docker",
    "systemctl",
    "git push",
    "权限",
    "部署",
    "删除",
    "扣费",
    "支付",
    "secret",
    "token",
    "password",
}
SENSITIVE_WORDS = {"password", "secret", "token", "api key", "authorization", "bearer", "private_key"}


@dataclass
class EvolutionPayload:
    employee_code: str | None = None
    task_id: int | None = None
    boss_confirmed: bool = False
    security_audited: bool = False


class EvolutionSafetyError(RuntimeError):
    pass


def analyze_employee_evolution(db: Session, payload: EvolutionPayload) -> dict:
    employee_code = payload.employee_code
    task_id = payload.task_id
    if task_id:
        task = db.get(TaskCenterTask, task_id)
        if not task:
            raise ValueError("task not found")
        employee_code = employee_code or task.assigned_ai_employee_code
        if is_high_risk_text(" ".join([task.title or "", task.description or ""])):
            enforce_high_risk_confirmation(payload)
    if not employee_code:
        raise ValueError("employee_code is required")

    reviews_query = db.query(TaskReview).filter(TaskReview.employee_code == employee_code)
    if task_id:
        reviews_query = reviews_query.filter(TaskReview.task_id == task_id)
    reviews = reviews_query.order_by(TaskReview.id.asc()).all()
    logs_query = db.query(EmployeeExecutionLog).filter(EmployeeExecutionLog.employee_code == employee_code)
    if task_id:
        logs_query = logs_query.filter(EmployeeExecutionLog.task_id == task_id)
    logs = logs_query.order_by(EmployeeExecutionLog.id.asc()).all()

    growth = build_growth(db, employee_code, task_id, reviews, logs)
    analyses = build_review_analysis(db, employee_code, reviews, logs)
    suggestions = build_skill_suggestions(db, employee_code, reviews, logs)
    risks = build_risk_events(db, employee_code, reviews, logs)
    db.commit()
    for row in [growth, *analyses, *suggestions, *risks]:
        db.refresh(row)
    return {
        "employee_growth": growth_to_dict(growth),
        "review_analysis": [analysis_to_dict(row) for row in analyses],
        "skill_suggestions": [skill_suggestion_to_dict(row) for row in suggestions],
        "risk_events": [risk_event_to_dict(row) for row in risks],
    }


def build_growth(
    db: Session,
    employee_code: str,
    task_id: int | None,
    reviews: list[TaskReview],
    logs: list[EmployeeExecutionLog],
) -> EmployeeGrowth:
    score_row = db.query(EmployeeScore).filter(EmployeeScore.employee_code == employee_code).first()
    task_count = score_row.task_count if score_row else len({row.task_id for row in reviews} | {row.task_id for row in logs})
    success_rate = score_row.success_rate if score_row else calculate_success_rate(reviews, logs)
    failure_count = sum(1 for row in reviews if not row.success) + sum(1 for row in logs if row.status == "failed")
    average_score = score_row.average_score if score_row else calculate_average_score(reviews)
    growth_score = round(min(100.0, average_score * 0.7 + success_rate * 0.2 + max(task_count - failure_count, 0) * 1.5), 2)
    growth = EmployeeGrowth(
        employee_code=employee_code,
        task_id=task_id,
        score=growth_score,
        growth_level=growth_level(growth_score),
        success_rate=round(success_rate, 2),
        failure_count=failure_count,
        improvement_summary=build_improvement_summary(reviews, logs),
    )
    db.add(growth)
    return growth


def build_review_analysis(
    db: Session,
    employee_code: str,
    reviews: list[TaskReview],
    logs: list[EmployeeExecutionLog],
) -> list[ReviewAnalysis]:
    rows: list[ReviewAnalysis] = []
    for review in reviews:
        row = ReviewAnalysis(
            task_id=review.task_id,
            employee_code=employee_code,
            analysis_type="success" if review.success else "failure",
            reason=safe_text(review.problem_reason),
            suggestion=safe_text(review.improvement),
            status="draft",
        )
        db.add(row)
        rows.append(row)
    if not rows and logs:
        latest = logs[-1]
        row = ReviewAnalysis(
            task_id=latest.task_id,
            employee_code=employee_code,
            analysis_type="execution_log",
            reason=safe_text(latest.error_message or latest.result or "执行日志已记录。"),
            suggestion="补充任务复盘后生成更稳定的成长建议。",
            status="draft",
        )
        db.add(row)
        rows.append(row)
    return rows


def build_skill_suggestions(
    db: Session,
    employee_code: str,
    reviews: list[TaskReview],
    logs: list[EmployeeExecutionLog],
) -> list[SkillSuggestion]:
    failed = [row for row in reviews if not row.success] + [row for row in logs if row.status == "failed"]
    successful = [row for row in reviews if row.success]
    rows: list[SkillSuggestion] = []
    if failed:
        row = SkillSuggestion(
            employee_code=employee_code,
            skill_name="failure_handling",
            suggestion="补充失败处理 SOP、输入校验和错误复盘 Skill，保持 draft，需人工审核后应用。",
            status="draft",
        )
        db.add(row)
        rows.append(row)
    if successful:
        row = SkillSuggestion(
            employee_code=employee_code,
            skill_name="success_pattern_reuse",
            suggestion="将成功任务路径沉淀为同类任务经验，后续经审批后进入 Skill 优化。",
            status="draft",
        )
        db.add(row)
        rows.append(row)
    if not rows:
        row = SkillSuggestion(
            employee_code=employee_code,
            skill_name="baseline_learning",
            suggestion="继续积累执行日志和复盘样本，暂不自动修改 Skill。",
            status="draft",
        )
        db.add(row)
        rows.append(row)
    return rows


def build_risk_events(
    db: Session,
    employee_code: str,
    reviews: list[TaskReview],
    logs: list[EmployeeExecutionLog],
) -> list[RiskEvent]:
    rows: list[RiskEvent] = []
    for log in logs:
        text = " ".join([log.error_message or "", log.input_data or "", log.output_data or "", log.tool_used or ""])
        if log.status == "failed" or is_high_risk_text(text):
            row = RiskEvent(
                employee_code=employee_code,
                event_type="execution_failure" if log.status == "failed" else "high_risk_signal",
                risk_level="high" if is_high_risk_text(text) else "medium",
                description=safe_text(log.error_message or text or "执行风险事件。"),
            )
            db.add(row)
            rows.append(row)
    for review in reviews:
        if not review.success:
            row = RiskEvent(
                employee_code=employee_code,
                event_type="review_failure",
                risk_level="medium",
                description=safe_text(review.problem_reason or "复盘失败事件。"),
            )
            db.add(row)
            rows.append(row)
    return rows


def enforce_high_risk_confirmation(payload: EvolutionPayload) -> None:
    if not (payload.boss_confirmed and payload.security_audited):
        raise EvolutionSafetyError("high risk evolution analysis requires boss confirmation and security audit")


def is_high_risk_text(value: str) -> bool:
    lowered = (value or "").lower()
    return any(word in lowered for word in HIGH_RISK_WORDS)


def safe_text(value: str | None) -> str:
    text = value or ""
    lowered = text.lower()
    if any(word in lowered for word in SENSITIVE_WORDS):
        return "[REDACTED]"
    return text


def calculate_success_rate(reviews: list[TaskReview], logs: list[EmployeeExecutionLog]) -> float:
    if reviews:
        return (sum(1 for row in reviews if row.success) / len(reviews)) * 100
    status_rows = [row for row in logs if row.status in {"completed", "failed"}]
    if not status_rows:
        return 0.0
    return (sum(1 for row in status_rows if row.status == "completed") / len(status_rows)) * 100


def calculate_average_score(reviews: list[TaskReview]) -> float:
    if not reviews:
        return 0.0
    return sum(float(row.score or 0) for row in reviews) / len(reviews)


def growth_level(score: float) -> str:
    if score >= 85:
        return "advanced"
    if score >= 70:
        return "growing"
    if score >= 50:
        return "starter"
    return "needs_review"


def build_improvement_summary(reviews: list[TaskReview], logs: list[EmployeeExecutionLog]) -> str:
    failed = [row for row in reviews if not row.success] + [row for row in logs if row.status == "failed"]
    if failed:
        return "存在失败样本，建议补充 Skill、SOP 与输入质量检查。"
    if reviews:
        return "成功路径稳定，建议沉淀为同类任务经验。"
    return "样本不足，建议继续积累执行日志和任务复盘。"


def growth_to_dict(row: EmployeeGrowth) -> dict:
    return {
        "id": row.id,
        "employee_code": row.employee_code,
        "task_id": row.task_id,
        "score": row.score,
        "growth_level": row.growth_level,
        "success_rate": row.success_rate,
        "failure_count": row.failure_count,
        "improvement_summary": row.improvement_summary or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def analysis_to_dict(row: ReviewAnalysis) -> dict:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "employee_code": row.employee_code,
        "analysis_type": row.analysis_type,
        "reason": row.reason or "",
        "suggestion": row.suggestion or "",
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def skill_suggestion_to_dict(row: SkillSuggestion) -> dict:
    return {
        "id": row.id,
        "employee_code": row.employee_code,
        "skill_name": row.skill_name,
        "suggestion": row.suggestion or "",
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def risk_event_to_dict(row: RiskEvent) -> dict:
    return {
        "id": row.id,
        "employee_code": row.employee_code,
        "event_type": row.event_type,
        "risk_level": row.risk_level,
        "description": row.description or "",
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
