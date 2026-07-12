from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import EmployeeLog, User
from .models import Skill, SkillInvocation, SkillReview
from .registry import audit_employee_log, invocation_to_dict, review_to_dict


def record_skill_audit(db: Session, *, user: User | None, skill: Skill | None = None, invocation: SkillInvocation | None = None, review: SkillReview | None = None, action: str, detail: str):
    log = audit_employee_log(
        db,
        user_id=user.id if user else None,
        action=action,
        detail=detail,
        skill_id=skill.id if skill else (invocation.skill_id if invocation else (review.skill_id if review else None)),
    )
    db.commit()
    return log


def list_audit_logs(db: Session, skill_id: int | None = None, limit: int = 50):
    query = db.query(EmployeeLog).order_by(EmployeeLog.id.desc())
    if skill_id is not None:
        query = query.filter(EmployeeLog.detail.ilike(f"%skill_id={skill_id}%"))
    rows = query.limit(limit).all()
    return [
        {
            "log_id": row.id,
            "user_id": row.user_id,
            "action": row.action,
            "detail": row.detail,
            "ip_address": row.ip_address,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
