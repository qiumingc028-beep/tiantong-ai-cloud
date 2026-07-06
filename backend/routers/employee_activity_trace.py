from __future__ import annotations

from typing import Optional
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..deploy_models import DeployRecord
from ..models import AiEmployee, TaskCenterAuditLog, TaskCenterResult, TaskCenterReview, TaskCenterTask
from ..orchestrator_models import OrchestratorAnalysisRecord, OrchestratorTaskLink


router = APIRouter()

PRIVILEGED_ROLES = {"owner", "admin"}
BLOCKER_STATUSES = {"rejected", "failed", "blocked"}
PENDING_BOSS_STATUSES = {"created", "pending"}
REVIEW_PENDING_STATUSES = {"submitted", "result_submitted", "reviewing"}
AUDIT_PENDING_STATUSES = {"accepted"}
DEPLOY_PENDING_STATUSES = {"audited", "summarized"}
@router.get("/logs/{log_id}/trace")
def get_log_trace(log_id: str, request: Request, db: Session = Depends(get_db)):
    require_trace_user(request, db)
    logs = build_activity_logs(db)
    log = next((row for row in logs if row["log_id"] == log_id), None)
    if not log:
        raise HTTPException(status_code=404, detail="log not found")
    task = db.get(TaskCenterTask, log["task_id"]) if log.get("task_id") else None
    response = build_trace_response(db, task=task, employee_code=log.get("employee_code"), focus_log=log)
    response["summary"]["trace_type"] = "log"
    return response


