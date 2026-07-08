from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class BrainTaskGraph(Base):
    __tablename__ = "brain_task_graphs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    user_request: Mapped[str] = mapped_column(Text, nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, default="low", index=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    estimated_cost_level: Mapped[str] = mapped_column(String(40), nullable=False, default="low", index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="planned", index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(100), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class BrainTaskNode(Base):
    __tablename__ = "brain_task_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    node_name: Mapped[str] = mapped_column(String(160), nullable=False)
    node_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    employee_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    employee_name: Mapped[str] = mapped_column(String(120), nullable=False)
    employee_role: Mapped[str] = mapped_column(String(160), nullable=False)
    task_goal: Mapped[str] = mapped_column(Text, nullable=False)
    required_tools: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    risk_level: Mapped[str] = mapped_column(String(40), nullable=False, default="low", index=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    estimated_cost_level: Mapped[str] = mapped_column(String(40), nullable=False, default="low", index=True)
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="planned", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class BrainTaskEdge(Base):
    __tablename__ = "brain_task_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    graph_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_node_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    target_node_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    edge_type: Mapped[str] = mapped_column(String(80), nullable=False, default="passes_result_to", index=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class BrainOrchestratorLog(Base):
    __tablename__ = "brain_orchestrator_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    graph_id: Mapped[str | None] = mapped_column(String(120), index=True)
    user_request: Mapped[str] = mapped_column(Text, nullable=False)
    brain_analysis: Mapped[str | None] = mapped_column(Text)
    task_graph: Mapped[str | None] = mapped_column(Text)
    orchestrator_plan: Mapped[str | None] = mapped_column(Text)
    tool_router_result: Mapped[str | None] = mapped_column(Text)
    approval_nodes: Mapped[str | None] = mapped_column(Text)
    risk_summary: Mapped[str | None] = mapped_column(Text)
    execution_result: Mapped[str] = mapped_column(String(80), nullable=False, default="dry_run_plan_generated", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

