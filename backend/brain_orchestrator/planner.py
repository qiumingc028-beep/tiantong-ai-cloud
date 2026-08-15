from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from ..models import Store, User, UserStoreMembership
from ..tool_center.gateway import clean_text
from ..tool_router.router_engine import check_route_permission
from .models import BrainOrchestratorLog, BrainTaskEdge, BrainTaskGraph, BrainTaskNode
from .schemas import TaskGraph
from .task_graph import build_task_graph


class BrainGraphIdentityConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class GraphOwnershipScope:
    tenant_id: int
    company_id: int
    requester_id: int
    store_scope_key: str
    ownership_scope_key: str


def resolve_graph_ownership(db: Session, user: User) -> GraphOwnershipScope:
    store_ids = [
        row[0]
        for row in (
            db.query(UserStoreMembership.store_id)
            .join(Store, Store.id == UserStoreMembership.store_id)
            .filter(
                UserStoreMembership.user_id == user.id,
                UserStoreMembership.active.is_(True),
                UserStoreMembership.can_read.is_(True),
                Store.active.is_(True),
                Store.tenant_id == user.tenant_id,
                Store.company_id == user.company_id,
            )
            .order_by(UserStoreMembership.store_id.asc())
        )
    ]
    store_scope_key = json.dumps(
        {"store_ids": store_ids} if store_ids else {"unassigned_user_id": user.id},
        sort_keys=True,
        separators=(",", ":"),
    )
    ownership_scope_key = hashlib.sha256(
        json.dumps(
            {
                "tenant_id": user.tenant_id,
                "company_id": user.company_id,
                "requester_id": user.id,
                "store_scope": json.loads(store_scope_key),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return GraphOwnershipScope(
        tenant_id=user.tenant_id,
        company_id=user.company_id,
        requester_id=user.id,
        store_scope_key=store_scope_key,
        ownership_scope_key=ownership_scope_key,
    )


def _semantic_hash(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


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


def generate_plan(
    db: Session,
    request_text: str,
    *,
    user: User,
    execution_identity: str | None = None,
    boss_confirmed: bool = False,
    security_audited: bool = False,
) -> dict:
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
    scope = resolve_graph_ownership(db, user)
    semantic_payload_json = json.dumps(
        {
            "goal": graph.goal,
            "task_type": graph.task_type,
            "nodes": plan["nodes"],
            "edges": plan["edges"],
            "tool_router_results": plan["tool_router_results"],
            "approval_nodes": plan["approval_nodes"],
            "risk_level": plan["risk_level"],
            "approval_required": plan["approval_required"],
            "estimated_cost_level": plan["estimated_cost_level"],
            "status": plan["status"],
            "requester_id": user.id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    semantic_hash = _semantic_hash(semantic_payload_json)
    normalized_execution_identity = clean_text(execution_identity)
    execution_scope_key = f"trace:{normalized_execution_identity}" if normalized_execution_identity else f"plan:{semantic_hash}"
    canonical_graph = persist_plan(
        db,
        graph,
        plan,
        scope=scope,
        execution_scope_key=execution_scope_key,
        semantic_hash=semantic_hash,
        semantic_payload_json=semantic_payload_json,
        created_by=user.username,
    )
    plan["graph_id"] = canonical_graph.graph_id
    return plan


def get_task_graph(db: Session, graph_id: str, *, user: User) -> dict | None:
    scope = resolve_graph_ownership(db, user)
    graph = db.query(BrainTaskGraph).filter(
        BrainTaskGraph.graph_id == graph_id,
        *_ownership_filters(scope),
    ).one_or_none()
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


def list_logs(db: Session, *, user: User) -> list[dict]:
    scope = resolve_graph_ownership(db, user)
    rows = (
        db.query(BrainOrchestratorLog)
        .join(BrainTaskGraph, BrainTaskGraph.graph_id == BrainOrchestratorLog.graph_id)
        .filter(*_ownership_filters(scope))
        .order_by(BrainOrchestratorLog.created_at.desc(), BrainOrchestratorLog.id.desc())
        .limit(100)
        .all()
    )
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


def persist_plan(
    db: Session,
    graph: TaskGraph,
    plan: dict,
    *,
    scope: GraphOwnershipScope,
    execution_scope_key: str,
    semantic_hash: str,
    semantic_payload_json: str,
    created_by: str | None = None,
) -> BrainTaskGraph:
    graph.graph_id = f"graph-{uuid4().hex}"
    canonical_graph: BrainTaskGraph | None = None
    graph_values = {
        "graph_id": graph.graph_id,
        "ownership_scope_key": scope.ownership_scope_key,
        "execution_scope_key": execution_scope_key,
        "semantic_hash": semantic_hash,
        "semantic_payload_json": semantic_payload_json,
        "tenant_id": scope.tenant_id,
        "company_id": scope.company_id,
        "store_scope_key": scope.store_scope_key,
        "requester_id": scope.requester_id,
        "user_request": graph.goal,
        "goal": graph.goal,
        "task_type": graph.task_type,
        "risk_level": graph.risk_level,
        "approval_required": graph.approval_required,
        "estimated_cost_level": graph.estimated_cost_level,
        "status": plan["status"],
        "dry_run": True,
        "created_by": clean_text(created_by)[:100],
    }
    if db.get_bind().dialect.name == "postgresql":
        inserted_graph_id = db.execute(
            postgresql_insert(BrainTaskGraph)
            .values(**graph_values)
            .on_conflict_do_nothing(constraint="uq_brain_task_graph_scope_execution_semantic")
            .returning(BrainTaskGraph.id)
        ).scalar_one_or_none()
        graph_created = inserted_graph_id is not None
    else:
        graph_created = not _canonical_graph_query(
            db, scope, execution_scope_key, semantic_hash
        ).with_entities(BrainTaskGraph.id).first()
        if graph_created:
            canonical_graph = BrainTaskGraph(**graph_values)
            db.add(canonical_graph)
    if graph_created:
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
    if canonical_graph is None:
        canonical_graph = _canonical_graph_query(
            db, scope, execution_scope_key, semantic_hash
        ).one_or_none()
    if canonical_graph is None:
        raise RuntimeError("并发创建的 BrainTaskGraph 无法回读")
    if canonical_graph.semantic_payload_json != semantic_payload_json:
        raise BrainGraphIdentityConflict("BrainTaskGraph 完整语义身份冲突")
    db.add(
        BrainOrchestratorLog(
            graph_id=canonical_graph.graph_id,
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
    db.refresh(canonical_graph)
    return canonical_graph


def _canonical_graph_query(
    db: Session,
    scope: GraphOwnershipScope,
    execution_scope_key: str,
    semantic_hash: str,
):
    return db.query(BrainTaskGraph).filter(
        *_ownership_filters(scope),
        BrainTaskGraph.execution_scope_key == execution_scope_key,
        BrainTaskGraph.semantic_hash == semantic_hash,
    )


def _ownership_filters(scope: GraphOwnershipScope):
    return (
        BrainTaskGraph.ownership_scope_key == scope.ownership_scope_key,
        BrainTaskGraph.tenant_id == scope.tenant_id,
        BrainTaskGraph.company_id == scope.company_id,
        BrainTaskGraph.requester_id == scope.requester_id,
        BrainTaskGraph.store_scope_key == scope.store_scope_key,
    )


def bind_graph_to_run(db: Session, *, graph_id: str, run_id: str, user: User) -> BrainTaskGraph:
    scope = resolve_graph_ownership(db, user)
    graph = db.query(BrainTaskGraph).filter(
        BrainTaskGraph.graph_id == graph_id,
        *_ownership_filters(scope),
    ).one_or_none()
    if graph is None:
        raise BrainGraphIdentityConflict("BrainTaskGraph 所有权范围不匹配")
    if graph.canonical_run_id not in {None, run_id}:
        raise BrainGraphIdentityConflict("BrainTaskGraph 已绑定其他 canonical Run")
    graph.canonical_run_id = run_id
    return graph


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
