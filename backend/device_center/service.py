from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..ai_employees.registry import normalize_employee_code
from ..auth_data import normalize_role
from ..config import get_settings
from ..models import AiEmployee, User
from ..agent_runtime.executors.computer.models import ComputerSession
from ..skills_engine.models import Skill
from ..skills_engine.permissions import get_flag as get_skill_flag
from .authentication import consume_registration_token, make_device_fingerprint, remember_nonce, verify_signature, create_registration_token_record, utcnow
from .audit import json_text, record_security_event, redact_sensitive
from .constants import (
    DEFAULT_MAC_ALLOWED_APPLICATIONS,
    DEFAULT_MAC_ALLOWED_WINDOW_PATTERNS,
    DEFAULT_MAC_BLOCKED_APPLICATIONS,
    DEFAULT_MAC_BLOCKED_WINDOW_PATTERNS,
    DEVICE_SECURITY_EVENT_CODES,
)
from .heartbeat import mark_online
from .models import (
    Device,
    DeviceCredential,
    DeviceObservationEvent,
    DeviceObservationSession,
    DeviceRegistrationToken,
    DeviceSecurityEvent,
)
from .permissions import require_feature_enabled
from .registry import default_allowed_applications, default_allowed_windows, default_blocked_applications, default_blocked_windows, normalize_list
from .session import append_observation_event, create_observation_session, observation_finished_status
from device_agents.macos_observer.sanitizer import sanitize_window
from device_agents.macos_observer.window_provider import WindowSnapshot


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except Exception:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return value if isinstance(value, list) else [str(value)]


def _device_to_dict(device: Device) -> dict[str, Any]:
    return {
        "device_id": device.device_id,
        "device_code": device.device_code,
        "chinese_name": device.chinese_name,
        "device_type": device.device_type,
        "operating_system": device.operating_system,
        "architecture": device.architecture,
        "agent_version": device.agent_version,
        "status": device.status,
        "trust_level": device.trust_level,
        "environment_type": device.environment_type,
        "owner_id": device.owner_id,
        "registered_by": device.registered_by,
        "approved_by": device.approved_by,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "last_ip_hash": device.last_ip_hash,
        "certificate_fingerprint": device.certificate_fingerprint,
        "capabilities": _parse_json_list(device.capabilities_json),
        "enabled": device.enabled,
        "revoked_at": device.revoked_at.isoformat() if device.revoked_at else None,
        "created_at": device.created_at.isoformat() if device.created_at else None,
        "updated_at": device.updated_at.isoformat() if device.updated_at else None,
    }


def _observation_to_dict(observation: DeviceObservationSession) -> dict[str, Any]:
    return {
        "observation_id": observation.observation_id,
        "device_id": observation.device_id,
        "computer_session_id": observation.computer_session_id,
        "task_id": observation.task_id,
        "employee_id": observation.employee_id,
        "skill_id": observation.skill_id,
        "status": observation.status,
        "allowed_applications": _parse_json_list(observation.allowed_applications_json),
        "allowed_windows": _parse_json_list(observation.allowed_windows_json),
        "observation_goal": observation.observation_goal,
        "screenshot_count": observation.screenshot_count,
        "max_screenshots": observation.max_screenshots,
        "started_at": observation.started_at.isoformat() if observation.started_at else None,
        "expires_at": observation.expires_at.isoformat() if observation.expires_at else None,
        "finished_at": observation.finished_at.isoformat() if observation.finished_at else None,
        "stop_reason": observation.stop_reason,
        "trace_id": observation.trace_id,
        "created_at": observation.created_at.isoformat() if observation.created_at else None,
        "updated_at": observation.updated_at.isoformat() if observation.updated_at else None,
    }


def _event_to_dict(event: DeviceObservationEvent) -> dict[str, Any]:
    risk_flags = _parse_json_list(event.risk_flags)
    return {
        "observation_event_id": event.observation_event_id,
        "observation_id": event.observation_id,
        "sequence_number": event.sequence_number,
        "application_name": event.application_name,
        "bundle_id": event.bundle_id,
        "window_title": event.window_title,
        "screenshot_reference": event.screenshot_reference,
        "screenshot_hash": event.screenshot_hash,
        "screen_state": event.screen_state,
        "risk_flags": risk_flags,
        "suggested_next_step": event.suggested_next_step,
        "captured_at": event.captured_at.isoformat() if event.captured_at else None,
        "duration_ms": event.duration_ms,
        "trace_id": event.trace_id,
    }


