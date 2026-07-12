from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("device_code", name="uq_devices_device_code"),)

    device_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    chinese_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    device_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    operating_system: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    architecture: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    agent_version: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="待注册", index=True)
    trust_level: Mapped[str] = mapped_column(String(40), nullable=False, default="测试", index=True)
    environment_type: Mapped[str] = mapped_column(String(40), nullable=False, default="test", index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("ai_employees.id", ondelete="SET NULL"), index=True)
    registered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_ip_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    certificate_fingerprint: Mapped[str | None] = mapped_column(String(255), index=True)
    capabilities_json: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    credentials: Mapped[list["DeviceCredential"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    observation_sessions: Mapped[list["DeviceObservationSession"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    security_events: Mapped[list["DeviceSecurityEvent"]] = relationship(back_populates="device", cascade="all, delete-orphan")


class DeviceRegistrationToken(Base):
    __tablename__ = "device_registration_tokens"

    token_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    device_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    environment_type: Mapped[str] = mapped_column(String(40), nullable=False, default="test", index=True)
    allowed_capabilities_json: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class DeviceCredential(Base):
    __tablename__ = "device_credentials"
    __table_args__ = (UniqueConstraint("device_id", "credential_fingerprint", name="uq_device_credentials_device_fingerprint"),)

    credential_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False, index=True)
    credential_type: Mapped[str] = mapped_column(String(40), nullable=False, default="signature", index=True)
    credential_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="有效", index=True)
    public_key_fingerprint: Mapped[str | None] = mapped_column(String(255), index=True)
    last_nonce: Mapped[str | None] = mapped_column(String(255), index=True)
    last_request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    device: Mapped[Device] = relationship(back_populates="credentials")


class DeviceObservationSession(Base):
    __tablename__ = "device_observation_sessions"

    observation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False, index=True)
    computer_session_id: Mapped[str | None] = mapped_column(ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("ai_employees.id", ondelete="SET NULL"), index=True)
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="等待设备", index=True)
    allowed_applications_json: Mapped[str | None] = mapped_column(Text)
    allowed_windows_json: Mapped[str | None] = mapped_column(Text)
    observation_goal: Mapped[str | None] = mapped_column(Text)
    screenshot_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_screenshots: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    stop_reason: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    device: Mapped[Device] = relationship(back_populates="observation_sessions")
    events: Mapped[list["DeviceObservationEvent"]] = relationship(back_populates="observation", cascade="all, delete-orphan")


class DeviceObservationEvent(Base):
    __tablename__ = "device_observation_events"
    __table_args__ = (
        UniqueConstraint("observation_id", "sequence_number", name="uq_device_observation_events_sequence"),
    )

    observation_event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    observation_id: Mapped[str] = mapped_column(ForeignKey("device_observation_sessions.observation_id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    application_name: Mapped[str | None] = mapped_column(String(120), index=True)
    bundle_id: Mapped[str | None] = mapped_column(String(180), index=True)
    window_title: Mapped[str | None] = mapped_column(Text)
    screenshot_reference: Mapped[str | None] = mapped_column(Text)
    screenshot_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    screen_state: Mapped[str | None] = mapped_column(Text)
    risk_flags: Mapped[str | None] = mapped_column(Text)
    suggested_next_step: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)

    observation: Mapped[DeviceObservationSession] = relationship(back_populates="events")


class DeviceSecurityEvent(Base):
    __tablename__ = "device_security_events"

    security_event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.device_id", ondelete="SET NULL"), index=True)
    observation_id: Mapped[str | None] = mapped_column(ForeignKey("device_observation_sessions.observation_id", ondelete="SET NULL"), index=True)
    event_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    event_message: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    sensitive_data_involved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    device: Mapped[Device | None] = relationship(back_populates="security_events")
