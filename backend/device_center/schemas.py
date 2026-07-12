from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DeviceRegistrationTokenCreate(BaseModel):
    device_type: str = Field(min_length=1, max_length=50)
    environment_type: str = Field(default="test", max_length=40)
    allowed_capabilities: list[str] = Field(default_factory=list)
    expires_in_minutes: int = Field(default=30, ge=1, le=24 * 60)


class DeviceRegisterPayload(BaseModel):
    registration_token: str = Field(min_length=8, max_length=512)
    device_code: str = Field(min_length=2, max_length=80)
    chinese_name: str = Field(min_length=1, max_length=200)
    device_type: str = Field(min_length=1, max_length=50)
    operating_system: str = Field(min_length=1, max_length=80)
    architecture: str = Field(min_length=1, max_length=40)
    agent_version: str = Field(min_length=1, max_length=50)
    trust_level: str = Field(default="测试", max_length=40)
    environment_type: str = Field(default="test", max_length=40)
    owner_employee_code: str | None = Field(default=None, max_length=80)
    certificate_fingerprint: str = Field(min_length=8, max_length=255)
    public_key_fingerprint: str | None = Field(default=None, max_length=255)
    nonce: str = Field(min_length=8, max_length=255)
    timestamp: str = Field(min_length=8, max_length=120)
    signature: str = Field(min_length=8, max_length=255)
    capabilities: list[str] = Field(default_factory=list)


class DeviceApprovalPayload(BaseModel):
    trust_level: str | None = Field(default=None, max_length=40)
    environment_type: str | None = Field(default=None, max_length=40)
    reason: str | None = Field(default=None, max_length=500)


class DeviceHeartbeatPayload(BaseModel):
    nonce: str = Field(min_length=8, max_length=255)
    timestamp: str = Field(min_length=8, max_length=120)
    signature: str = Field(min_length=8, max_length=255)
    last_ip_hash: str | None = Field(default=None, max_length=128)
    agent_version: str | None = Field(default=None, max_length=50)
    capabilities: list[str] | None = None


class DeviceObservationCreate(BaseModel):
    task_id: int | None = None
    employee_id: int | None = None
    skill_id: int | None = None
    computer_session_id: str | None = None
    observation_goal: str | None = None
    allowed_applications: list[str] = Field(default_factory=list)
    allowed_windows: list[str] = Field(default_factory=list)
    max_screenshots: int = Field(default=3, ge=1, le=20)
    expires_in_minutes: int = Field(default=30, ge=1, le=24 * 60)
    trace_id: str | None = Field(default=None, max_length=120)
    windows: list[dict[str, Any]] = Field(default_factory=list)
    screen_state: str | None = None
    suggested_next_step: str | None = None


class DeviceObservationCancel(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class DeviceWindowSnapshot(BaseModel):
    application_name: str
    bundle_id: str
    window_title: str
    width: int | None = None
    height: int | None = None
    frontmost: bool = False
    screenshot_allowed: bool = True


class DeviceWindowRead(BaseModel):
    application_name: str
    bundle_id: str | None = None
    window_title: str | None = None
    width: int | None = None
    height: int | None = None
    frontmost: bool = False
    screenshot_allowed: bool = True
    blocked_reason: str | None = None


class DeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device_id: str
    device_code: str
    chinese_name: str
    device_type: str
    operating_system: str
    architecture: str
    agent_version: str
    status: str
    trust_level: str
    environment_type: str
    owner_id: int | None = None
    registered_by: int | None = None
    approved_by: int | None = None
    last_seen_at: datetime | None = None
    last_ip_hash: str | None = None
    certificate_fingerprint: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    enabled: bool = True
    revoked_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DeviceRegistrationTokenRead(BaseModel):
    token_id: str
    device_type: str
    environment_type: str
    registration_token: str
    expires_at: datetime
    created_at: datetime


class DeviceObservationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    observation_event_id: str
    observation_id: str
    sequence_number: int
    application_name: str | None = None
    bundle_id: str | None = None
    window_title: str | None = None
    screenshot_reference: str | None = None
    screenshot_hash: str | None = None
    screen_state: str | None = None
    risk_flags: list[str] = Field(default_factory=list)
    suggested_next_step: str | None = None
    captured_at: datetime | None = None
    duration_ms: int | None = None
    trace_id: str | None = None


class DeviceObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    observation_id: str
    device_id: str
    computer_session_id: str | None = None
    task_id: int | None = None
    employee_id: int | None = None
    skill_id: int | None = None
    status: str
    allowed_applications: list[str] = Field(default_factory=list)
    allowed_windows: list[str] = Field(default_factory=list)
    observation_goal: str | None = None
    screenshot_count: int = 0
    max_screenshots: int = 3
    started_at: datetime | None = None
    expires_at: datetime | None = None
    finished_at: datetime | None = None
    stop_reason: str | None = None
    trace_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

