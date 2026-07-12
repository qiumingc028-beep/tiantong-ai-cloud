from __future__ import annotations

import hashlib
import json
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import DeviceCredential, DeviceRegistrationToken


@dataclass(frozen=True)
class DeviceAuthContext:
    device_code: str
    nonce: str
    timestamp: str
    signature: str
    material: str


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_registration_token_record(db: Session, *, device_type: str, environment_type: str, allowed_capabilities: list[str], expires_in_minutes: int, created_by: int | None = None) -> tuple[DeviceRegistrationToken, str]:
    token = f"dtok_{uuid4().hex}_{uuid4().hex}"
    row = DeviceRegistrationToken(
        token_id=str(uuid4()),
        token_hash=token_hash(token),
        device_type=device_type,
        environment_type=environment_type,
        allowed_capabilities_json=json.dumps(allowed_capabilities, ensure_ascii=False),
        expires_at=utcnow() + timedelta(minutes=expires_in_minutes),
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, token


def consume_registration_token(db: Session, token_value: str) -> DeviceRegistrationToken:
    hashed = token_hash(token_value)
    row = db.query(DeviceRegistrationToken).filter(DeviceRegistrationToken.token_hash == hashed).one_or_none()
    if not row:
        raise HTTPException(status_code=403, detail="注册令牌无效")
    if row.revoked_at is not None:
        raise HTTPException(status_code=403, detail="注册令牌已撤销")
    if row.used_at is not None:
        raise HTTPException(status_code=403, detail="注册令牌已使用")
    expires_at = row.expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= utcnow():
        raise HTTPException(status_code=403, detail="注册令牌已过期")
    row.used_at = utcnow()
    db.commit()
    db.refresh(row)
    return row


def make_device_fingerprint(device_code: str, certificate_fingerprint: str, nonce: str, timestamp: str) -> str:
    material = f"{device_code}:{certificate_fingerprint}:{nonce}:{timestamp}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def make_request_signature(secret_like_material: str, device_code: str, nonce: str, timestamp: str, *, path: str = "") -> str:
    payload = f"{device_code}:{nonce}:{timestamp}:{path}"
    return hmac.new(secret_like_material.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(secret_like_material: str, device_code: str, nonce: str, timestamp: str, signature: str, *, path: str = "") -> None:
    expected = make_request_signature(secret_like_material, device_code, nonce, timestamp, path=path)
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="设备签名校验失败")


def remember_nonce(db: Session, credential: DeviceCredential, nonce: str) -> None:
    if credential.last_nonce and credential.last_nonce == nonce:
        raise HTTPException(status_code=409, detail="请求重放被拒绝")
    credential.last_nonce = nonce
    credential.last_request_at = utcnow()
    db.commit()
