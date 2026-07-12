from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..alpha_workflow.exceptions import AlphaWorkflowDependencyError, AlphaWorkflowNotFoundError, AlphaWorkflowValidationError
from ..alpha_workflow.permissions import require_alpha_workflow_dashboard_enabled, require_alpha_workflow_enabled, require_alpha_workflow_user
from ..alpha_workflow.schemas import AlphaWorkflowRecoverRequest, AlphaWorkflowScenarioCreate, AlphaWorkflowStartRequest
from ..alpha_workflow.service import (
    build_dashboard,
    cancel_alpha_workflow,
    create_scenario,
    get_audit_timeline,
    get_final_report,
    get_stage_detail,
    get_trace,
    get_run,
    get_scenario,
    health_view,
    list_runs,
    list_scenarios,
    recover_alpha_workflow,
    start_alpha_workflow,
)
from ..brain_orchestrator.orchestrator import plan_dry_run


router = APIRouter(prefix="/api/v2/alpha-workflows")


@router.get("/health")
def api_health(request: Request, db: Session = Depends(get_db)):
    require_alpha_workflow_enabled()
    require_alpha_workflow_user(request, db)
    return health_view(db)


@router.get("/scenarios")
def api_list_scenarios(request: Request, db: Session = Depends(get_db)):
    require_alpha_workflow_enabled()
    require_alpha_workflow_user(request, db)
    return {"items": list_scenarios(db)}


@router.get("/scenarios/{scenario_code}")
def api_get_scenario(scenario_code: str, request: Request, db: Session = Depends(get_db)):
    require_alpha_workflow_enabled()
    require_alpha_workflow_user(request, db)
    try:
        return {"scenario": get_scenario(db, scenario_code)}
    except AlphaWorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/scenarios")
def api_create_scenario(payload: AlphaWorkflowScenarioCreate, request: Request, db: Session = Depends(get_db)):
    require_alpha_workflow_enabled()
    user = require_alpha_workflow_user(request, db)
    return {"scenario": create_scenario(db, created_by_id=user.id, payload=payload.model_dump())}


@router.get("/runs")
def api_list_runs(request: Request, db: Session = Depends(get_db)):
    require_alpha_workflow_enabled()
    require_alpha_workflow_user(request, db)
    return {"items": list_runs(db)}


@router.get("/runs/{run_id}")
def api_get_run(run_id: str, request: Request, db: Session = Depends(get_db)):
    require_alpha_workflow_enabled()
    require_alpha_workflow_user(request, db)
    try:
        return {"run": get_run(db, run_id)}
    except AlphaWorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/trace")
def api_get_run_trace(run_id: str, request: Request, db: Session = Depends(get_db)):
    require_alpha_workflow_enabled()
    require_alpha_workflow_user(request, db)
    try:
        return get_trace(db, run_id)
    except AlphaWorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/audit")
def api_get_run_audit(run_id: str, request: Request, db: Session = Depends(get_db)):
    require_alpha_workflow_enabled()
    require_alpha_workflow_user(request, db)
    try:
        return get_audit_timeline(db, run_id)
    except AlphaWorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/report")
def api_get_run_report(run_id: str, request: Request, db: Session = Depends(get_db)):
    require_alpha_workflow_enabled()
    require_alpha_workflow_user(request, db)
    try:
        return get_final_report(db, run_id)
    except AlphaWorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/stages")
def api_get_run_stages(run_id: str, request: Request, db: Session = Depends(get_db)):
    require_alpha_workflow_enabled()
    require_alpha_workflow_user(request, db)
    try:
        return get_stage_detail(db, run_id)
    except AlphaWorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/demo")
def api_run_demo(payload: AlphaWorkflowStartRequest, request: Request, db: Session = Depends(get_db)):
    require_alpha_workflow_enabled()
    user = require_alpha_workflow_user(request, db)
    try:
        orchestrator_plan = plan_dry_run(db, payload.input_text, created_by=user.username, boss_confirmed=True, security_audited=True)
        run = start_alpha_workflow(
            db,
            user=user,
            input_text=payload.input_text,
            trace_id=payload.trace_id or orchestrator_plan.get("graph_id"),
            scenario_code=payload.scenario_code,
            orchestrator_plan=orchestrator_plan,
        )
    except (AlphaWorkflowDependencyError, AlphaWorkflowValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "run": run}


@router.post("/runs/{run_id}/recover")
def api_recover_run(run_id: str, payload: AlphaWorkflowRecoverRequest, request: Request, db: Session = Depends(get_db)):
    require_alpha_workflow_enabled()
    user = require_alpha_workflow_user(request, db)
    try:
        return {"ok": True, "run": recover_alpha_workflow(db, user=user, run_id=run_id, reason=payload.reason)}
    except (AlphaWorkflowDependencyError, AlphaWorkflowValidationError, AlphaWorkflowNotFoundError) as exc:
        raise HTTPException(status_code=400 if not isinstance(exc, AlphaWorkflowNotFoundError) else 404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/cancel")
def api_cancel_run(run_id: str, payload: AlphaWorkflowRecoverRequest, request: Request, db: Session = Depends(get_db)):
    require_alpha_workflow_enabled()
    user = require_alpha_workflow_user(request, db)
    try:
        return {"ok": True, "run": cancel_alpha_workflow(db, user=user, run_id=run_id, reason=payload.reason)}
    except AlphaWorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/dashboard")
def api_dashboard(request: Request, db: Session = Depends(get_db)):
    require_alpha_workflow_dashboard_enabled()
    require_alpha_workflow_user(request, db)
    return build_dashboard(db)
