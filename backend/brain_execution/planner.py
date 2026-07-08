from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from ..brain_orchestrator.planner import unique_employees
from ..brain_orchestrator.task_graph import build_task_graph
from ..brain_tool_router.models import BrainExecutionLog
from ..tool_center.gateway import clean_text
from ..tool_router.router_engine import check_route_permission
from .models import BrainApprovalRecord, BrainExecutionRun, BrainTaskEdge, BrainTaskNode, BrainToolCall


def analyze_goal(goal: str) -> dict:
    graph = build_task_graph(goal)
    return {
        "goal": graph.goal,
        "task_type": graph.task_type,
        "employees": unique_employees(graph),
        "tools": sorted({tool for node in graph.nodes for tool in node.required_tools}),
        "risk_level": graph.risk_level,
        "approval_required": graph.approval_required,
        "nodes": [node.model_dump() for node in graph.nodes],
        "edges": [edge.model_dump() for edge in graph.edges],
        "dry_run": True,
        "mode": "simulation",
    }


def create_plan(
    db: Session,
    goal: str,
    created_by: str | None = None,
    boss_confirm: bool = False,
    security_audited: bool = False,
) -> dict:
    graph = build_task_graph(goal)
    approval = approval_decision(graph.risk_level, boss_confirm=boss_confirm, security_audited=security_audited)
    run = BrainExecutionRun(
        goal=graph.goal,
        status="blocked" if approval["blocked"] else "planned",
        risk_level=graph.risk_level,
        approval_required=graph.approval_required,
        dry_run=True,
        created_by=clean_text(created_by)[:100],
    )
    db.add(run)
    db.flush()

    nodes = []
    edges = []
    tool_checks = []
    for node in graph.nodes:
        first_tool = node.required_tools[0] if node.required_tools else None
        status = "blocked" if graph.risk_level == "high" and approval["blocked"] else node.status
        row = BrainTaskNode(
            graph_id=f"run-{run.id}",
            execution_id=run.id,
            node_id=node.node_id,
            node_name=node.node_name,
            node_type=node.node_type,
            employee_code=node.employee_code,
            employee_name=node.employee_name,
            employee_role=node.employee_role,
            task_goal=node.task_goal,
            required_tools=to_json(node.required_tools),
            tool_name=first_tool,
            risk_level=node.risk_level,
            approval_required=node.approval_required,
            estimated_cost_level=node.estimated_cost_level,
            sequence_order=node.sequence_order,
            status=status,
        )
        db.add(row)
        nodes.append(node_to_dict(row))
        for tool_name in node.required_tools:
            decision = check_route_permission(
                db,
                node.employee_code,
                tool_name,
                boss_confirmed=boss_confirm,
                security_audited=security_audited,
            )
            call = BrainToolCall(
                execution_id=run.id,
                node_id=node.node_id,
                employee_code=node.employee_code,
                tool_name=tool_name,
                request_payload=to_json({"goal": graph.goal, "node_id": node.node_id}),
                response_payload=to_json({"mode": "simulation", "dry_run": True}),
                permission_result=to_json(decision),
                risk_level=clean_text(decision.get("risk_level") or node.risk_level),
                dry_run=True,
                status="allowed" if decision.get("allowed") else "denied",
            )
            db.add(call)
            tool_checks.append(tool_call_to_dict(call))

    for edge in graph.edges:
        row = BrainTaskEdge(
            graph_id=f"run-{run.id}",
            execution_id=run.id,
            source_node_id=edge.source_node_id,
            target_node_id=edge.target_node_id,
            edge_type=edge.edge_type,
            description=edge.description,
        )
        db.add(row)
        edges.append(edge_to_dict(row))

    db.add(
        BrainApprovalRecord(
            execution_id=run.id,
            node_id=None,
            approve_user=clean_text(created_by)[:100],
            decision="blocked" if approval["blocked"] else "not_required",
            reason=approval["reason"],
            boss_confirmed=boss_confirm,
            security_audited=security_audited,
        )
    )
    write_execution_log(
        db,
        run,
        action="plan_generated",
        status=run.status,
        output_data={"approval": approval, "dry_run": True},
    )
    db.commit()
    return get_task_chain(db, run.id) or {"execution_id": run.id}


def approve_run(
    db: Session,
    execution_id: int,
    approve_user: str | None,
    decision: str,
    reason: str | None,
    boss_confirm: bool,
    security_audited: bool,
) -> dict:
    run = db.get(BrainExecutionRun, execution_id)
    if not run:
        return {"error": "execution_not_found"}
    approval = approval_decision(run.risk_level, boss_confirm=boss_confirm, security_audited=security_audited)
    final_decision = clean_text(decision or "approved")
    if approval["blocked"]:
        final_decision = "blocked"
        run.status = "blocked"
    elif final_decision == "approved":
        run.status = "approved"
    db.add(
        BrainApprovalRecord(
            execution_id=run.id,
            approve_user=clean_text(approve_user)[:100],
            decision=final_decision,
            reason=clean_text(reason or approval["reason"]),
            boss_confirmed=boss_confirm,
            security_audited=security_audited,
        )
    )
    write_execution_log(db, run, action="approval_recorded", status=final_decision, output_data={"approval": approval})
    db.commit()
    return {"execution_id": run.id, "status": run.status, "decision": final_decision, "approval": approval}


