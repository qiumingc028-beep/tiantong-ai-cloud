from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..tool_center.gateway import clean_text
from ..tool_router.router_engine import check_route_permission
from .models import BrainOrchestratorLog, BrainTaskEdge, BrainTaskGraph, BrainTaskNode
from .schemas import TaskGraph
from .task_graph import build_task_graph


def analyze_request(request_text: str) -> dict:
    graph = build_task_graph(request_text)
    return {
        "goal": graph.goal,
        "task_type": graph.task_type,
        "tasks": [node.model_dump() for node in graph.nodes],
        "employees": unique_employees(graph),
        "tools": sorted({tool for node in graph.nodes for tool in node.required_tools}),
        "risk_level": graph.risk_level,
        "approval_required": graph.approval_required,
        "estimated_cost_level": graph.estimated_cost_level,
        "dry_run": True,
    }


def generate_plan(db: Session, request_text: str, created_by: str | None = None, boss_confirmed: bool = False, security_audited: bool = False) -> dict:
    graph = build_task_graph(request_text)
    approval = approval_summary(graph, boss_confirmed, security_audited)
    tool_results = check_graph_tools(db, graph, boss_confirmed=boss_confirmed, security_audited=security_audited)
    blocked = approval["blocked"] or any(not item["allowed"] and item["risk_level"] == "high" for item in tool_results)
    plan = {
        "graph_id": graph.graph_id,
        "goal": graph.goal,
        "execution_order": [node.node_id for node in graph.nodes],
        "nodes": [node.model_dump() for node in graph.nodes],
        "edges": [edge.model_dump() for edge in graph.edges],
        "tool_router_results": tool_results,
        "approval_nodes": approval["approval_nodes"],
        "risk_level": graph.risk_level,
        "approval_required": graph.approval_required,
        "estimated_cost_level": graph.estimated_cost_level,
        "status": "blocked" if blocked else "planned",
        "dry_run": True,
        "mode": "simulation",
    }
    persist_plan(db, graph, plan, created_by=created_by)
    return plan


def get_task_graph(db: Session, graph_id: str) -> dict | None:
    graph = db.query(BrainTaskGraph).filter(BrainTaskGraph.graph_id == graph_id).first()
    if not graph:
        return None
    nodes = (
        db.query(BrainTaskNode)
        .filter(BrainTaskNode.graph_id == graph_id)
        .order_by(BrainTaskNode.sequence_order.asc(), BrainTaskNode.id.asc())
        .all()
    )
    edges = db.query(BrainTaskEdge).filter(BrainTaskEdge.graph_id == graph_id).order_by(BrainTaskEdge.id.asc()).all()
    return {
        "graph": graph_to_dict(graph),
        "nodes": [node_to_dict(row) for row in nodes],
        "edges": [edge_to_dict(row) for row in edges],
        "dry_run": True,
    }


def list_logs(db: Session) -> list[dict]:
    rows = db.query(BrainOrchestratorLog).order_by(BrainOrchestratorLog.created_at.desc(), BrainOrchestratorLog.id.desc()).limit(100).all()
    return [log_to_dict(row) for row in rows]


def approval_summary(graph: TaskGraph, boss_confirmed: bool, security_audited: bool) -> dict:
    nodes = [node for node in graph.nodes if node.approval_required]
    if graph.risk_level == "high" and not (boss_confirmed and security_audited):
        return {"blocked": True, "approval_nodes": [node.node_id for node in nodes], "reason": "高风险任务必须老板确认和天监审核"}
    if graph.risk_level == "medium" and not boss_confirmed:
        return {"blocked": True, "approval_nodes": [node.node_id for node in nodes], "reason": "中风险任务需要老板确认"}
    return {"blocked": False, "approval_nodes": [node.node_id for node in nodes], "reason": "审批条件满足或无需审批"}


def check_graph_tools(db: Session, graph: TaskGraph, boss_confirmed: bool, security_audited: bool) -> list[dict]:
    results = []
    for node in graph.nodes:
        for tool_name in node.required_tools:
            decision = check_route_permission(
                db,
                node.employee_code,
                tool_name,
                boss_confirmed=boss_confirmed,
                security_audited=security_audited,
            )
            results.append(
                {
                    "node_id": node.node_id,
                    "employee_code": node.employee_code,
                    "tool_name": tool_name,
                    "allowed": bool(decision.get("allowed", False)),
                    "require_approval": bool(decision.get("require_approval", True)),
                    "risk_level": decision.get("risk_level") or "unknown",
                    "reason": decision.get("reason"),
                    "mode": "simulation",
                }
            )
    return results


