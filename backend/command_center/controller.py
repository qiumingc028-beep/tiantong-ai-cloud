from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.agent_meeting import create_meeting, list_meetings
from backend.autonomy.task_monitor import monitor_business_state
from backend.auth import require_permission_user
from backend.command_center.orchestration_view import command_history, command_status, employee_logs_from_commands, new_command_id, operations_snapshot, save_command_record, utc_now
from backend.command_center.task_parser import parse_command
from backend.core.orchestrator import handle_event
from backend.database import get_db
from backend.decision_center import evaluate_business_decisions, list_decisions
from backend.employee_capability import match_employee_for_task
from backend.knowledge_center import learn_from_execution, search_knowledge
from backend.learning_center import analyze_execution, optimize_prompt_suggestions, score_employees
from backend.security.tian_shen import evaluate_command
from backend.strategy_engine import route_strategy, select_best_strategy
from backend.workflow.router import route_event


router = APIRouter(prefix="/command")


class CommandSubmit(BaseModel):
    command: str
    metadata: dict[str, Any] | None = None


class AutonomyScan(BaseModel):
    snapshot: dict[str, Any] | None = None
    auto_create: bool = True


class DecisionEvaluate(BaseModel):
    snapshot: dict[str, Any] | None = None


class MeetingCreate(BaseModel):
    goal: str
    context: dict[str, Any] | None = None
    invitees: list[str] | None = None


class StrategyPlan(BaseModel):
    goal: str
    context: dict[str, Any] | None = None
    invitees: list[str] | None = None
    submit_to_queue: bool = False


class LearningAnalyze(BaseModel):
    command_id: str | None = None
    goal: str | None = None
    logs: list[dict[str, Any]] | None = None


class KnowledgeLearn(BaseModel):
    learning_report: dict[str, Any] | None = None
    command_id: str | None = None
    goal: str | None = None
    logs: list[dict[str, Any]] | None = None


class CapabilityMatch(BaseModel):
    task: dict[str, Any]


def require_command_user(request: Request, db: Session):
    return require_permission_user(request, db, "task_center.manage")


def require_command_reader(request: Request, db: Session):
    return require_permission_user(request, db, "task_center.read")


def create_command_from_text(command: str, metadata: dict[str, Any] | None, submitted_by: str) -> dict[str, Any]:
    parsed = parse_command(command, metadata)
    command_id = new_command_id()
    dispatches = []
    event_ids = []
    for step in parsed["steps"]:
        event = {
            "source": "command_center",
            "target": step["employee_code"],
            "action": "execute_employee_skill",
            "payload": {
                "task_id": 0,
                "task_type": step["task_type"],
                "task_input": {
                    "command_id": command_id,
                    "step_id": step["step_id"],
                    "role": step["role"],
                    "input": step["input"],
                },
            },
        }
        result = handle_event(event)
        dispatches.append(result)
        if result.get("event_id"):
            event_ids.append(result["event_id"])

    record = save_command_record(
        {
            "command_id": command_id,
            "command": command,
            "status": "submitted",
            "submitted_by": submitted_by,
            "parsed": parsed,
            "dispatches": dispatches,
            "event_ids": event_ids,
            "created_at": utc_now(),
        }
    )
    return record


@router.post("/submit")
def submit_command(payload: CommandSubmit, request: Request, db: Session = Depends(get_db)):
    user = require_command_user(request, db)
    record = create_command_from_text(payload.command, payload.metadata, getattr(user, "username", "unknown"))
    return {"ok": True, "command": record}


@router.get("/status")
def get_status(command_id: str, request: Request, db: Session = Depends(get_db)):
    require_command_reader(request, db)
    status = command_status(command_id)
    if not status:
        raise HTTPException(status_code=404, detail="command not found")
    return {"ok": True, "command": status}


@router.get("/history")
def get_history(request: Request, db: Session = Depends(get_db), limit: int = 20):
    require_command_reader(request, db)
    safe_limit = min(max(limit, 1), 50)
    return {"ok": True, "commands": command_history(safe_limit)}


@router.get("/operations")
def get_operations(request: Request, db: Session = Depends(get_db), limit: int = 50):
    require_command_reader(request, db)
    safe_limit = min(max(limit, 1), 100)
    return {"ok": True, "operations": operations_snapshot(safe_limit)}


@router.get("/logs")
def get_logs(request: Request, db: Session = Depends(get_db), limit: int = 50):
    require_command_reader(request, db)
    safe_limit = min(max(limit, 1), 100)
    commands = command_history(safe_limit)
    return {"ok": True, "logs": employee_logs_from_commands(commands)[:safe_limit]}


@router.get("/autonomy/opportunities")
def get_autonomy_opportunities(request: Request, db: Session = Depends(get_db)):
    require_command_reader(request, db)
    return {"ok": True, "monitor": monitor_business_state()}


@router.post("/autonomy/scan")
def scan_autonomous_workflow(payload: AutonomyScan, request: Request, db: Session = Depends(get_db)):
    user = require_command_user(request, db)
    monitor = monitor_business_state(payload.snapshot)
    commands = []
    if payload.auto_create:
        for opportunity in monitor["opportunities"]:
            command = create_command_from_text(
                opportunity["command"],
                {
                    "source": "autonomous_monitor",
                    "opportunity_id": opportunity["opportunity_id"],
                    "source_signal": opportunity["source_signal"],
                    "recommended_team": opportunity["recommended_team"],
                    "workflow_stages": opportunity["lifecycle"],
                    "approval_required": opportunity["approval_required"],
                    "learning_goal": opportunity["learning_goal"],
                },
                getattr(user, "username", "unknown"),
            )
            commands.append(command)
    return {"ok": True, "monitor": monitor, "commands": commands}