def approval_decision(risk_level: str, boss_confirm: bool, security_audited: bool) -> dict:
    risk = clean_text(risk_level or "low")
    if risk == "high" and not (boss_confirm and security_audited):
        return {"blocked": True, "allowed": False, "reason": "高风险任务必须老板确认和天监审核", "risk_level": risk}
    if risk == "medium" and not boss_confirm:
        return {"blocked": True, "allowed": False, "reason": "中风险任务必须老板确认", "risk_level": risk}
    return {"blocked": False, "allowed": True, "reason": "审批条件满足或无需审批", "risk_level": risk}


def get_task_chain(db: Session, execution_id: int) -> dict | None:
    run = db.get(BrainExecutionRun, execution_id)
    if not run:
        return None
    nodes = (
        db.query(BrainTaskNode)
        .filter(BrainTaskNode.execution_id == execution_id)
        .order_by(BrainTaskNode.sequence_order.asc(), BrainTaskNode.id.asc())
        .all()
    )
    edges = db.query(BrainTaskEdge).filter(BrainTaskEdge.execution_id == execution_id).order_by(BrainTaskEdge.id.asc()).all()
    approvals = db.query(BrainApprovalRecord).filter(BrainApprovalRecord.execution_id == execution_id).order_by(BrainApprovalRecord.id.asc()).all()
    tool_calls = db.query(BrainToolCall).filter(BrainToolCall.execution_id == execution_id).order_by(BrainToolCall.id.asc()).all()
    return {
        "execution_id": run.id,
        "run": run_to_dict(run),
        "nodes": [node_to_dict(row) for row in nodes],
        "edges": [edge_to_dict(row) for row in edges],
        "approvals": [approval_to_dict(row) for row in approvals],
        "tool_calls": [tool_call_to_dict(row) for row in tool_calls],
        "dry_run": True,
        "mode": "simulation",
    }


def list_execution_logs(db: Session, employee_code: str | None = None) -> list[dict]:
    query = db.query(BrainExecutionLog).order_by(BrainExecutionLog.created_at.desc(), BrainExecutionLog.id.desc())
    if employee_code:
        query = query.filter(BrainExecutionLog.employee_code == employee_code)
    return [log_to_dict(row) for row in query.limit(100).all()]


def write_execution_log(
    db: Session,
    run: BrainExecutionRun,
    action: str,
    status: str,
    node_id: str | None = None,
    employee_code: str | None = None,
    input_data: Any | None = None,
    output_data: Any | None = None,
    error_message: str | None = None,
) -> BrainExecutionLog:
    row = BrainExecutionLog(
        user_request=run.goal,
        ai_analysis_result=to_json({"run_id": run.id, "risk_level": run.risk_level}),
        recommended_employee=employee_code,
        tool_selection=to_json({"dry_run": True}),
        approval_status=run.status,
        execution_result=status,
        run_id=str(run.id),
        node_id=node_id,
        employee_code=employee_code,
        action=action,
        input_data=to_json(input_data or {"goal": run.goal}),
        output_data=to_json(output_data or {"mode": "simulation", "dry_run": True}),
        status=status,
        error_message=clean_text(error_message),
    )
    db.add(row)
    return row


def run_to_dict(row: BrainExecutionRun) -> dict:
    return {
        "id": row.id,
        "goal": clean_text(row.goal),
        "status": clean_text(row.status),
        "risk_level": clean_text(row.risk_level),
        "approval_required": bool(row.approval_required),
        "dry_run": bool(row.dry_run),
        "created_by": clean_text(row.created_by),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def node_to_dict(row: BrainTaskNode) -> dict:
    return {
        "id": row.id,
        "execution_id": row.execution_id,
        "node_id": clean_text(row.node_id),
        "node_type": clean_text(row.node_type),
        "node_name": clean_text(row.node_name),
        "employee_code": clean_text(row.employee_code),
        "employee_name": clean_text(row.employee_name),
        "tool_name": clean_text(row.tool_name),
        "status": clean_text(row.status),
        "risk_level": clean_text(row.risk_level),
        "approval_required": bool(row.approval_required),
    }


def edge_to_dict(row: BrainTaskEdge) -> dict:
    return {
        "id": row.id,
        "execution_id": row.execution_id,
        "source_node_id": clean_text(row.source_node_id),
        "target_node_id": clean_text(row.target_node_id),
        "edge_type": clean_text(row.edge_type),
        "description": clean_text(row.description),
    }


def approval_to_dict(row: BrainApprovalRecord) -> dict:
    return {
        "id": row.id,
        "execution_id": row.execution_id,
        "node_id": clean_text(row.node_id),
        "approve_user": clean_text(row.approve_user),
        "decision": clean_text(row.decision),
        "reason": clean_text(row.reason),
        "boss_confirmed": bool(row.boss_confirmed),
        "security_audited": bool(row.security_audited),
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
    }


def tool_call_to_dict(row: BrainToolCall) -> dict:
    return {
        "id": row.id,
        "execution_id": row.execution_id,
        "node_id": clean_text(row.node_id),
        "employee_code": clean_text(row.employee_code),
        "tool_name": clean_text(row.tool_name),
        "permission_result": parse_json(row.permission_result),
        "risk_level": clean_text(row.risk_level),
        "dry_run": bool(row.dry_run),
        "status": clean_text(row.status),
    }


def log_to_dict(row: BrainExecutionLog) -> dict:
    return {
        "id": row.id,
        "run_id": clean_text(row.run_id),
        "node_id": clean_text(row.node_id),
        "employee_code": clean_text(row.employee_code or row.recommended_employee),
        "action": clean_text(row.action),
        "status": clean_text(row.status or row.execution_result),
        "input_data": parse_json(row.input_data),
        "output_data": parse_json(row.output_data),
        "error_message": clean_text(row.error_message),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:8000]


def parse_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return clean_text(value)

