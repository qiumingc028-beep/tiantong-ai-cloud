from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..config import get_settings
from ..auth import capture_workflow_id
from ..database import get_db
from ..skills_engine.permissions import require_feature_enabled, require_skills_manage_user, require_skills_user
from ..agent_runtime.workflows.computer.schemas import ComputerWorkflowCreatePayload
from ..agent_runtime.workflows.computer.runner import (
    approve_workflow,
    approve_workflow_checkpoint,
    cancel_workflow,
    create_workflow,
    execute_step,
    get_workflow,
    owned_workflow_or_404,
    owned_workflows_query,
    pause_workflow,
    preview_workflow,
    reject_workflow,
    reject_workflow_checkpoint,
    resume_workflow,
    start_workflow,
    workflow_audit,
)
from ..agent_runtime.workflows.computer.models import ComputerWorkflow, ComputerWorkflowCheckpoint, ComputerWorkflowStep
from ..task_center_ownership import bind_session_task_ownership


router = APIRouter(prefix="/api/v2/computer")
health_router = APIRouter(prefix="/api/v2/computer-workflow")


def _workflow_to_dict_from_model(workflow: ComputerWorkflow) -> dict:
    return {
        "workflow_id": workflow.workflow_id,
        "task_id": workflow.task_id,
        "employee_id": workflow.employee_id,
        "skill_id": workflow.skill_id,
        "device_id": workflow.device_id,
        "session_id": workflow.session_id,
        "goal": workflow.goal,
        "status": workflow.status,
        "risk_level": workflow.risk_level,
        "approval_status": workflow.approval_status,
        "total_steps": workflow.total_steps,
        "current_step": workflow.current_step,
        "max_steps": workflow.max_steps,
        "checkpoint_count": workflow.checkpoint_count,
        "execution_budget": None,
        "started_at": workflow.started_at.isoformat() if workflow.started_at else None,
        "expires_at": workflow.expires_at.isoformat() if workflow.expires_at else None,
        "finished_at": workflow.finished_at.isoformat() if workflow.finished_at else None,
        "stop_reason": workflow.stop_reason,
        "trace_id": workflow.trace_id,
        "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
        "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
    }


def _bind_owner_scope(request: Request, db: Session, *, manage: bool = False):
    user = (require_skills_manage_user if manage else require_skills_user)(request, db)
    bind_session_task_ownership(db, user=user)
    return user


