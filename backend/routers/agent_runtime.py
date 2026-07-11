from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..config import get_settings
from ..database import get_db
from ..models import AiEmployee, User
from ..agent_runtime.exceptions import (
    ApprovalRequiredError,
    CapabilityNotFoundError,
    ExecutionNotFoundError,
    ExecutorUnavailableError,
    InputValidationError,
    PermissionDeniedError,
)
from ..agent_runtime.schemas import (
    AgentCapabilityCreate,
    AgentCapabilityUpdate,
    AgentExecutionApprove,
    AgentExecutionCancel,
    AgentExecutionCreate,
    AgentExecutionReject,
)
from ..agent_runtime.service import (
    approve_execution,
    cancel_execution,
    create_capability,
    create_execution,
    get_capability,
    get_execution,
    get_execution_audit,
    list_capabilities,
    list_executions,
    reject_execution,
    update_capability,
)
from ..agent_runtime.models import AgentCapability
from ..agent_runtime.constants import DEFAULT_CAPABILITIES


router = APIRouter(prefix="/api/v2")
OWNER_ROLES = {"owner", "admin"}


@router.get("/capabilities")
def api_list_capabilities(request: Request, db: Session = Depends(get_db)):
    require_agent_runtime_reader(request, db)
    return {"items": list_capabilities(db)}


@router.get("/capabilities/{capability_id}")
def api_get_capability(capability_id: str, request: Request, db: Session = Depends(get_db)):
    require_agent_runtime_reader(request, db)
    return {"capability": get_capability(db, capability_id)}


@router.post("/capabilities")
def api_create_capability(payload: AgentCapabilityCreate, request: Request, db: Session = Depends(get_db)):
    require_agent_runtime_admin(request, db)
    return {"capability": create_capability(db, payload.model_dump())}


@router.patch("/capabilities/{capability_id}")
def api_update_capability(capability_id: str, payload: AgentCapabilityUpdate, request: Request, db: Session = Depends(get_db)):
    require_agent_runtime_admin(request, db)
    return {"capability": update_capability(db, capability_id, payload.model_dump(exclude_unset=True))}


@router.post("/capabilities/{capability_id}/enable")
def api_enable_capability(capability_id: str, request: Request, db: Session = Depends(get_db)):
    require_agent_runtime_admin(request, db)
    from ..agent_runtime.service import enable_capability

    return {"capability": enable_capability(db, capability_id, enabled=True)}


@router.post("/capabilities/{capability_id}/disable")
def api_disable_capability(capability_id: str, request: Request, db: Session = Depends(get_db)):
    require_agent_runtime_admin(request, db)
    from ..agent_runtime.service import enable_capability

    return {"capability": enable_capability(db, capability_id, enabled=False)}


@router.post("/executions")
def api_create_execution(payload: AgentExecutionCreate, request: Request, db: Session = Depends(get_db)):
    user = require_agent_runtime_user(request, db)
    try:
        execution = create_execution(user, db, payload.model_dump())
    except CapabilityNotFoundError as exc:
        raise HTTPException(status_code=404, detail="能力不存在") from exc
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ApprovalRequiredError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ExecutorUnavailableError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InputValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"execution": execution}


@router.get("/executions")
def api_list_executions(request: Request, task_id: int | None = None, employee_id: int | None = None, db: Session = Depends(get_db)):
    require_agent_runtime_reader(request, db)
    return {"items": list_executions(db, task_id=task_id, employee_id=employee_id)}


@router.get("/executions/{execution_id}")
def api_get_execution(execution_id: str, request: Request, db: Session = Depends(get_db)):
    require_agent_runtime_reader(request, db)
    try:
        return {"execution": get_execution(db, execution_id)}
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="执行记录不存在") from exc


@router.post("/executions/{execution_id}/approve")
def api_approve_execution(execution_id: str, payload: AgentExecutionApprove, request: Request, db: Session = Depends(get_db)):
    user = require_agent_runtime_boss(request, db)
    try:
        return {"execution": approve_execution(db, execution_id, user, payload.boss_confirmed, payload.security_audited)}
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="执行记录不存在") from exc
    except InputValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/executions/{execution_id}/reject")
def api_reject_execution(execution_id: str, payload: AgentExecutionReject, request: Request, db: Session = Depends(get_db)):
    user = require_agent_runtime_boss(request, db)
    try:
        return {"execution": reject_execution(db, execution_id, user, payload.reason)}
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="执行记录不存在") from exc


@router.post("/executions/{execution_id}/cancel")
def api_cancel_execution(execution_id: str, payload: AgentExecutionCancel, request: Request, db: Session = Depends(get_db)):
    user = require_agent_runtime_user(request, db)
    try:
        return {"execution": cancel_execution(db, execution_id, user, payload.reason)}
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="执行记录不存在") from exc
    except InputValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/executions/{execution_id}/audit")
def api_execution_audit(execution_id: str, request: Request, db: Session = Depends(get_db)):
    require_agent_runtime_reader(request, db)
    try:
        return {"items": get_execution_audit(db, execution_id)}
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="执行记录不存在") from exc


@router.get("/agent-runtime/health")
def api_agent_runtime_health(request: Request, db: Session = Depends(get_db)):
    require_agent_runtime_reader(request, db)
    capabilities = db.query(AgentCapability).count()
    settings = get_settings()
    return {
        "status": "healthy",
        "ok": True,
        "capabilities": capabilities or len(DEFAULT_CAPABILITIES),
        "runtime_enabled": settings.AGENT_RUNTIME_ENABLED,
        "real_executor_enabled": settings.REAL_EXECUTOR_ENABLED,
        "feature_flags": {
            "AGENT_RUNTIME_ENABLED": settings.AGENT_RUNTIME_ENABLED,
            "REAL_EXECUTOR_ENABLED": settings.REAL_EXECUTOR_ENABLED,
            "COMPUTER_CONTROL_ENABLED": settings.COMPUTER_CONTROL_ENABLED,
            "MOBILE_CONTROL_ENABLED": settings.MOBILE_CONTROL_ENABLED,
            "BROWSER_CONTROL_ENABLED": settings.BROWSER_CONTROL_ENABLED,
            "SHELL_EXECUTION_ENABLED": settings.SHELL_EXECUTION_ENABLED,
        },
    }


def require_agent_runtime_user(request: Request, db: Session) -> User:
    user = current_user(request, db)
    if normalize_role(user.role) not in OWNER_ROLES and user.username != "boss":
        raise HTTPException(status_code=403, detail="无 Agent Runtime 访问权限")
    return user


def require_agent_runtime_boss(request: Request, db: Session) -> User:
    user = require_agent_runtime_user(request, db)
    if user.username != "boss" and normalize_role(user.role) not in OWNER_ROLES:
        raise HTTPException(status_code=403, detail="需要老板确认")
    return user


def require_agent_runtime_reader(request: Request, db: Session) -> User:
    return require_agent_runtime_user(request, db)


def require_agent_runtime_admin(request: Request, db: Session) -> User:
    user = require_agent_runtime_user(request, db)
    if normalize_role(user.role) not in OWNER_ROLES:
        raise HTTPException(status_code=403, detail="无 Agent Runtime 管理权限")
    return user
