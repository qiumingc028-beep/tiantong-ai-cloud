from __future__ import annotations

from sqlalchemy.orm import Session

from .review_models import EmployeeScore, TaskReview


def calculate_employee_score(db: Session, employee_code: str) -> EmployeeScore:
    reviews = db.query(TaskReview).filter(TaskReview.employee_code == employee_code).all()
    task_count = len(reviews)
    success_count = sum(1 for review in reviews if review.success)
    total_score = sum(float(review.score or 0) for review in reviews)
    success_rate = round((success_count / task_count) * 100, 2) if task_count else 0.0
    average_score = round(total_score / task_count, 2) if task_count else 0.0
    skill_growth = round(min(100.0, average_score * 0.65 + success_rate * 0.25 + task_count * 2), 2) if task_count else 0.0

    score = db.query(EmployeeScore).filter(EmployeeScore.employee_code == employee_code).first()
    if not score:
        score = EmployeeScore(employee_code=employee_code)
        db.add(score)
    score.task_count = task_count
    score.success_rate = success_rate
    score.average_score = average_score
    score.skill_growth = skill_growth
    db.commit()
    db.refresh(score)
    return score


def recalculate_all_employee_scores(db: Session) -> list[EmployeeScore]:
    employee_codes = [row[0] for row in db.query(TaskReview.employee_code).distinct().all()]
    return [calculate_employee_score(db, code) for code in employee_codes]


def score_to_dict(score: EmployeeScore) -> dict:
    return {
        "id": score.id,
        "employee_code": score.employee_code,
        "task_count": score.task_count,
        "success_rate": score.success_rate,
        "average_score": score.average_score,
        "skill_growth": score.skill_growth,
        "updated_at": score.updated_at.isoformat() if score.updated_at else None,
    }