@router.get("/workflows")
def list_workflows(request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    _bind_owner_scope(request, db)
    query = owned_workflows_query(db)
    capture_id = capture_workflow_id(request)
    if capture_id:
        query = query.filter(ComputerWorkflow.workflow_id == capture_id)
    workflows = query.order_by(ComputerWorkflow.created_at.desc()).all()
    return {"items": [_workflow_to_dict_from_model(row) for row in workflows]}


@router.post("/workflows")
def create_workflow_api(payload: ComputerWorkflowCreatePayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    _bind_owner_scope(request, db, manage=True)
    return {"ok": True, **create_workflow(db, payload)}


@router.get("/workflows/{workflow_id}")
def get_workflow_api(workflow_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    _bind_owner_scope(request, db)
    return get_workflow(db, workflow_id)


@router.post("/workflows/{workflow_id}/preview")
def preview_workflow_api(workflow_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    _bind_owner_scope(request, db)
    return preview_workflow(db, workflow_id)


@router.post("/workflows/{workflow_id}/approve")
def approve_workflow_api(workflow_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    user = _bind_owner_scope(request, db, manage=True)
    return approve_workflow(db, workflow_id, approved_by=user.id, trace_id=request.query_params.get("trace_id"))


@router.post("/workflows/{workflow_id}/reject")
def reject_workflow_api(workflow_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    user = _bind_owner_scope(request, db, manage=True)
    return reject_workflow(db, workflow_id, approved_by=user.id, reason=request.query_params.get("reason"), trace_id=request.query_params.get("trace_id"))


@router.post("/workflows/{workflow_id}/start")
def start_workflow_api(workflow_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    _bind_owner_scope(request, db, manage=True)
    return start_workflow(
        db,
        workflow_id,
        current_application=request.query_params.get("current_application"),
        current_window=request.query_params.get("current_window"),
        current_screenshot_hash=request.query_params.get("current_screenshot_hash"),
        trace_id=request.query_params.get("trace_id"),
    )


@router.post("/workflows/{workflow_id}/pause")
def pause_workflow_api(workflow_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    _bind_owner_scope(request, db, manage=True)
    return pause_workflow(db, workflow_id, reason=request.query_params.get("reason"))


@router.post("/workflows/{workflow_id}/resume")
def resume_workflow_api(workflow_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    _bind_owner_scope(request, db, manage=True)
    return resume_workflow(
        db,
        workflow_id,
        current_application=request.query_params.get("current_application"),
        current_window=request.query_params.get("current_window"),
        current_screenshot_hash=request.query_params.get("current_screenshot_hash"),
        trace_id=request.query_params.get("trace_id"),
    )


@router.post("/workflows/{workflow_id}/cancel")
def cancel_workflow_api(workflow_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    _bind_owner_scope(request, db, manage=True)
    return cancel_workflow(db, workflow_id, reason=request.query_params.get("reason"), trace_id=request.query_params.get("trace_id"))


@router.get("/workflows/{workflow_id}/steps")
def list_steps(workflow_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    _bind_owner_scope(request, db)
    owned_workflow_or_404(db, workflow_id)
    steps = db.query(ComputerWorkflowStep).filter(ComputerWorkflowStep.workflow_id == workflow_id).order_by(ComputerWorkflowStep.sequence_number.asc()).all()
    return {"workflow_id": workflow_id, "items": [step.__dict__ for step in steps]}


@router.get("/workflows/{workflow_id}/checkpoints")
def list_checkpoints(workflow_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    _bind_owner_scope(request, db)
    owned_workflow_or_404(db, workflow_id)
    checkpoints = db.query(ComputerWorkflowCheckpoint).filter(ComputerWorkflowCheckpoint.workflow_id == workflow_id).order_by(ComputerWorkflowCheckpoint.created_at.asc()).all()
    return {"workflow_id": workflow_id, "items": [row.__dict__ for row in checkpoints]}


@router.post("/checkpoints/{checkpoint_id}/approve")
def approve_checkpoint_api(checkpoint_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    user = _bind_owner_scope(request, db, manage=True)
    return approve_workflow_checkpoint(db, checkpoint_id, approved_by=user.id, trace_id=request.query_params.get("trace_id"))


@router.post("/checkpoints/{checkpoint_id}/reject")
def reject_checkpoint_api(checkpoint_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    user = _bind_owner_scope(request, db, manage=True)
    return reject_workflow_checkpoint(db, checkpoint_id, approved_by=user.id, reason=request.query_params.get("reason"), trace_id=request.query_params.get("trace_id"))


@router.get("/workflows/{workflow_id}/audit")
def workflow_audit_api(workflow_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("COMPUTER_EXECUTOR_ENABLED")
    require_feature_enabled("MAC_SAFE_WORKFLOW_ENABLED")
    _bind_owner_scope(request, db)
    return workflow_audit(db, workflow_id)


@health_router.get("/health")
def workflow_health():
    settings = get_settings()
    return {
        "status": "healthy",
        "feature_flags": {
            "MAC_SAFE_WORKFLOW_ENABLED": settings.MAC_SAFE_WORKFLOW_ENABLED,
            "MAC_MULTI_STEP_ENABLED": settings.MAC_MULTI_STEP_ENABLED,
            "WORKFLOW_SCOPE_APPROVAL_ENABLED": settings.WORKFLOW_SCOPE_APPROVAL_ENABLED,
            "WORKFLOW_CHECKPOINT_APPROVAL_ENABLED": settings.WORKFLOW_CHECKPOINT_APPROVAL_ENABLED,
            "WORKFLOW_AUTO_CONTINUE_ENABLED": settings.WORKFLOW_AUTO_CONTINUE_ENABLED,
            "WORKFLOW_RECOVERY_ENABLED": settings.WORKFLOW_RECOVERY_ENABLED,
        },
    }
