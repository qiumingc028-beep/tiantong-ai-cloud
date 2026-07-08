from __future__ import annotations

from sqlalchemy.orm import Session

from ..tool_center.gateway import clean_text
from .models import BrainApprovalRecord, BrainExecutionRun, BrainTaskNode
from .planner import approval_decision, get_task_chain, write_execution_log


def start_dry_run(db: Session, execution_id: int) -> dict:
    run = db.get(BrainExecutionRun, execution_id)
    if not run:
        return {"error": "execution_not_found"}

    approval = latest_approval(db, run.id)
    decision = approval_decision(
        run.risk_level,
        boss_confirm=bool(approval and approval.boss_confirmed),
        security_audited=bool(approval and approval.security_audited),
    )
    if decision["blocked"]:
        run.status = "blocked"
        write_execution_log(db, run, action="dry_run_blocked", status="blocked", output_data={"approval": decision})
        db.commit()
        return {"execution_id": run.id, "status": "blocked", "dry_run": True, "approval": decision}

    run.status = "running"
    nodes = (
        db.query(BrainTaskNode)
        .filter(BrainTaskNode.execution_id == execution_id)
        .order_by(BrainTaskNode.sequence_order.asc(), BrainTaskNode.id.asc())
        .all()
    )
    completed = []
    for node in nodes:
        node.status = "completed"
        write_execution_log(
            db,
            run,
            action="node_simulated",
            status="completed",
            node_id=node.node_id,
            employee_code=node.employee_code,
            input_data={"task_goal": node.task_goal, "tool_name": node.tool_name},
            output_data={"result": f"{clean_text(node.node_name)} dry-run completed", "dry_run": True},
        )
        completed.append(node.node_id)
    run.status = "completed"
    write_execution_log(db, run, action="dry_run_completed", status="completed", output_data={"completed_nodes": completed})
    db.commit()
    return get_task_chain(db, run.id) or {"execution_id": run.id, "status": run.status, "dry_run": True}


def latest_approval(db: Session, execution_id: int) -> BrainApprovalRecord | None:
    return (
        db.query(BrainApprovalRecord)
        .filter(BrainApprovalRecord.execution_id == execution_id)
        .order_by(BrainApprovalRecord.id.desc())
        .first()
    )