def get_device_center_health(db: Session) -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "healthy",
        "ok": True,
        "feature_flags": {
            "DEVICE_CENTER_ENABLED": settings.DEVICE_CENTER_ENABLED,
            "MAC_DEVICE_AGENT_ENABLED": settings.MAC_DEVICE_AGENT_ENABLED,
            "MAC_READONLY_OBSERVER_ENABLED": settings.MAC_READONLY_OBSERVER_ENABLED,
            "MAC_WINDOW_ENUMERATION_ENABLED": settings.MAC_WINDOW_ENUMERATION_ENABLED,
            "MAC_SCREEN_CAPTURE_ENABLED": settings.MAC_SCREEN_CAPTURE_ENABLED,
            "LOCAL_VISION_PROVIDER_ENABLED": settings.LOCAL_VISION_PROVIDER_ENABLED,
            "EXTERNAL_VISION_PROVIDER_ENABLED": settings.EXTERNAL_VISION_PROVIDER_ENABLED,
        },
        "summary": {
            "devices": db.query(Device).count(),
            "online": db.query(Device).filter(Device.status == "在线").count(),
            "observations": db.query(DeviceObservationSession).count(),
            "events": db.query(DeviceObservationEvent).count(),
            "security_events": db.query(DeviceSecurityEvent).count(),
        },
        "defaults": {
            "allowed_applications": list(DEFAULT_MAC_ALLOWED_APPLICATIONS),
            "blocked_applications": list(DEFAULT_MAC_BLOCKED_APPLICATIONS),
            "allowed_windows": list(DEFAULT_MAC_ALLOWED_WINDOW_PATTERNS),
            "blocked_windows": list(DEFAULT_MAC_BLOCKED_WINDOW_PATTERNS),
        },
    }


def list_devices(db: Session, *, limit: int = 100) -> dict[str, Any]:
    rows = db.query(Device).order_by(Device.created_at.desc()).limit(limit).all()
    return {"readonly": True, "items": [_device_to_dict(row) for row in rows], "total": len(rows)}


def get_device(db: Session, device_id: str) -> dict[str, Any]:
    device = db.query(Device).filter(Device.device_id == device_id).one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="测试设备不存在")
    return {"device": _device_to_dict(device)}


def create_registration_token(db: Session, payload: dict[str, Any], *, created_by: int | None = None) -> dict[str, Any]:
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    row, token = create_registration_token_record(
        db,
        device_type=payload["device_type"],
        environment_type=payload.get("environment_type") or "test",
        allowed_capabilities=payload.get("allowed_capabilities") or [],
        expires_in_minutes=int(payload.get("expires_in_minutes") or 30),
        created_by=created_by,
    )
    return {
        "token": {
            "token_id": row.token_id,
            "device_type": row.device_type,
            "environment_type": row.environment_type,
            "registration_token": token,
            "expires_at": row.expires_at.isoformat(),
            "created_at": row.created_at.isoformat(),
        }
    }


def register_device(db: Session, payload: dict[str, Any], *, registered_by: int | None = None) -> dict[str, Any]:
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    token_row = consume_registration_token(db, payload["registration_token"])
    if token_row.device_type != payload["device_type"]:
        raise HTTPException(status_code=400, detail="设备类型与注册令牌不匹配")
    fingerprint = make_device_fingerprint(payload["device_code"], payload["certificate_fingerprint"], payload["nonce"], payload["timestamp"])
    verify_signature(
        payload["certificate_fingerprint"],
        payload["device_code"],
        payload["nonce"],
        payload["timestamp"],
        payload["signature"],
        path="/api/v2/devices/register",
    )
    device = db.query(Device).filter(Device.device_code == payload["device_code"]).one_or_none()
    if device:
        raise HTTPException(status_code=409, detail="设备编码已存在")
    owner = None
    if payload.get("owner_employee_code"):
        owner = db.query(AiEmployee).filter(AiEmployee.employee_code == normalize_employee_code(payload["owner_employee_code"])).one_or_none()
    device = Device(
        device_id=str(uuid4()),
        device_code=payload["device_code"],
        chinese_name=payload["chinese_name"],
        device_type=payload["device_type"],
        operating_system=payload["operating_system"],
        architecture=payload["architecture"],
        agent_version=payload["agent_version"],
        status="等待批准",
        trust_level=payload.get("trust_level") or "测试",
        environment_type=payload.get("environment_type") or token_row.environment_type,
        owner_id=owner.id if owner else None,
        registered_by=registered_by,
        certificate_fingerprint=payload["certificate_fingerprint"],
        capabilities_json=json_text(payload.get("capabilities") or _parse_json_list(token_row.allowed_capabilities_json) or []),
        enabled=False,
    )
    db.add(device)
    db.flush()
    credential = DeviceCredential(
        credential_id=str(uuid4()),
        device_id=device.device_id,
        credential_type="signature",
        credential_fingerprint=fingerprint,
        status="有效",
        public_key_fingerprint=payload.get("public_key_fingerprint") or payload["certificate_fingerprint"],
    )
    db.add(credential)
    db.commit()
    db.refresh(device)
    return {"device": _device_to_dict(device), "credential_fingerprint": credential.credential_fingerprint}


