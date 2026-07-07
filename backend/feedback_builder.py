from __future__ import annotations

from sqlalchemy.orm import Session

from .review_models import KnowledgeFeedback, TaskReview


def build_knowledge_feedback(db: Session, review: TaskReview) -> KnowledgeFeedback:
    feedback = db.query(KnowledgeFeedback).filter(KnowledgeFeedback.source_task == review.task_id).first()
    if not feedback:
        feedback = KnowledgeFeedback(source_task=review.task_id)
        db.add(feedback)
    feedback.problem = review.problem_reason
    feedback.solution = review.improvement
    feedback.skill_update = build_skill_update(review)
    feedback.status = "draft"
    db.commit()
    db.refresh(feedback)
    return feedback


def build_skill_update(review: TaskReview) -> str:
    if review.success:
        return "将成功经验沉淀为同类任务 Skill 建议，后续经天审批准后再更新生产规则。"
    return "补充失败处理 Skill、SOP 检查项和输入质量校验建议，暂不自动修改生产规则。"


def feedback_to_dict(feedback: KnowledgeFeedback) -> dict:
    return {
        "id": feedback.id,
        "source_task": feedback.source_task,
        "problem": feedback.problem or "",
        "solution": feedback.solution or "",
        "skill_update": feedback.skill_update or "",
        "status": feedback.status,
        "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
    }
