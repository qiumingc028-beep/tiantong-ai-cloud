from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class DeployRecord(Base):
    __tablename__ = "deploy_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deploy_id: Mapped[str | None] = mapped_column(String(100), index=True)
    version: Mapped[str | None] = mapped_column(String(100))
    commit_id: Mapped[str | None] = mapped_column(String(100))
    deploy_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deploy_status: Mapped[str | None] = mapped_column(String(50), index=True)
    deploy_version: Mapped[str | None] = mapped_column(String(100))
    commit_hash: Mapped[str | None] = mapped_column(String(100))
    branch: Mapped[str | None] = mapped_column(String(100))
    operator: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="initialized", nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DeployHealthCheck(Base):
    __tablename__ = "deploy_health_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    check_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    message: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HealthCheckRecord(Base):
    __tablename__ = "health_check_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    latency: Mapped[int | None] = mapped_column(Integer)