def approve_device(db: Session, device_id: str, *, approved_by: int | None = None, trust_level: str | None = None, environment_type: str | None = None, reason: str | None = None) -> dict[str, Any]:
    device = db.query(Device).filter(Device.device_id == device_id).one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="测试设备不存在")
    device.status = "已批准"
    device.enabled = True
    if trust_level:
        device.trust_level = trust_level
    if environment_type:
        device.environment_type = environment_type
    device.approved_by = approved_by
    device.approved_at = utcnow()
    record_security_event(db, device_id=device.device_id, observation_id=None, event_code="DEVICE_APPROVED", event_message=reason or "测试设备已批准", risk_level="低", sensitive_data_involved=False, trace_id=None)
    db.commit()
    db.refresh(device)
    return {"device": _device_to_dict(device)}


def disable_device(db: Session, device_id: str, *, approved_by: int | None = None, reason: str | None = None) -> dict[str, Any]:
    device = db.query(Device).filter(Device.device_id == device_id).one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="测试设备不存在")
    device.enabled = False
    device.status = "已禁用"
    device.approved_by = approved_by or device.approved_by
    record_security_event(db, device_id=device.device_id, observation_id=None, event_code="DEVICE_DISABLED", event_message=reason or "测试设备已禁用", risk_level="中", sensitive_data_involved=False, trace_id=None)
    db.commit()
    db.refresh(device)
    return {"device": _device_to_dict(device)}


def revoke_device(db: Session, device_id: str, *, approved_by: int | None = None, reason: str | None = None) -> dict[str, Any]:
    device = db.query(Device).filter(Device.device_id == device_id).one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="测试设备不存在")
    device.enabled = False
    device.status = "已撤销"
    device.revoked_at = utcnow()
    device.approved_by = approved_by or device.approved_by
    for credential in device.credentials:
        credential.status = "已撤销"
        credential.revoked_at = utcnow()
    record_security_event(db, device_id=device.device_id, observation_id=None, event_code="DEVICE_REVOKED", event_message=reason or "测试设备已撤销", risk_level="高", sensitive_data_involved=False, trace_id=None)
    db.commit()
    db.refresh(device)
    return {"device": _device_to_dict(device)}


def heartbeat_device(db: Session, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    device = db.query(Device).filter(Device.device_id == device_id).one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="测试设备不存在")
    if not device.enabled or device.status in {"已禁用", "已撤销"}:
        raise HTTPException(status_code=403, detail="设备当前不可用")
    credential = device.credentials[0] if device.credentials else None
    if not credential:
        raise HTTPException(status_code=403, detail="设备缺少认证凭据")
    verify_signature(
        credential.credential_fingerprint,
        device.device_code,
        payload["nonce"],
        payload["timestamp"],
        payload["signature"],
        path=f"/api/v2/devices/{device.device_id}/heartbeat",
    )
    remember_nonce(db, credential, payload["nonce"])
    mark_online(device, ip_hash=payload.get("last_ip_hash"), agent_version=payload.get("agent_version"), capabilities_json=json_text(payload.get("capabilities") or _parse_json_list(device.capabilities_json)))
    db.commit()
    db.refresh(device)
    return {"device": _device_to_dict(device)}


