"""sprint23 brain orchestrator

Revision ID: 0022_sprint23_brain_orchestrator
Revises: 0021_sprint22_brain_tool_router
Create Date: 2026-07-08
"""
from alembic import op
import sqlalchemy as sa


revision = "0022_sprint23_brain_orchestrator"
down_revision = "0021_sprint22_brain_tool_router"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return _inspector().has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(index["name"] == index_name for index in _inspector().get_indexes(table_name))


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade():
    if not _has_table("brain_task_graphs"):
        op.create_table(
            "brain_task_graphs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("graph_id", sa.String(120), nullable=False, unique=True),
            sa.Column("user_request", sa.Text(), nullable=False),
            sa.Column("goal", sa.Text(), nullable=False),
            sa.Column("task_type", sa.String(80), nullable=False),
            sa.Column("risk_level", sa.String(40), nullable=False, server_default="low"),
            sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("estimated_cost_level", sa.String(40), nullable=False, server_default="low"),
            sa.Column("status", sa.String(40), nullable=False, server_default="planned"),
            sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.String(100)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    for name, columns in {
        "ix_brain_task_graphs_graph_id": ["graph_id"],
        "ix_brain_task_graphs_task_type": ["task_type"],
        "ix_brain_task_graphs_risk_level": ["risk_level"],
        "ix_brain_task_graphs_approval_required": ["approval_required"],
        "ix_brain_task_graphs_estimated_cost_level": ["estimated_cost_level"],
        "ix_brain_task_graphs_status": ["status"],
        "ix_brain_task_graphs_dry_run": ["dry_run"],
        "ix_brain_task_graphs_created_by": ["created_by"],
        "ix_brain_task_graphs_created_at": ["created_at"],
    }.items():
        _create_index_if_missing(name, "brain_task_graphs", columns)

    if not _has_table("brain_task_nodes"):
        op.create_table(
            "brain_task_nodes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("graph_id", sa.String(120), nullable=False),
            sa.Column("node_id", sa.String(120), nullable=False),
            sa.Column("node_name", sa.String(160), nullable=False),
            sa.Column("node_type", sa.String(80), nullable=False),
            sa.Column("employee_code", sa.String(100), nullable=False),
            sa.Column("employee_name", sa.String(120), nullable=False),
            sa.Column("employee_role", sa.String(160), nullable=False),
            sa.Column("task_goal", sa.Text(), nullable=False),
            sa.Column("required_tools", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("risk_level", sa.String(40), nullable=False, server_default="low"),
            sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("estimated_cost_level", sa.String(40), nullable=False, server_default="low"),
            sa.Column("sequence_order", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("status", sa.String(40), nullable=False, server_default="planned"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    for name, columns in {
        "ix_brain_task_nodes_graph_id": ["graph_id"],
        "ix_brain_task_nodes_node_id": ["node_id"],
        "ix_brain_task_nodes_node_type": ["node_type"],
        "ix_brain_task_nodes_employee_code": ["employee_code"],
        "ix_brain_task_nodes_risk_level": ["risk_level"],
        "ix_brain_task_nodes_approval_required": ["approval_required"],
        "ix_brain_task_nodes_estimated_cost_level": ["estimated_cost_level"],
        "ix_brain_task_nodes_sequence_order": ["sequence_order"],
        "ix_brain_task_nodes_status": ["status"],
        "ix_brain_task_nodes_created_at": ["created_at"],
    }.items():
        _create_index_if_missing(name, "brain_task_nodes", columns)

    if not _has_table("brain_task_edges"):
        op.create_table(
            "brain_task_edges",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("graph_id", sa.String(120), nullable=False),
            sa.Column("source_node_id", sa.String(120), nullable=False),
            sa.Column("target_node_id", sa.String(120), nullable=False),
            sa.Column("edge_type", sa.String(80), nullable=False, server_default="passes_result_to"),
            sa.Column("description", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    for name, columns in {
        "ix_brain_task_edges_graph_id": ["graph_id"],
        "ix_brain_task_edges_source_node_id": ["source_node_id"],
        "ix_brain_task_edges_target_node_id": ["target_node_id"],
        "ix_brain_task_edges_edge_type": ["edge_type"],
        "ix_brain_task_edges_created_at": ["created_at"],
    }.items():
        _create_index_if_missing(name, "brain_task_edges", columns)

    if not _has_table("brain_orchestrator_logs"):
        op.create_table(
            "brain_orchestrator_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("graph_id", sa.String(120)),
            sa.Column("user_request", sa.Text(), nullable=False),
            sa.Column("brain_analysis", sa.Text()),
            sa.Column("task_graph", sa.Text()),
            sa.Column("orchestrator_plan", sa.Text()),
            sa.Column("tool_router_result", sa.Text()),
            sa.Column("approval_nodes", sa.Text()),
            sa.Column("risk_summary", sa.Text()),
            sa.Column("execution_result", sa.String(80), nullable=False, server_default="dry_run_plan_generated"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
    _create_index_if_missing("ix_brain_orchestrator_logs_graph_id", "brain_orchestrator_logs", ["graph_id"])
    _create_index_if_missing("ix_brain_orchestrator_logs_execution_result", "brain_orchestrator_logs", ["execution_result"])
    _create_index_if_missing("ix_brain_orchestrator_logs_created_at", "brain_orchestrator_logs", ["created_at"])


def downgrade():
    for table_name in ("brain_orchestrator_logs", "brain_task_edges", "brain_task_nodes", "brain_task_graphs"):
        if _has_table(table_name):
            op.drop_table(table_name)