@router.post("/decision/evaluate")
def evaluate_decision_center(payload: DecisionEvaluate, request: Request, db: Session = Depends(get_db)):
    require_command_user(request, db)
    monitor = monitor_business_state(payload.snapshot)
    decision = evaluate_business_decisions(monitor["opportunities"])
    return {"ok": True, "monitor": monitor, "decision": decision}


@router.get("/decision/history")
def get_decision_history(request: Request, db: Session = Depends(get_db), limit: int = 20):
    require_command_reader(request, db)
    return {"ok": True, "decisions": list_decisions(limit)}


@router.post("/meeting/create")
def create_agent_meeting(payload: MeetingCreate, request: Request, db: Session = Depends(get_db)):
    require_command_user(request, db)
    meeting = create_meeting(payload.goal, payload.context, payload.invitees)
    return {"ok": True, "meeting": meeting}


@router.get("/meeting/history")
def get_agent_meeting_history(request: Request, db: Session = Depends(get_db), limit: int = 20):
    require_command_reader(request, db)
    return {"ok": True, "meetings": list_meetings(limit)}


@router.post("/strategy/plan")
def plan_strategy_loop(payload: StrategyPlan, request: Request, db: Session = Depends(get_db)):
    require_command_user(request, db)
    meeting = create_meeting(payload.goal, payload.context, payload.invitees)
    strategy = select_best_strategy(meeting)
    routing = route_strategy(strategy["best_strategy"], payload.submit_to_queue)
    return {"ok": True, "meeting": meeting, "strategy": strategy, "routing": routing}


@router.post("/learning/analyze")
def analyze_learning_center(payload: LearningAnalyze, request: Request, db: Session = Depends(get_db)):
    require_command_user(request, db)
    execution = resolve_learning_execution(payload)
    analysis = analyze_execution(execution)
    scores = score_employees(execution["logs"])
    prompt_optimization = optimize_prompt_suggestions(analysis, scores, execution["logs"])
    approval_gate = learning_approval_preview(analysis, prompt_optimization)
    return {
        "ok": True,
        "center": "TianWu AI Learning Center",
        "execution": execution,
        "analysis": analysis,
        "employee_scores": scores,
        "prompt_optimization": prompt_optimization,
        "approval_gate": approval_gate,
        "safety": {
            "review_only": True,
            "requires_tian_shen_approval": True,
            "can_auto_update_prompt": False,
            "can_modify_production_prompt": False,
        },
    }


def resolve_learning_execution(payload: LearningAnalyze) -> dict[str, Any]:
    if payload.command_id:
        command = command_status(payload.command_id)
        if not command:
            raise HTTPException(status_code=404, detail="command not found")
        logs = employee_logs_from_commands([command])
        return {
            "source": "command_center",
            "command_id": payload.command_id,
            "goal": command.get("command") or payload.goal or "unknown_goal",
            "logs": logs,
        }
    return {
        "source": "manual_learning_payload",
        "command_id": "",
        "goal": payload.goal or "manual_learning_review",
        "logs": payload.logs or [],
    }


def learning_approval_preview(analysis: dict[str, Any], prompt_optimization: dict[str, Any]) -> dict[str, Any]:
    event = {
        "source": "learning_center",
        "target": "orchestrator",
        "action": "review_learning_suggestion",
        "requires_boss_confirmation": True,
        "payload": {
            "goal": analysis.get("goal"),
            "status": analysis.get("status"),
            "suggestion_count": len(prompt_optimization.get("optimization_suggestions") or []),
            "review_only": True,
            "can_auto_update_prompt": False,
            "can_modify_production_prompt": False,
        },
    }
    route = route_event(event)
    return evaluate_command(
        event,
        {
            "source": route.source,
            "target": route.target,
            "handler": route.handler,
            "queue_required": route.queue_required,
        },
    )


@router.post("/knowledge/learn")
def learn_knowledge_from_execution(payload: KnowledgeLearn, request: Request, db: Session = Depends(get_db)):
    require_command_user(request, db)
    report = payload.learning_report or build_learning_report_from_payload(payload)
    knowledge = learn_from_execution(report)
    return {"ok": True, "knowledge": knowledge}


@router.get("/knowledge/search")
def search_command_knowledge(request: Request, db: Session = Depends(get_db), q: str = "", limit: int = 10, knowledge_type: str | None = None):
    require_command_reader(request, db)
    return {"ok": True, "search": search_knowledge(q, limit, knowledge_type)}


def build_learning_report_from_payload(payload: KnowledgeLearn) -> dict[str, Any]:
    execution = resolve_learning_execution(LearningAnalyze(command_id=payload.command_id, goal=payload.goal, logs=payload.logs))
    analysis = analyze_execution(execution)
    scores = score_employees(execution["logs"])
    prompt_optimization = optimize_prompt_suggestions(analysis, scores, execution["logs"])
    approval_gate = learning_approval_preview(analysis, prompt_optimization)
    return {
        "center": "TianWu AI Learning Center",
        "execution": execution,
        "analysis": analysis,
        "employee_scores": scores,
        "prompt_optimization": prompt_optimization,
        "approval_gate": approval_gate,
    }


@router.post("/capability/match")
def match_capability(payload: CapabilityMatch, request: Request, db: Session = Depends(get_db)):
    require_command_user(request, db)
    return {"ok": True, "match": match_employee_for_task(payload.task)}