@router.get("/tasks/{task_id}/trace")
def get_task_trace(task_id: int, request: Request, db: Session = Depends(get_db)):
    require_trace_user(request, db)
    task = db.get(TaskCenterTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    response = build_trace_response(db, task=task, employee_code=task.assigned_ai_employee_code)
    response["summary"]["trace_type"] = "task"
    return response


@router.get("/employees/{employee_code}/trace")
def get_employee_trace(employee_code: str, request: Request, db: Session = Depends(get_db)):
    require_trace_user(request, db)
    employee = find_employee(db, employee_code)
    response = build_trace_response(db, employee_code=employee_code)
    response["summary"]["trace_type"] = "employee"
    response["employee"] = employee_payload(employee) if employee else {"employee_code": safe_text(employee_code)}
    return response


@router.get("/trace-overview")
def get_trace_overview(request: Request, db: Session = Depends(get_db)):
    require_trace_user(request, db)
    logs = build_activity_logs(db)
    tasks = db.query(TaskCenterTask).order_by(TaskCenterTask.id.desc()).limit(500).all()
    blockers = [safe_log(row) for row in logs if row.get("has_blocker")][:100]
    pending_boss = [safe_log(row) for row in logs if row.get("needs_boss_confirmation")][:100]
    missing_steps = []
    for task in tasks:
        missing_steps.extend(missing_steps_for_task(db, task))
    return {
        "summary": {
            "trace_type": "overview",
            "total_logs": len(logs),
            "total_tasks": len(tasks),
            "blockers": len(blockers),
            "pending_boss_confirmations": len(pending_boss),
            "pending_reviews": sum(1 for task in tasks if task.status in REVIEW_PENDING_STATUSES),
            "pending_audits": sum(1 for task in tasks if task.status in AUDIT_PENDING_STATUSES),
            "pending_deploys": sum(1 for task in tasks if task.status in DEPLOY_PENDING_STATUSES),
            "missing_steps": len(missing_steps),
        },
        "trace_nodes": [],
        "trace_edges": [],
        "employee": {},
        "task": {},
        "orchestrator_source": {},
        "boss_confirmation": {"items": pending_boss[:20]},
        "review_status": {},
        "audit_status": {},
        "deploy_status": {},
        "git_commit": {},
        "blockers": blockers,
        "missing_steps": missing_steps[:200],
        "next_suggestion": "优先处理阻塞、老板确认、验收、审计和部署缺失环节",
        "safety_flags": [],
    }


def require_trace_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in PRIVILEGED_ROLES:
        raise HTTPException(status_code=403, detail="no employee activity trace permission")
    return user


def build_trace_response(db: Session, task: Optional[TaskCenterTask] = None, employee_code: Optional[str] = None, focus_log: Optional[dict] = None) -> dict:
    logs = build_activity_logs(db)
    if task:
        logs = [row for row in logs if row.get("task_id") == task.id or row.get("source_id") == str(task.id)]
    elif employee_code:
        logs = [row for row in logs if row.get("employee_code") == employee_code]
    if focus_log and not any(row["log_id"] == focus_log["log_id"] for row in logs):
        logs.insert(0, focus_log)

    logs.sort(key=lambda row: row.get("time") or "", reverse=False)
    trace_nodes = [log_to_node(row) for row in logs]
    trace_edges = build_edges(trace_nodes)
    trace_task = task or first_task_from_logs(db, logs)
    employee = find_employee(db, employee_code or (trace_task.assigned_ai_employee_code if trace_task else None))
    source = orchestrator_source_for_task(db, trace_task) if trace_task else {}
    reviews = reviews_for_task(db, trace_task) if trace_task else []
    audits = audits_for_task(db, trace_task) if trace_task else []
    deploys = deploys_for_task(db, trace_task) if trace_task else []
    commits = commits_for_deploys(deploys)
    blockers = [safe_log(row) for row in logs if row.get("has_blocker")]
    missing_steps = missing_steps_for_task(db, trace_task) if trace_task else []

    return {
        "summary": {
            "trace_type": "trace",
            "total_nodes": len(trace_nodes),
            "total_edges": len(trace_edges),
            "has_blocker": bool(blockers),
            "missing_steps": len(missing_steps),
        },
        "trace_nodes": trace_nodes,
        "trace_edges": trace_edges,
        "employee": employee_payload(employee) if employee else {},
        "task": task_payload(trace_task) if trace_task else {},
        "orchestrator_source": source,
        "boss_confirmation": boss_confirmation_for_task(trace_task),
        "review_status": review_summary(reviews),
        "audit_status": review_summary(audits),
        "deploy_status": deploy_summary(deploys),
        "git_commit": commit_summary(commits),
        "blockers": blockers,
        "missing_steps": missing_steps,
        "next_suggestion": next_suggestion(trace_task, blockers, missing_steps),
        "safety_flags": safety_flags_from_source(source),
    }


def build_activity_logs(db: Session) -> list[dict]:
    employees = {row.employee_code: row for row in db.query(AiEmployee).all()}
    tasks = db.query(TaskCenterTask).order_by(TaskCenterTask.id.desc()).limit(500).all()
    task_map = {task.id: task for task in tasks}
    logs: list[dict] = []
    for task in tasks:
        logs.append(make_log("task_created", "任务创建", task.created_at, task, employees, "task_center", str(task.id), task.status, "任务已创建"))
        if task.assigned_ai_employee_code:
            logs.append(make_log("task_assigned", "分配 AI员工", task.updated_at or task.created_at, task, employees, "task_center", str(task.id), task.status, "任务已分配"))
        if task.status in BLOCKER_STATUSES:
            logs.append(make_log("blocker_detected", "发现阻塞", task.updated_at or task.created_at, task, employees, "task_center", str(task.id), task.status, status_summary(task.status), has_blocker=True, blocker_reason=status_summary(task.status)))
        if task.status in PENDING_BOSS_STATUSES:
            logs.append(make_log("boss_confirmation_required", "等待老板确认", task.updated_at or task.created_at, task, employees, "task_center", str(task.id), task.status, "任务等待老板确认", needs_boss_confirmation=True))

    for row in db.query(TaskCenterAuditLog).order_by(TaskCenterAuditLog.id.asc()).limit(500).all():
        task = task_map.get(row.task_id)
        logs.append(make_log("task_status_changed", "任务状态流转", row.created_at, task, employees, "task_center", str(row.id), row.to_status or (task.status if task else None), safe_summary(row.detail) or "任务状态流转"))

    for row in db.query(TaskCenterResult).order_by(TaskCenterResult.id.asc()).limit(500).all():
        task = task_map.get(row.task_id)
        logs.append(make_log("task_submitted", "提交结果", row.created_at, task, employees, "task_center", str(row.id), task.status if task else "result_submitted", "AI员工提交任务结果", employee_code=row.ai_employee_code))

    for row in db.query(TaskCenterReview).order_by(TaskCenterReview.id.asc()).limit(500).all():
        task = task_map.get(row.task_id)
        action_type = "task_audited" if row.review_type == "audit" else "task_reviewed"
        title = "天监审计" if row.review_type == "audit" else "天检验收"
        has_blocker = row.review_status == "rejected"
        logs.append(make_log(action_type, title, row.created_at, task, employees, "task_center", str(row.id), row.review_status, f"{title}：{safe_text(row.review_status)}", has_blocker=has_blocker, blocker_reason="任务被驳回" if has_blocker else None))

    for row in db.query(OrchestratorAnalysisRecord).order_by(OrchestratorAnalysisRecord.id.asc()).limit(300).all():
        logs.append(
            make_log(
                "orchestrator_analyzed",
                "Orchestrator 分析",
                row.created_at,
                None,
                employees,
                "orchestrator",
                str(row.id),
                row.completion_status,
                f"识别阶段：{safe_text(row.detected_stage)}，推荐：{safe_text(row.recommended_codex)}",
                employee_code=row.recommended_codex or row.detected_employee_code,
                has_blocker=bool(row.has_blocker or row.needs_fix),
                blocker_reason=orchestrator_blocker_reason(row),
                needs_boss_confirmation=bool(row.needs_fix),
            )
        )

    for link in db.query(OrchestratorTaskLink).order_by(OrchestratorTaskLink.id.asc()).limit(300).all():
        task = task_map.get(link.task_id)
        logs.append(make_log("task_created_from_orchestrator", "Orchestrator 来源链路", link.created_at, task, employees, "orchestrator", str(link.id), task.status if task else link.link_type, f"来源链路：{safe_text(link.link_type)}", employee_code=link.recommended_codex))

    for row in db.query(DeployRecord).order_by(DeployRecord.id.asc()).limit(200).all():
        logs.append(make_log("deploy_recorded", "部署记录", row.finished_at or row.started_at or row.created_at, None, employees, "deploy_center", str(row.id), row.status, f"部署状态：{safe_text(row.status)}", employee_code=row.operator, has_blocker=row.status in {"failed", "error", "rollback_failed"}, blocker_reason="部署失败" if row.status in {"failed", "error", "rollback_failed"} else None))
        if row.commit_hash:
            logs.append(make_log("git_commit_recorded", "GitHub Commit 记录", row.created_at, None, employees, "deploy_center", str(row.id), row.status, f"Commit {safe_text(row.commit_hash)}", employee_code=row.operator))
    return logs


def make_log(action_type: str, title: str, time: Optional[datetime], task: Optional[TaskCenterTask], employees: dict[str, AiEmployee], source_module: str, source_id: str, status: Optional[str], summary: Optional[str], employee_code: Optional[str] = None, has_blocker: bool = False, blocker_reason: Optional[str] = None, needs_boss_confirmation: bool = False) -> dict:
    code = employee_code or (task.assigned_ai_employee_code if task else None)
    employee = employees.get(code or "")
    return {
        "log_id": f"{source_module}-{source_id}-{action_type}",
        "action_type": safe_text(action_type),
        "action_title": safe_text(title),
        "time": iso(time),
        "employee_code": safe_text(code, None),
        "employee_name": safe_text(employee.employee_name if employee else (task.assigned_ai_employee_name if task else None), None),
        "task_id": task.id if task else None,
        "task_title": safe_text(task.title if task else None, None),
        "status": safe_text(status, None),
        "source_module": safe_text(source_module),
        "source_id": safe_text(source_id),
        "summary": safe_summary(summary),
        "has_blocker": bool(has_blocker),
        "blocker_reason": safe_text(blocker_reason, None),
        "needs_boss_confirmation": bool(needs_boss_confirmation),
    }


def log_to_node(log: dict) -> dict:
    return safe_node(
        {
            "node_id": log.get("log_id"),
            "node_type": log.get("action_type"),
            "title": log.get("action_title"),
            "status": log.get("status"),
            "time": log.get("time"),
            "employee_code": log.get("employee_code"),
            "task_id": log.get("task_id"),
            "source_module": log.get("source_module"),
            "source_id": log.get("source_id"),
            "summary": log.get("summary"),
        }
    )


def build_edges(nodes: list[dict]) -> list[dict]:
    edges = []
    for previous, current in zip(nodes, nodes[1:]):
        edges.append(
            {
                "from_node": previous["node_id"],
                "to_node": current["node_id"],
                "relation_type": "next_step",
                "label": "下一环节",
            }
        )
    return edges


def first_task_from_logs(db: Session, logs: list[dict]) -> Optional[TaskCenterTask]:
    for log in logs:
        if log.get("task_id"):
            return db.get(TaskCenterTask, log["task_id"])
    return None


def find_employee(db: Session, employee_code: Optional[str]) -> Optional[AiEmployee]:
    if not employee_code:
        return None
    return db.query(AiEmployee).filter(AiEmployee.employee_code == employee_code).one_or_none()


def task_payload(task: Optional[TaskCenterTask]) -> dict:
    if not task:
        return {}
    return {
        "task_id": task.id,
        "task_title": safe_text(task.title),
        "status": safe_text(task.status),
        "priority": safe_text(task.priority),
        "sprint": task_sprint(task),
        "assigned_employee_code": safe_text(task.assigned_ai_employee_code, None),
        "assigned_employee_name": safe_text(task.assigned_ai_employee_name, None),
        "created_at": iso(task.created_at),
        "updated_at": iso(task.updated_at),
    }


def employee_payload(employee: Optional[AiEmployee]) -> dict:
    if not employee:
        return {}
    return {
        "employee_code": safe_text(employee.employee_code),
        "employee_name": safe_text(employee.employee_name),
        "department": safe_text(employee.legion, None),
        "role": first_json_value(employee.task_types),
        "status": safe_text(employee.status),
    }


def orchestrator_source_for_task(db: Session, task: Optional[TaskCenterTask]) -> dict:
    if not task:
        return {}
    link = db.query(OrchestratorTaskLink).filter(OrchestratorTaskLink.task_id == task.id).order_by(OrchestratorTaskLink.id.desc()).first()
    if not link:
        return {}
    analysis = db.get(OrchestratorAnalysisRecord, link.analysis_record_id)
    return {
        "link_id": link.id,
        "analysis_record_id": link.analysis_record_id,
        "link_type": safe_text(link.link_type),
        "recommended_codex": safe_text(link.recommended_codex, None),
        "source_stage": safe_text(link.source_stage, None),
        "detected_employee_name": safe_text(analysis.detected_employee_name if analysis else None, None),
        "detected_sprint": safe_text(analysis.detected_sprint if analysis else None, None),
        "detected_stage": safe_text(analysis.detected_stage if analysis else None, None),
        "completion_status": safe_text(analysis.completion_status if analysis else None, None),
        "has_blocker": bool(analysis.has_blocker) if analysis else False,
        "needs_fix": bool(analysis.needs_fix) if analysis else False,
        "safety_flags": safe_text_list(parse_json_list(analysis.safety_flags_json if analysis else None)),
    }


def reviews_for_task(db: Session, task: Optional[TaskCenterTask]) -> list[TaskCenterReview]:
    if not task:
        return []
    return db.query(TaskCenterReview).filter(TaskCenterReview.task_id == task.id, TaskCenterReview.review_type != "audit").order_by(TaskCenterReview.id.desc()).all()


def audits_for_task(db: Session, task: Optional[TaskCenterTask]) -> list[TaskCenterReview]:
    if not task:
        return []
    return db.query(TaskCenterReview).filter(TaskCenterReview.task_id == task.id, TaskCenterReview.review_type == "audit").order_by(TaskCenterReview.id.desc()).all()


def deploys_for_task(db: Session, task: Optional[TaskCenterTask]) -> list[DeployRecord]:
    if not task:
        return []
    sprint = task_sprint(task)
    query = db.query(DeployRecord).order_by(DeployRecord.id.desc()).limit(20)
    if sprint:
        query = db.query(DeployRecord).filter(DeployRecord.deploy_version == sprint).order_by(DeployRecord.id.desc()).limit(20)
    return query.all()


def commits_for_deploys(deploys: list[DeployRecord]) -> list[dict]:
    return [
        {
            "commit_id": safe_text(row.commit_hash),
            "branch": safe_text(row.branch, None),
            "created_at": iso(row.created_at),
        }
        for row in deploys
        if row.commit_hash
    ]


def boss_confirmation_for_task(task: Optional[TaskCenterTask]) -> dict:
    if not task:
        return {}
    return {
        "required": task.status in PENDING_BOSS_STATUSES,
        "status": "pending" if task.status in PENDING_BOSS_STATUSES else "not_required",
        "summary": "等待老板确认" if task.status in PENDING_BOSS_STATUSES else "暂无待确认事项",
    }


def review_summary(rows: list[TaskCenterReview]) -> dict:
    if not rows:
        return {}
    row = rows[0]
    return {"review_id": row.id, "status": safe_text(row.review_status), "reviewer_role": safe_text(row.reviewer_role, None), "time": iso(row.created_at)}


def deploy_summary(rows: list[DeployRecord]) -> dict:
    if not rows:
        return {}
    row = rows[0]
    return {"deploy_id": row.id, "status": safe_text(row.status), "time": iso(row.finished_at or row.started_at or row.created_at)}


def commit_summary(rows: list[dict]) -> dict:
    return rows[0] if rows else {}


def missing_steps_for_task(db: Session, task: Optional[TaskCenterTask]) -> list[dict]:
    if not task:
        return []
    steps = []
    if not task.assigned_ai_employee_code:
        steps.append({"step": "assignment", "label": "缺少 AI员工分配", "task_id": task.id})
    if not orchestrator_source_for_task(db, task):
        steps.append({"step": "orchestrator_source", "label": "缺少 Orchestrator 来源", "task_id": task.id})
    if task.status in PENDING_BOSS_STATUSES:
        steps.append({"step": "boss_confirmation", "label": "等待老板确认", "task_id": task.id})
    if not reviews_for_task(db, task):
        steps.append({"step": "review", "label": "缺少天检验收", "task_id": task.id})
    if not audits_for_task(db, task):
        steps.append({"step": "audit", "label": "缺少天监审计", "task_id": task.id})
    if not deploys_for_task(db, task):
        steps.append({"step": "deploy", "label": "缺少天盾部署记录", "task_id": task.id})
    return steps


def next_suggestion(task: Optional[TaskCenterTask], blockers: list[dict], missing_steps: list[dict]) -> str:
    if blockers:
        return "优先处理阻塞原因"
    if missing_steps:
        return safe_text(missing_steps[0].get("label"), "继续补齐追溯链路")
    if task and task.status in {"completed", "summarized"}:
        return "任务链路已完成"
    return "继续跟进任务流转"


def safety_flags_from_source(source: dict) -> list[str]:
    return safe_text_list(source.get("safety_flags")) if source else []


def safe_log(row: dict) -> dict:
    return {
        "log_id": safe_text(row.get("log_id")),
        "action_type": safe_text(row.get("action_type")),
        "action_title": safe_text(row.get("action_title")),
        "time": safe_text(row.get("time"), None),
        "employee_code": safe_text(row.get("employee_code"), None),
        "task_id": row.get("task_id"),
        "status": safe_text(row.get("status"), None),
        "source_module": safe_text(row.get("source_module")),
        "source_id": safe_text(row.get("source_id")),
        "summary": safe_summary(row.get("summary")),
        "has_blocker": bool(row.get("has_blocker")),
        "blocker_reason": safe_text(row.get("blocker_reason"), None),
        "needs_boss_confirmation": bool(row.get("needs_boss_confirmation")),
    }


def safe_node(value: dict) -> dict:
    return {
        "node_id": safe_text(value.get("node_id")),
        "node_type": safe_text(value.get("node_type")),
        "title": safe_text(value.get("title")),
        "status": safe_text(value.get("status"), None),
        "time": safe_text(value.get("time"), None),
        "employee_code": safe_text(value.get("employee_code"), None),
        "task_id": value.get("task_id"),
        "source_module": safe_text(value.get("source_module")),
        "source_id": safe_text(value.get("source_id")),
        "summary": safe_summary(value.get("summary")),
    }


def safe_obj(value) -> dict:
    return value if isinstance(value, dict) else {}


def safe_summary(value, fallback: Optional[str] = "暂无") -> Optional[str]:
    return safe_text(value, fallback)


def safe_text(value, fallback: Optional[str] = "暂无") -> Optional[str]:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        return text or fallback
    if isinstance(value, list):
        parts = safe_text_list(value)
        return "、".join(parts) if parts else fallback
    if isinstance(value, dict):
        for key in ["reason", "message", "title", "text", "name", "code"]:
            if key in value:
                text = safe_text(value.get(key), None)
                if text:
                    return text
        return "存在追溯项"
    return fallback


def safe_text_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(safe_text_list(item))
        return items
    text = safe_text(value, None)
    return [text] if text else []


def orchestrator_blocker_reason(row: OrchestratorAnalysisRecord) -> Optional[str]:
    if row.has_blocker:
        flags = safe_text_list(parse_json_list(row.safety_flags_json))
        return "、".join(flags) if flags else "Orchestrator 检测到阻塞"
    if row.needs_fix:
        return "Orchestrator 建议修复"
    return None


def status_summary(status: Optional[str]) -> str:
    return {"rejected": "任务被驳回", "failed": "任务失败", "blocked": "任务阻塞"}.get(status or "", "任务状态更新")


def first_json_value(value: Optional[str]) -> Optional[str]:
    values = parse_json_list(value)
    return safe_text(values[0], None) if values else None


def parse_json_list(value: Optional[str]) -> list:
    if not value:
        return []
    try:
        data = json.loads(value)
    except Exception:
        return []
    return data if isinstance(data, list) else []


def task_sprint(task: Optional[TaskCenterTask]) -> Optional[str]:
    if not task:
        return None
    for value in [task.title, task.description, task.split_plan, task.summary]:
        if not value:
            continue
        for index in range(1, 20):
            sprint = f"Sprint {index}"
            if sprint in value:
                return sprint
    return None


def iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None
