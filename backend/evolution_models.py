from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .models import TaskCenterTask


class EmployeeGrowth(Base):
    __tablename__ = "employee_growth"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), index=True)
    score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    growth_level: Mapped[str] = mapped_column(String(50), default="starter", nullable=False)
    success_rate: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    improvement_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    task: Mapped[TaskCenterTask | None] = relationship()


class ReviewAnalysis(Base):
    __tablename__ = "review_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    analysis_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    suggestion: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    task: Mapped[TaskCenterTask] = relationship()


class SkillSuggestion(Base):
    __tablename__ = "skill_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    skill_name: Mapped[str] = mapped_column(String(120), nullable=False)
    suggestion: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RiskEvent(Base):
    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(50), default="low", nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
