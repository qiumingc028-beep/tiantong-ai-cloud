from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..observability.exceptions import ObservabilityNotFoundError
from ..observability.permissions import (
    require_feature_enabled,
    require_observability_manage_user,
    require_observability_user,
)
from ..observability.schemas import AlertRuleCreateRequest, AlertRuleUpdateRequest, IncidentAcknowledgeRequest, IncidentResolveRequest
from ..observability.service import (
    acknowledge_incident,
    build_quality_and_risk_summary,
    create_alert_rule_view,
    get_device_view,
    get_execution_view,
    get_incident_view,
    get_observability_overview,
    get_replay_view,
    get_workflow_view,
    health_view,
    list_alert_rules_view,
    list_devices_view,
    list_incidents_view,
    list_quality_scores_view,
    list_risk_scores_view,
    list_executions_view,
    patch_alert_rule_view,
    reset_circuit_breaker_view,
    resolve_incident,
)


router = APIRouter(prefix="/api/v2/observability")
security_router = APIRouter(prefix="/api/v2/security")
health_router = APIRouter(prefix="/api/v2/observability")
replay_router = APIRouter(prefix="/api/v2")


def _require_observability_read(request: Request, db: Session):
    require_feature_enabled("EXECUTION_OBSERVABILITY_ENABLED")
    return require_observability_user(request, db)


def _require_observability_manage(request: Request, db: Session):
    require_feature_enabled("EXECUTION_OBSERVABILITY_ENABLED")
    return require_observability_manage_user(request, db)


@router.get("/overview")
def api_overview(request: Request, db: Session = Depends(get_db)):
    _require_observability_read(request, db)
    return get_observability_overview(db)


@router.get("/devices")
def api_devices(request: Request, device_id: str | None = None, db: Session = Depends(get_db)):
    _require_observability_read(request, db)
    return {"items": list_devices_view(db, device_id=device_id)}


@router.get("/devices/{device_id}")
def api_device_detail(device_id: str, request: Request, db: Session = Depends(get_db)):
    _require_observability_read(request, db)
    try:
        return get_device_view(db, device_id)
    except ObservabilityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/executions")
def api_executions(request: Request, execution_id: str | None = None, db: Session = Depends(get_db)):
    _require_observability_read(request, db)
    return {"items": list_executions_view(db, execution_id=execution_id)}


@router.get("/executions/{execution_id}")
def api_execution_detail(execution_id: str, request: Request, db: Session = Depends(get_db)):
    _require_observability_read(request, db)
    try:
        return get_execution_view(db, execution_id)
    except ObservabilityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}")
def api_workflow_detail(workflow_id: str, request: Request, db: Session = Depends(get_db)):
    _require_observability_read(request, db)
    try:
        return get_workflow_view(db, workflow_id)
    except ObservabilityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/quality-scores")
def api_quality_scores(request: Request, db: Session = Depends(get_db)):
    _require_observability_read(request, db)
    return {"items": list_quality_scores_view(db)}


@router.get("/risk-scores")
def api_risk_scores(request: Request, db: Session = Depends(get_db)):
    _require_observability_read(request, db)
    return {"items": list_risk_scores_view(db)}


@router.get("/execution-replays/{workflow_id}")
@replay_router.get("/execution-replays/{workflow_id}")
def api_execution_replay(workflow_id: str, request: Request, db: Session = Depends(get_db)):
    _require_observability_read(request, db)
    try:
        return get_replay_view(db, workflow_id)
    except ObservabilityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@health_router.get("/health")
def api_health(db: Session = Depends(get_db)):
    return health_view(db)


@security_router.get("/incidents")
def api_incidents(request: Request, db: Session = Depends(get_db)):
    _require_observability_read(request, db)
    return {"items": list_incidents_view(db)}


@security_router.get("/incidents/{incident_id}")
def api_incident_detail(incident_id: str, request: Request, db: Session = Depends(get_db)):
    _require_observability_read(request, db)
    try:
        return get_incident_view(db, incident_id)
    except ObservabilityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@security_router.post("/incidents/{incident_id}/acknowledge")
def api_acknowledge_incident(incident_id: str, payload: IncidentAcknowledgeRequest, request: Request, db: Session = Depends(get_db)):
    user = _require_observability_manage(request, db)
    try:
        return acknowledge_incident(db, incident_id, acknowledged_by=user.username, comment=payload.comment)
    except ObservabilityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@security_router.post("/incidents/{incident_id}/resolve")
def api_resolve_incident(incident_id: str, payload: IncidentResolveRequest, request: Request, db: Session = Depends(get_db)):
    user = _require_observability_manage(request, db)
    try:
        return resolve_incident(db, incident_id, resolved_by=user.username, resolution_summary=payload.resolution_summary)
    except ObservabilityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@security_router.get("/alert-rules")
def api_list_alert_rules(request: Request, db: Session = Depends(get_db)):
    _require_observability_read(request, db)
    return {"items": list_alert_rules_view(db)}


@security_router.post("/alert-rules")
def api_create_alert_rule(payload: AlertRuleCreateRequest, request: Request, db: Session = Depends(get_db)):
    user = _require_observability_manage(request, db)
    return create_alert_rule_view(db, payload.model_dump(), created_by=user.id)


@security_router.patch("/alert-rules/{rule_id}")
def api_patch_alert_rule(rule_id: str, payload: AlertRuleUpdateRequest, request: Request, db: Session = Depends(get_db)):
    _require_observability_manage(request, db)
    try:
        return patch_alert_rule_view(db, rule_id, payload.model_dump(exclude_none=True))
    except ObservabilityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@security_router.post("/circuit-breakers/{breaker_id}/reset")
def api_reset_breaker(breaker_id: str, request: Request, db: Session = Depends(get_db)):
    user = _require_observability_manage(request, db)
    return reset_circuit_breaker_view(db, breaker_id, reset_by=user.username)
