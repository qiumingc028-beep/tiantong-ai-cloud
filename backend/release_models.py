from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ReleaseVersion(Base):
    __tablename__ = "release_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    sprint_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    commit_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    branch: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    author: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    approved_by: Mapped[str | None] = mapped_column(String(100))
    deploy_status: Mapped[str] = mapped_column(String(50), default="waiting", nullable=False, index=True)
