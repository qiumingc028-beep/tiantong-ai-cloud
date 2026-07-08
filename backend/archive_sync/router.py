from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from .draft_builder import build_archive_drafts, build_decision_log_draft, build_project_status_draft
from .schemas import SprintSummaryPayload
from .sprint_record import list_sprint_records


router = APIRouter(prefix="/api/archive")
PRIVILEGED_ROLES = {"owner", "admin"}


@router.get("/sprints")
def get_archive_sprints(request: Request, db: Session = Depends(get_db)):
    require_archive_user(request, db)
    return {
        "records": [record.model_dump() for record in list_sprint_records()],
        "saved": False,
        "draft_only": True,
    }


@router.post("/sprint-summary")
def create_sprint_summary(payload: SprintSummaryPayload, request: Request, db: Session = Depends(get_db)):
    require_archive_user(request, db)
    return build_archive_drafts(payload).model_dump()


@router.get("/project-status-draft")
def get_project_status_draft(request: Request, db: Session = Depends(get_db)):
    require_archive_user(request, db)
    return {"draft": build_project_status_draft(), "saved": False, "requires_boss_confirmation": True}


@router.get("/decision-draft")
def get_decision_draft(request: Request, db: Session = Depends(get_db)):
    require_archive_user(request, db)
    return {"draft": build_decision_log_draft(), "saved": False, "requires_boss_confirmation": True}


def require_archive_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) in PRIVILEGED_ROLES:
        return user
    raise HTTPException(status_code=403, detail="无项目档案同步权限")
