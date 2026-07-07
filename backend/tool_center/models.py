from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ToolRegistry(Base):
    __tablename__ = "tool_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    tool_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(120), nullable=False, default="internal")
    version: Mapped[str] = mapped_column(String(40), nullable=False, default="v1")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, default="low", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class EmployeeToolBinding(Base):
    __tablename__ = "employee_tool_binding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tool_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    permission_level: Mapped[str] = mapped_column(String(80), nullable=False, default="read_only", index=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    require_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)


class ToolExecutionLog(Base):
    __tablename__ = "tool_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    request: Mapped[str | None] = mapped_column(Text)
    response: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

