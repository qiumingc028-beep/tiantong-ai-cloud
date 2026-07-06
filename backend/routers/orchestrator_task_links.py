from __future__ import annotations

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import require_permission_user
from ..database import get_db
from ..models import AiEmployee, TaskCenterTask
from ..orchestrator_models import OrchestratorAnalysisRecord, OrchestratorTaskLink
from .orchestrator import redact_sensitive_text
from .task_center import write_audit_log


router = APIRouter()

LINK_TYPES = {"existing_task", "created_from_draft"}
DESCRIPTION_LIMIT = 500


class TaskLinkCreate(BaseModel):
    analysis_record_id: int
    task_id: int
    link_type: str = "existing_task"
    note: Optional[str] = None


class TaskDraftCreate(BaseModel):
    analysis_record_id: int


class ConfirmCreateTask(BaseModel):
    analysis_record_id: int
    title: str
    description: Optional[str] = None
    priority: str = "normal"
    parent_task_id: Optional[int] = None
    split_plan: Optional[str] = None
    recommended_ai_employee_code: Optional[str] = None
    note: Optional[str] = None


@router.post("/api/orchestrator/task-links")
def create_task_link(payload: TaskLinkCreate, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "orchestrator.confirm")
    analysis = get_analysis_or_404(db, payload.analysis_record_id)
    task = get_task_or_404(db, payload.task_id)
    link_type = normalize_link_type(payload.link_type)
    if link_type != "existing_task":
        raise HTTPException(status_code=400, detail="link_type must be existing_task")

    link = build_task_link(
        analysis=analysis,
        task=task,
        link_type=link_type,
        created_by_id=user.id,
        note=payload.note,
        recommended_codex=analysis.recommended_codex,
        recommended_action=analysis.recommended_action,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return {"ok": True, "link": task_link_to_dict(link, analysis)}


@router.post("/api/orchestrator/task-drafts")
def create_task_draft(payload: TaskDraftCreate, request: Request, db: Session = Depends(get_db)):
    require_permission_user(request, db, "orchestrator.analyze")
    analysis = get_analysis_or_404(db, payload.analysis_record_id)
    draft = build_task_draft(db, analysis)
    message = "task draft generated; confirm before creating a formal task"
    if analysis.confidence in {None, "low", "unknown"} or analysis.has_blocker or analysis.needs_fix:
        message = "analysis needs manual review before creating a formal task"
    return {
        "ok": True,
        "analysis_id": analysis.id,
        "draft": draft,
        "message": message,
    }


@router.post("/api/orchestrator/task-drafts/confirm-create-task")
def confirm_create_task(payload: ConfirmCreateTask, request: Request, db: Session = Depends(get_db)):
    user = require_permission_user(request, db, "orchestrator.confirm")
    require_permission_user(request, db, "task_center.manage")
    analysis = get_analysis_or_404(db, payload.analysis_record_id)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="task title is required")
    if payload.parent_task_id and not db.get(TaskCenterTask, payload.parent_task_id):
        raise HTTPException(status_code=404, detail="parent task not found")

    task = TaskCenterTask(
        title=redact_sensitive_text(title),
        description=redact_sensitive_text(payload.description.strip()) if payload.description else None,
        priority=payload.priority.strip() or "normal",
        source="orchestrator",
        parent_task_id=payload.parent_task_id,
        split_plan=redact_sensitive_text(payload.split_plan.strip()) if payload.split_plan else None,
        status="created",
        created_by_id=user.id,
        updated_by_id=user.id,
    )
    db.add(task)
    db.flush()
    write_audit_log(db, task, user, "orchestrator_task_created", None, "created", "created from orchestrator confirmed draft")

    link = build_task_link(
        analysis=analysis,
        task=task,
        link_type="created_from_draft",
        created_by_id=user.id,
        note=payload.note or "created from confirmed orchestrator draft",
        recommended_codex=payload.recommended_ai_employee_code or analysis.recommended_codex,
        recommended_action=analysis.recommended_action,
    )
    db.add(link)
    db.commit()
    db.refresh(task)
    db.refresh(link)
    return {
        "ok": True,
        "task_id": task.id,
        "link_id": link.id,
        "task_status": task.status,
        "message": "task created, not assigned, not started, and not sent to Codex",
    }


