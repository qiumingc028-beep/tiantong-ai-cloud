from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from .dispatch_models import EmployeeExecutionLog
from .models import TaskCenterResult, TaskCenterTask
from .review_models import TaskReview


SENSITIVE_WORDS = {
    "password",
    "secret",
    "token",
    "api key",
    "authorization",
    "bearer",
    "private_key",
    "access_token",
    "refresh_token",
}


def redact_text(value: Any) -> str | None:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    lowered = text.lower()
    if any(word in lowered for word in SENSITIVE_WORDS):
        return "[REDACTED]"
    return text


def generate_task_review(db: Session, task_id: int) -> TaskReview:
    task = db.get(TaskCenterTask, task_id)
    if not task:
        raise ValueError("task not found")

    logs = (
        db.query(EmployeeExecutionLog)
        .filter(EmployeeExecutionLog.task_id == task.id)
        .order_by(EmployeeExecutionLog.id.asc())
        .all()
    )
    latest_result = (
        db.query(TaskCenterResult)
        .filter(TaskCenterResult.task_id == task.id)
        .order_by(TaskCenterResult.id.desc())
        .first()
    )

    failed_logs = [log for log in logs if log.status == "failed"]
    completed_logs = [log for log in logs if log.status == "completed"]
    success = task.status == "completed" or bool(completed_logs or latest_result)
    if task.status == "failed" or failed_logs:
        success = False

    employee_code = (
        task.assigned_ai_employee_code
        or (logs[-1].employee_code if logs else None)
        or (latest_result.ai_employee_code if latest_result else None)
        or "unassigned"
    )
    problem_reason = build_problem_reason(task, logs, latest_result, success)
    improvement = build_improvement(task, logs, success)
    score = calculate_review_score(task, logs, latest_result, success)

    review = db.query(TaskReview).filter(TaskReview.task_id == task.id).first()
    if not review:
        review = TaskReview(task_id=task.id, employee_code=employee_code)
        db.add(review)
    review.employee_code = employee_code
    review.success = success
    review.score = score
    review.problem_reason = problem_reason
    review.improvement = improvement
    db.commit()
    db.refresh(review)
    return review


def build_problem_reason(
    task: TaskCenterTask,
    logs: list[EmployeeExecutionLog],
    latest_result: TaskCenterResult | None,
    success: bool,
) -> str:
    failed_logs = [log for log in logs if log.status == "failed"]
    if failed_logs:
        return redact_text(failed_logs[-1].error_message or failed_logs[-1].result) or "执行失败，需检查执行日志。"
    if task.status == "failed":
        return "任务状态为 failed，需复查执行链路。"
    if success:
        return "结果与任务目标基本一致。"
    if not logs:
        return "缺少 execution_logs，暂无法完整复盘。"
    if not latest_result:
        return "缺少任务结果记录，建议补充执行输出。"
    return "任务仍处于进行中或待复核状态。"


def build_improvement(task: TaskCenterTask, logs: list[EmployeeExecutionLog], success: bool) -> str:
    if success:
        return "沉淀本次成功路径，复用到同类任务 SOP 与 Skill 建议。"
    if any(log.status == "failed" for log in logs):
        return "复查输入、工具使用与错误日志，补充失败处理 SOP。"
    if task.status in {"assigned", "running", "waiting_review"}:
        return "等待执行完成后补充结果复盘。"
    return "补充任务目标、执行记录和验收标准后重新复盘。"


def calculate_review_score(
    task: TaskCenterTask,
    logs: list[EmployeeExecutionLog],
    latest_result: TaskCenterResult | None,
    success: bool,
) -> float:
    if success:
        score = 88.0
        if latest_result:
            score += 5
        if any(log.tool_used for log in logs):
            score += 2
        return min(score, 100.0)
    if task.status == "failed" or any(log.status == "failed" for log in logs):
        return 35.0
    return 60.0


def review_to_dict(review: TaskReview) -> dict:
    return {
        "id": review.id,
        "task_id": review.task_id,
        "employee_code": review.employee_code,
        "success": bool(review.success),
        "score": review.score,
        "problem_reason": review.problem_reason or "",
        "improvement": review.improvement or "",
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }
