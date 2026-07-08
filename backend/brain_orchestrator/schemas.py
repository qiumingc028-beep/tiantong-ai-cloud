from __future__ import annotations

from pydantic import BaseModel, Field


class AnalyzePayload(BaseModel):
    request_text: str = Field(min_length=1, max_length=2000)


class PlanPayload(BaseModel):
    request_text: str = Field(min_length=1, max_length=2000)
    boss_confirmed: bool = False
    security_audited: bool = False


class TaskGraphNode(BaseModel):
    node_id: str
    node_name: str
    node_type: str
    employee_code: str
    employee_name: str
    employee_role: str
    task_goal: str
    required_tools: list[str]
    risk_level: str
    approval_required: bool
    estimated_cost_level: str
    sequence_order: int
    status: str = "planned"


class TaskGraphEdge(BaseModel):
    source_node_id: str
    target_node_id: str
    edge_type: str = "passes_result_to"
    description: str | None = None


class TaskGraph(BaseModel):
    graph_id: str
    goal: str
    task_type: str
    risk_level: str
    approval_required: bool
    estimated_cost_level: str
    dry_run: bool = True
    nodes: list[TaskGraphNode]
    edges: list[TaskGraphEdge]

