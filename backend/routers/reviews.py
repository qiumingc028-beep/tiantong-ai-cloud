from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..feedback_builder import build_knowledge_feedback, feedback_to_dict
from ..models import TaskCenterTask, User
from ..review_analyzer import generate_task_review, review_to_dict
from ..review_models import EmployeeScore, TaskReview
from ..score_calculator import calculate_employee_score, recalculate_all_employee_scores, score_to_dict


router = APIRouter(prefix="/api/reviews")
PRIVILEGED_ROLES = {"owner", "admin"}
EMPLOYEE_ROLES = {"operator", "customer_service", "designer", "editor"}


class GenerateReviewPayload(BaseModel):
    task_id: int
    include_feedback: bool = True


@router.get("/tasks")
def list_task_reviews(request: Request, db: Session = Depends(get_db)):
    user = require_review_user(request, db)
    query = db.query(TaskReview).order_by(TaskReview.id.desc())
    if not can_view_all_reviews(user):
        query = query.filter(TaskReview.employee_code == user.username)
    rows = query.limit(200).all()
    return {"reviews": [review_to_dict(row) for row in rows]}


@router.get("/employees")
def list_employee_scores(request: Request, db: Session = Depends(get_db)):
    user = require_review_user(request, db)
    if not can_view_all_reviews(user):
        raise HTTPException(status_code=403, detail="无权查看全部员工评分")
    if db.query(EmployeeScore).count() == 0:
        recalculate_all_employee_scores(db)
    rows = db.query(EmployeeScore).order_by(EmployeeScore.average_score.desc(), EmployeeScore.id.asc()).all()
    return {"employees": [score_to_dict(row) for row in rows]}


@router.post("/generate")
def generate_review(payload: GenerateReviewPayload, request: Request, db: Session = Depends(get_db)):
    user = require_review_user(request, db)
    task = db.get(TaskCenterTask, payload.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if not can_view_all_reviews(user) and task.assigned_ai_employee_code != user.username:
        raise HTTPException(status_code=403, detail="只能生成自己的任务复盘")
    try:
        review = generate_task_review(db, payload.task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    score = calculate_employee_score(db, review.employee_code)
    feedback = build_knowledge_feedback(db, review) if payload.include_feedback else None
    return {
        "review": review_to_dict(review),
        "employee_score": score_to_dict(score),
        "knowledge_feedback": feedback_to_dict(feedback) if feedback else None,
    }


@router.get("/employee/{code}")
def get_employee_review(code: str, request: Request, db: Session = Depends(get_db)):
    user = require_review_user(request, db)
    if not can_view_all_reviews(user) and code != user.username:
        raise HTTPException(status_code=403, detail="只能查看自己的复盘")
    reviews = (
        db.query(TaskReview)
        .filter(TaskReview.employee_code == code)
        .order_by(TaskReview.id.desc())
        .limit(200)
        .all()
    )
    score = db.query(EmployeeScore).filter(EmployeeScore.employee_code == code).first()
    if reviews and not score:
        score = calculate_employee_score(db, code)
    return {
        "employee_code": code,
        "score": score_to_dict(score) if score else None,
        "reviews": [review_to_dict(row) for row in reviews],
    }


def require_review_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role == "viewer":
        raise HTTPException(status_code=403, detail="无复盘访问权限")
    if role in PRIVILEGED_ROLES or role in EMPLOYEE_ROLES:
        return user
    raise HTTPException(status_code=403, detail="无复盘访问权限")


def can_view_all_reviews(user: User) -> bool:
    return normalize_role(user.role) in PRIVILEGED_ROLES