def persist_plan(db: Session, graph: TaskGraph, plan: dict, created_by: str | None = None) -> None:
    existing_graph = db.query(BrainTaskGraph).filter(BrainTaskGraph.graph_id == graph.graph_id).first()
    if not existing_graph:
        db.add(
            BrainTaskGraph(
                graph_id=graph.graph_id,
                user_request=graph.goal,
                goal=graph.goal,
                task_type=graph.task_type,
                risk_level=graph.risk_level,
                approval_required=graph.approval_required,
                estimated_cost_level=graph.estimated_cost_level,
                status=plan["status"],
                dry_run=True,
                created_by=clean_text(created_by)[:100],
            )
        )
        for node in graph.nodes:
            db.add(
                BrainTaskNode(
                    graph_id=graph.graph_id,
                    node_id=node.node_id,
                    node_name=node.node_name,
                    node_type=node.node_type,
                    employee_code=node.employee_code,
                    employee_name=node.employee_name,
                    employee_role=node.employee_role,
                    task_goal=node.task_goal,
                    required_tools=to_json(node.required_tools),
                    risk_level=node.risk_level,
                    approval_required=node.approval_required,
                    estimated_cost_level=node.estimated_cost_level,
                    sequence_order=node.sequence_order,
                    status=node.status,
                )
            )
        for edge in graph.edges:
            db.add(
                BrainTaskEdge(
                    graph_id=graph.graph_id,
                    source_node_id=edge.source_node_id,
                    target_node_id=edge.target_node_id,
                    edge_type=edge.edge_type,
                    description=edge.description,
                )
            )
    db.add(
        BrainOrchestratorLog(
            graph_id=graph.graph_id,
            user_request=graph.goal,
            brain_analysis=to_json(analyze_request(graph.goal)),
            task_graph=to_json({"nodes": [node.model_dump() for node in graph.nodes], "edges": [edge.model_dump() for edge in graph.edges]}),
            orchestrator_plan=to_json({"execution_order": plan["execution_order"], "status": plan["status"], "dry_run": True}),
            tool_router_result=to_json(plan["tool_router_results"]),
            approval_nodes=to_json(plan["approval_nodes"]),
            risk_summary=to_json({"risk_level": plan["risk_level"], "approval_required": plan["approval_required"]}),
            execution_result="blocked_dry_run" if plan["status"] == "blocked" else "dry_run_plan_generated",
        )
    )
    db.commit()


def unique_employees(graph: TaskGraph) -> list[dict]:
    seen = set()
    employees = []
    for node in graph.nodes:
        if node.employee_code in seen:
            continue
        seen.add(node.employee_code)
        employees.append(
            {
                "employee_code": node.employee_code,
                "employee_name": node.employee_name,
                "employee_role": node.employee_role,
                "reason": node.task_goal,
            }
        )
    return employees


def graph_to_dict(row: BrainTaskGraph) -> dict:
    return {
        "id": row.id,
        "graph_id": clean_text(row.graph_id),
        "goal": clean_text(row.goal),
        "task_type": clean_text(row.task_type),
        "risk_level": clean_text(row.risk_level),
        "approval_required": bool(row.approval_required),
        "estimated_cost_level": clean_text(row.estimated_cost_level),
        "status": clean_text(row.status),
        "dry_run": bool(row.dry_run),
        "created_by": clean_text(row.created_by),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def node_to_dict(row: BrainTaskNode) -> dict:
    return {
        "id": row.id,
        "graph_id": clean_text(row.graph_id),
        "node_id": clean_text(row.node_id),
        "node_name": clean_text(row.node_name),
        "node_type": clean_text(row.node_type),
        "employee_code": clean_text(row.employee_code),
        "employee_name": clean_text(row.employee_name),
        "employee_role": clean_text(row.employee_role),
        "task_goal": clean_text(row.task_goal),
        "required_tools": parse_json(row.required_tools),
        "risk_level": clean_text(row.risk_level),
        "approval_required": bool(row.approval_required),
        "estimated_cost_level": clean_text(row.estimated_cost_level),
        "sequence_order": row.sequence_order,
        "status": clean_text(row.status),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def edge_to_dict(row: BrainTaskEdge) -> dict:
    return {
        "id": row.id,
        "graph_id": clean_text(row.graph_id),
        "source_node_id": clean_text(row.source_node_id),
        "target_node_id": clean_text(row.target_node_id),
        "edge_type": clean_text(row.edge_type),
        "description": clean_text(row.description),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def log_to_dict(row: BrainOrchestratorLog) -> dict:
    return {
        "id": row.id,
        "graph_id": clean_text(row.graph_id),
        "user_request": clean_text(row.user_request),
        "brain_analysis": parse_json(row.brain_analysis),
        "task_graph": parse_json(row.task_graph),
        "orchestrator_plan": parse_json(row.orchestrator_plan),
        "tool_router_result": parse_json(row.tool_router_result),
        "approval_nodes": parse_json(row.approval_nodes),
        "risk_summary": parse_json(row.risk_summary),
        "execution_result": clean_text(row.execution_result),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:8000]


def parse_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return clean_text(value)