def create_observation(db: Session, device_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    require_feature_enabled("DEVICE_CENTER_ENABLED")
    device = db.query(Device).filter(Device.device_id == device_id).one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="测试设备不存在")
    if device.status not in {"已批准", "在线"} or not device.enabled:
        raise HTTPException(status_code=403, detail="设备尚未批准或已禁用")
    allowed_applications = normalize_list(payload.get("allowed_applications")) or default_allowed_applications()
    allowed_windows = normalize_list(payload.get("allowed_windows")) or default_allowed_windows()
    observation = create_observation_session(
        device.device_id,
        task_id=payload.get("task_id"),
        employee_id=payload.get("employee_id"),
        skill_id=payload.get("skill_id"),
        computer_session_id=payload.get("computer_session_id"),
        observation_goal=payload.get("observation_goal"),
        allowed_applications=allowed_applications,
        allowed_windows=allowed_windows,
        max_screenshots=int(payload.get("max_screenshots") or 3),
        expires_in_minutes=int(payload.get("expires_in_minutes") or 30),
        trace_id=payload.get("trace_id"),
    )
    if payload.get("windows"):
        blocked_detected = False
        for index, window in enumerate(payload["windows"], start=1):
            snapshot = WindowSnapshot(
                application_name=str(window.get("application_name") or ""),
                bundle_id=str(window.get("bundle_id") or ""),
                window_title=str(window.get("window_title") or ""),
                width=window.get("width"),
                height=window.get("height"),
                frontmost=bool(window.get("frontmost", index == 1)),
                screenshot_allowed=bool(window.get("screenshot_allowed", True)),
                metadata=window.get("metadata") or {},
            )
            sanitized = sanitize_window(snapshot)
            observation_event = append_observation_event(
                observation,
                application_name=sanitized.application_name,
                bundle_id=sanitized.bundle_id,
                window_title=sanitized.window_title,
                screenshot_reference=None if sanitized.blocked or not snapshot.screenshot_allowed else window.get("screenshot_reference") or f"screenshot://{uuid4().hex[:24]}",
                screen_state=payload.get("screen_state") or ("敏感窗口阻断" if sanitized.blocked else "页面状态正常"),
                risk_flags=list(window.get("risk_flags") or []) + ([sanitized.blocked_reason] if sanitized.blocked_reason else []),
                suggested_next_step="请求人工处理敏感窗口" if sanitized.blocked else (window.get("suggested_next_step") or "继续只读观察"),
                trace_id=payload.get("trace_id"),
            )
            if sanitized.blocked:
                blocked_detected = True
            db.add(observation_event)
        if blocked_detected:
            observation.status = "敏感内容阻断"
            observation.stop_reason = "检测到敏感窗口"
        else:
            observation.status = "执行中" if observation.events else "等待设备"
    observation.status = observation.status or ("执行中" if observation.events else "等待设备")
    db.add(observation)
    db.commit()
    db.refresh(observation)
    return {"observation": _observation_to_dict(observation), "events": [_event_to_dict(row) for row in observation.events]}


def list_observations(db: Session, *, device_id: str | None = None, limit: int = 100) -> dict[str, Any]:
    query = db.query(DeviceObservationSession)
    if device_id:
        query = query.filter(DeviceObservationSession.device_id == device_id)
    rows = query.order_by(DeviceObservationSession.created_at.desc()).limit(limit).all()
    return {"readonly": True, "items": [_observation_to_dict(row) for row in rows], "total": len(rows)}


def get_observation(db: Session, observation_id: str) -> dict[str, Any]:
    row = db.query(DeviceObservationSession).filter(DeviceObservationSession.observation_id == observation_id).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="观察会话不存在")
    return {"observation": _observation_to_dict(row)}


def cancel_observation(db: Session, observation_id: str, *, reason: str | None = None) -> dict[str, Any]:
    row = db.query(DeviceObservationSession).filter(DeviceObservationSession.observation_id == observation_id).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="观察会话不存在")
    row.status = "已取消"
    row.stop_reason = reason or "用户取消"
    row.finished_at = utcnow()
    db.commit()
    db.refresh(row)
    return {"observation": _observation_to_dict(row)}


def get_observation_events(db: Session, observation_id: str) -> dict[str, Any]:
    row = db.query(DeviceObservationSession).filter(DeviceObservationSession.observation_id == observation_id).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="观察会话不存在")
    events = db.query(DeviceObservationEvent).filter(DeviceObservationEvent.observation_id == observation_id).order_by(DeviceObservationEvent.sequence_number.asc()).all()
    return {"items": [_event_to_dict(item) for item in events], "readonly": True}


def get_windows_for_device(db: Session, device_id: str) -> dict[str, Any]:
    device = db.query(Device).filter(Device.device_id == device_id).one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="测试设备不存在")
    latest = (
        db.query(DeviceObservationSession)
        .filter(DeviceObservationSession.device_id == device_id)
        .order_by(DeviceObservationSession.created_at.desc())
        .first()
    )
    windows = []
    if latest:
        for event in latest.events:
            windows.append({
                "application_name": event.application_name,
                "bundle_id": event.bundle_id,
                "window_title": event.window_title,
                "screenshot_allowed": True,
            })
    return {
        "readonly": True,
        "device_id": device_id,
        "items": windows,
        "summary": {
            "device_status": device.status,
            "allowed_applications": _parse_json_list(latest.allowed_applications_json) if latest and latest.allowed_applications_json else default_allowed_applications(),
            "blocked_applications": default_blocked_applications(),
            "allowed_windows": _parse_json_list(latest.allowed_windows_json) if latest and latest.allowed_windows_json else default_allowed_windows(),
            "blocked_windows": default_blocked_windows(),
        },
    }


def _device_has_capability(device: Device, capability: str) -> bool:
    capabilities = _parse_json_list(device.capabilities_json)
    return capability in capabilities


def record_device_observation_from_snapshot(db: Session, device_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    return create_observation(db, device_id, snapshot)
