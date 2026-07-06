from __future__ import annotations

from typing import Optional
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .models import User


class OrchestratorAnalysisRecord(Base):
    __tablename__ = "orchestrator_analysis_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    input_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detected_employee_code: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    detected_employee_name: Mapped[Optional[str]] = mapped_column(String(100))
    detected_sprint: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    detected_stage: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    completion_status: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    has_blocker: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    needs_fix: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confidence: Mapped[Optional[str]] = mapped_column(String(50))
    recommended_codex: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    recommended_action: Mapped[Optional[str]] = mapped_column(Text)
    prompt_draft: Mapped[Optional[str]] = mapped_column(Text)
    safety_flags_json: Mapped[Optional[str]] = mapped_column(Text)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    created_by: Mapped[Optional[User]] = relationship()


class OrchestratorPromptConfirmation(Base):
    __tablename__ = "orchestrator_prompt_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_record_id: Mapped[int] = mapped_column(
        ForeignKey("orchestrator_analysis_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    confirmed_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    target_codex: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    confirm_status: Mapped[str] = mapped_column(String(50), nullable=False)
    confirmed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    note: Mapped[Optional[str]] = mapped_column(Text)

    analysis_record: Mapped[OrchestratorAnalysisRecord] = relationship()
    confirmed_by: Mapped[Optional[User]] = relationship()


class OrchestratorTaskLink(Base):
    __tablename__ = "orchestrator_task_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analysis_record_id: Mapped[int] = mapped_column(
        ForeignKey("orchestrator_analysis_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[int] = mapped_column(
        ForeignKey("task_center_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    link_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    recommended_codex: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    recommended_action: Mapped[Optional[str]] = mapped_column(String(100))
    source_stage: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    confidence: Mapped[Optional[str]] = mapped_column(String(50))
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    analysis_record: Mapped[OrchestratorAnalysisRecord] = relationship()
    created_by: Mapped[Optional[User]] = relationship()