@router.get("/api/task-center/tasks/{task_id}/orchestrator-links")
def list_task_orchestrator_links(task_id: int, request: Request, db: Session = Depends(get_db)):
    require_task_center_read(request, db)
    get_task_or_404(db, task_id)
    rows = (
        db.query(OrchestratorTaskLink)
        .filter(OrchestratorTaskLink.task_id == task_id)
        .order_by(OrchestratorTaskLink.id.asc())
        .all()
    )
    return [task_link_to_dict(row, row.analysis_record) for row in rows]


def require_task_center_read(request: Request, db: Session):
    try:
        return require_permission_user(request, db, "task_center.read")
    except HTTPException as exc:
        if exc.status_code == 403:
            return require_permission_user(request, db, "task_center.manage")
        raise


def get_analysis_or_404(db: Session, analysis_record_id: int) -> OrchestratorAnalysisRecord:
    analysis = db.get(OrchestratorAnalysisRecord, analysis_record_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="analysis record not found")
    return analysis


def get_task_or_404(db: Session, task_id: int) -> TaskCenterTask:
    task = db.get(TaskCenterTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


def normalize_link_type(link_type: str) -> str:
    clean = (link_type or "").strip()
    if clean not in LINK_TYPES:
        raise HTTPException(status_code=400, detail="invalid link_type")
    return clean


def build_task_link(
    analysis: OrchestratorAnalysisRecord,
    task: TaskCenterTask,
    link_type: str,
    created_by_id: Optional[int],
    note: Optional[str],
    recommended_codex: Optional[str],
    recommended_action: Optional[str],
) -> OrchestratorTaskLink:
    return OrchestratorTaskLink(
        analysis_record_id=analysis.id,
        task_id=task.id,
        link_type=link_type,
        recommended_codex=recommended_codex,
        recommended_action=compact_action(recommended_action),
        source_stage=analysis.detected_stage,
        confidence=analysis.confidence,
        note=redact_sensitive_text(note.strip()) if note else None,
        created_by_id=created_by_id,
    )


def build_task_draft(db: Session, analysis: OrchestratorAnalysisRecord) -> dict:
    employee_name = resolve_employee_name(db, analysis.recommended_codex)
    stage_label = analysis.detected_stage or "orchestrator"
    completion = analysis.completion_status or "unknown"
    title = f"AI Orchestrator {stage_label} {completion} follow-up task"
    description = redact_sensitive_text((analysis.input_excerpt or "")[:DESCRIPTION_LIMIT])
    if not description:
        description = "Generated from Orchestrator analysis record"
    return {
        "title": title,
        "description": description,
        "priority": "normal",
        "split_plan": None,
        "recommended_ai_employee_code": analysis.recommended_codex,
        "recommended_ai_employee_name": employee_name,
        "manual_review_required": analysis.confidence in {None, "low", "unknown"} or analysis.has_blocker or analysis.needs_fix,
    }


def resolve_employee_name(db: Session, employee_code: Optional[str]) -> Optional[str]:
    if not employee_code:
        return None
    employee = db.query(AiEmployee).filter(AiEmployee.employee_code == employee_code).one_or_none()
    return employee.employee_name if employee else employee_code


def compact_action(action: Optional[str]) -> Optional[str]:
    if not action:
        return None
    return redact_sensitive_text(action.strip())[:100]


def iso(value: Optional[datetime]):
    return value.isoformat() if value else None


def task_link_to_dict(link: OrchestratorTaskLink, analysis: Optional[OrchestratorAnalysisRecord]) -> dict:
    return {
        "link_id": link.id,
        "analysis_record_id": link.analysis_record_id,
        "task_id": link.task_id,
        "link_type": link.link_type,
        "recommended_codex": link.recommended_codex,
        "recommended_action": link.recommended_action,
        "source_stage": link.source_stage,
        "confidence": link.confidence,
        "note": link.note,
        "created_by_id": link.created_by_id,
        "created_at": iso(link.created_at),
        "analysis": analysis_summary(analysis),
    }


def analysis_summary(analysis: Optional[OrchestratorAnalysisRecord]) -> Optional[dict]:
    if not analysis:
        return None
    return {
        "detected_employee_name": analysis.detected_employee_name,
        "detected_sprint": analysis.detected_sprint,
        "detected_stage": analysis.detected_stage,
        "completion_status": analysis.completion_status,
        "has_blocker": analysis.has_blocker,
        "needs_fix": analysis.needs_fix,
    }
