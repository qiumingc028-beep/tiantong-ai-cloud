from __future__ import annotations

from typing import Any

from sqlalchemy import and_, exists, false, or_, select
from sqlalchemy.orm import Query, Session

from .alpha_workflow.models import AlphaWorkflowRun
from .brain_orchestrator.models import BrainTaskGraph
from .brain_orchestrator.planner import GraphOwnershipScope, resolve_graph_ownership
from .models import TaskCenterResult, TaskCenterTask, User


TASK_OWNERSHIP_FIELDS = (
    "tenant_id",
    "company_id",
    "requester_id",
    "store_scope_key",
    "ownership_scope_key",
)
SESSION_USER_KEY = "task_center_ownership_user"


def bind_session_task_ownership(db: Session, *, user: User) -> None:
    db.info[SESSION_USER_KEY] = user


def _session_user(db: Session, user: User | None) -> User | None:
    return user or db.info.get(SESSION_USER_KEY)


def bind_task_ownership(
    db: Session,
    task: TaskCenterTask,
    *,
    user: User,
    canonical_run_id: str | None = None,
) -> GraphOwnershipScope:
    scope = resolve_graph_ownership(db, user)
    task.tenant_id = scope.tenant_id
    task.company_id = scope.company_id
    task.requester_id = scope.requester_id
    task.store_scope_key = scope.store_scope_key
    task.ownership_scope_key = scope.ownership_scope_key
    task.canonical_run_id = canonical_run_id
    return scope


def task_ownership_context(task: TaskCenterTask) -> dict[str, Any]:
    values = {field: getattr(task, field) for field in TASK_OWNERSHIP_FIELDS}
    if any(value is None or value == "" for value in values.values()):
        raise ValueError("task ownership is incomplete")
    values["canonical_run_id"] = task.canonical_run_id
    return values


def bind_task_ownership_from_task(task: TaskCenterTask, *, parent: TaskCenterTask) -> None:
    context = task_ownership_context(parent)
    for field in TASK_OWNERSHIP_FIELDS:
        value = context[field]
        setattr(task, field, value)
    task.canonical_run_id = None


def owned_task_from_context_or_none(
    db: Session,
    *,
    task_id: int,
    ownership: dict[str, Any] | None,
) -> TaskCenterTask | None:
    if not isinstance(ownership, dict):
        return None
    expected = set(TASK_OWNERSHIP_FIELDS) | {"canonical_run_id"}
    if set(ownership) != expected or any(
        ownership[field] is None or ownership[field] == "" for field in TASK_OWNERSHIP_FIELDS
    ):
        return None
    return (
        db.query(TaskCenterTask)
        .filter(
            TaskCenterTask.id == task_id,
            *(getattr(TaskCenterTask, field) == ownership[field] for field in TASK_OWNERSHIP_FIELDS),
            TaskCenterTask.canonical_run_id.is_(None)
            if ownership["canonical_run_id"] is None
            else TaskCenterTask.canonical_run_id == ownership["canonical_run_id"],
        )
        .one_or_none()
    )


def task_ownership_predicate(scope: GraphOwnershipScope):
    canonical_run_matches = exists(
        select(1)
        .select_from(AlphaWorkflowRun)
        .join(BrainTaskGraph, BrainTaskGraph.canonical_run_id == AlphaWorkflowRun.run_id)
        .where(
            AlphaWorkflowRun.run_id == TaskCenterTask.canonical_run_id,
            AlphaWorkflowRun.task_id == TaskCenterTask.id,
            AlphaWorkflowRun.user_id == scope.requester_id,
            BrainTaskGraph.tenant_id == scope.tenant_id,
            BrainTaskGraph.company_id == scope.company_id,
            BrainTaskGraph.requester_id == scope.requester_id,
            BrainTaskGraph.store_scope_key == scope.store_scope_key,
            BrainTaskGraph.ownership_scope_key == scope.ownership_scope_key,
        )
    )
    return and_(
        TaskCenterTask.tenant_id == scope.tenant_id,
        TaskCenterTask.company_id == scope.company_id,
        TaskCenterTask.requester_id == scope.requester_id,
        TaskCenterTask.store_scope_key == scope.store_scope_key,
        TaskCenterTask.ownership_scope_key == scope.ownership_scope_key,
        or_(TaskCenterTask.canonical_run_id.is_(None), canonical_run_matches),
    )


def owned_tasks_query(db: Session, *, user: User | None = None) -> Query:
    user = _session_user(db, user)
    if user is None:
        return db.query(TaskCenterTask).filter(false())
    scope = resolve_graph_ownership(db, user)
    return db.query(TaskCenterTask).filter(task_ownership_predicate(scope))


def owned_task_or_none(db: Session, *, task_id: int, user: User | None = None) -> TaskCenterTask | None:
    return owned_tasks_query(db, user=user).filter(TaskCenterTask.id == task_id).one_or_none()


def owned_results_query(db: Session, *, user: User | None = None) -> Query:
    user = _session_user(db, user)
    if user is None:
        return db.query(TaskCenterResult).filter(false())
    scope = resolve_graph_ownership(db, user)
    return (
        db.query(TaskCenterResult)
        .join(TaskCenterTask, TaskCenterTask.id == TaskCenterResult.task_id)
        .filter(task_ownership_predicate(scope))
    )


def owned_task_rows_query(db: Session, entity, task_id_column, *, user: User | None = None) -> Query:
    return (
        owned_tasks_query(db, user=user)
        .join(entity, task_id_column == TaskCenterTask.id)
        .with_entities(entity)
    )


def owned_result_or_none(
    db: Session,
    *,
    user: User | None = None,
    task_id: int,
    result_id: int,
) -> TaskCenterResult | None:
    return (
        owned_results_query(db, user=user)
        .filter(TaskCenterResult.task_id == task_id, TaskCenterResult.id == result_id)
        .one_or_none()
    )
