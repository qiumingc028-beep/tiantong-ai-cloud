from __future__ import annotations

from sqlalchemy.orm import Session

from .planner import analyze_request, generate_plan, get_task_graph, list_logs


def analyze_goal(request_text: str) -> dict:
    return analyze_request(request_text)


def plan_dry_run(db: Session, request_text: str, created_by: str | None = None, boss_confirmed: bool = False, security_audited: bool = False) -> dict:
    return generate_plan(
        db,
        request_text,
        created_by=created_by,
        boss_confirmed=boss_confirmed,
        security_audited=security_audited,
    )


def read_task_graph(db: Session, graph_id: str) -> dict | None:
    return get_task_graph(db, graph_id)


def read_logs(db: Session) -> list[dict]:
    return list_logs(db)

