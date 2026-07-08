from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class BrainExecutionLog(Base):
    __tablename__ = "brain_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_request: Mapped[str] = mapped_column(Text, nullable=False)
    ai_analysis_result: Mapped[str | None] = mapped_column(Text)
    recommended_employee: Mapped[str | None] = mapped_column(String(100), index=True)
    tool_selection: Mapped[str | None] = mapped_column(Text)
    approval_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_checked", index=True)
    execution_result: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(String(80), index=True)
    node_id: Mapped[str | None] = mapped_column(String(120), index=True)
    employee_code: Mapped[str | None] = mapped_column(String(100), index=True)
    action: Mapped[str | None] = mapped_column(String(120))
    input_data: Mapped[str | None] = mapped_column(Text)
    output_data: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(40), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
