from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..device_center.authentication import utcnow
from ..device_center.permissions import require_device_center_manage_user, require_device_center_user, require_feature_enabled
from ..device_center.schemas import (
    DeviceApprovalPayload,
    DeviceHeartbeatPayload,
    DeviceObservationCancel,
    DeviceObservationCreate,
    DeviceRegisterPayload,
    DeviceRegistrationTokenCreate,
)
from ..device_center.service import (
    approve_device,
    cancel_observation,
    create_observation,
    create_registration_token,
    disable_device,
    get_device,
    get_device_center_health,
    get_observation,
    get_observation_events,
    get_windows_for_device,
    heartbeat_device,
    list_devices,
    list_observations,
    register_device,
    revoke_device,
)


router = APIRouter(prefix="/api/v2/devices")
observation_router = APIRouter(prefix="/api/v2/device-observations")
health_router = APIRouter(prefix="/api/v2/device-center")


@router.get("")
def api_list_devices(request: Request, limit: int = 100, db: Session = Depends(get_db)):
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    require_device_center_user(request, db)
    return list_devices(db, limit=limit)


@router.post("/register-token")
def api_create_registration_token(payload: DeviceRegistrationTokenCreate, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    user = require_device_center_manage_user(request, db)
    return create_registration_token(db, payload.model_dump(), created_by=user.id)


@router.post("/register")
def api_register_device(payload: DeviceRegisterPayload, db: Session = Depends(get_db)):
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    return register_device(db, payload.model_dump())


@router.get("/{device_id}")
def api_get_device(device_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    require_device_center_user(request, db)
    return get_device(db, device_id)


@router.post("/{device_id}/approve")
def api_approve_device(device_id: str, payload: DeviceApprovalPayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    user = require_device_center_manage_user(request, db)
    return approve_device(db, device_id, approved_by=user.id, trust_level=payload.trust_level, environment_type=payload.environment_type, reason=payload.reason)


@router.post("/{device_id}/disable")
def api_disable_device(device_id: str, payload: DeviceApprovalPayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    user = require_device_center_manage_user(request, db)
    return disable_device(db, device_id, approved_by=user.id, reason=payload.reason)


@router.post("/{device_id}/revoke")
def api_revoke_device(device_id: str, payload: DeviceApprovalPayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    user = require_device_center_manage_user(request, db)
    return revoke_device(db, device_id, approved_by=user.id, reason=payload.reason)


@router.post("/{device_id}/heartbeat")
def api_heartbeat(device_id: str, payload: DeviceHeartbeatPayload, db: Session = Depends(get_db)):
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    return heartbeat_device(db, device_id, payload.model_dump())


@router.get("/{device_id}/windows")
def api_list_windows(device_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    require_device_center_user(request, db)
    return get_windows_for_device(db, device_id)


@router.post("/{device_id}/observations")
def api_create_observation(device_id: str, payload: DeviceObservationCreate, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    require_device_center_manage_user(request, db)
    return create_observation(db, device_id, payload.model_dump())


@router.get("/observations")
@observation_router.get("")
def api_list_observations(request: Request, device_id: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    require_device_center_user(request, db)
    return list_observations(db, device_id=device_id, limit=limit)


@router.get("/observations/{observation_id}")
@observation_router.get("/{observation_id}")
def api_get_observation(observation_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    require_device_center_user(request, db)
    return get_observation(db, observation_id)


@router.post("/observations/{observation_id}/cancel")
@observation_router.post("/{observation_id}/cancel")
def api_cancel_observation(observation_id: str, payload: DeviceObservationCancel, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    require_device_center_manage_user(request, db)
    return cancel_observation(db, observation_id, reason=payload.reason)


@router.get("/observations/{observation_id}/events")
@observation_router.get("/{observation_id}/events")
def api_get_observation_events(observation_id: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    require_device_center_user(request, db)
    return get_observation_events(db, observation_id)


@health_router.get("/health")
def api_device_center_health(request: Request, db: Session = Depends(get_db)):
    require_device_center_user(request, db)
    return get_device_center_health(db)
