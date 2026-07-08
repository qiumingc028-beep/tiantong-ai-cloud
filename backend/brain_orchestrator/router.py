from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import require_permission_user
from ..models import User
from .orchestrator import analyze_goal, plan_dry_run, read_logs, read_task_graph
from .schemas import AnalyzePayload, PlanPayload


def analyze(payload: AnalyzePayload, request: Request, db: Session) -> dict:
    require_brain_orchestrator_user(request, db)
    return analyze_goal(payload.request_text)


def plan(payload: PlanPayload, request: Request, db: Session) -> dict:
    user = require_brain_orchestrator_user(request, db)
    return plan_dry_run(
        db,
        payload.request_text,
        created_by=user.username,
        boss_confirmed=payload.boss_confirmed,
        security_audited=payload.security_audited,
    )


def get_task(graph_id: str, request: Request, db: Session) -> dict:
    require_brain_orchestrator_user(request, db)
    row = read_task_graph(db, graph_id)
    if not row:
        raise HTTPException(status_code=404, detail="任务链不存在")
    return row


def logs(request: Request, db: Session) -> dict:
    require_brain_orchestrator_user(request, db)
    return {"logs": read_logs(db)}


def require_brain_orchestrator_user(request: Request, db: Session) -> User:
    return require_permission_user(request, db, "orchestrator.analyze")

