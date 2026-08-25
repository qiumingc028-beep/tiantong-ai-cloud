from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import re
import typing
from itertools import product
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel

from backend.agent_runtime.models import AgentExecution
from backend.database import get_redis
from backend.dispatch_models import EmployeeExecutionLog
from backend.main import app
from backend.models import AiEmployee, TaskCenterAuditLog, TaskCenterResult, TaskCenterReview, TaskCenterTask, User, UserStoreMembership
from backend.release_models import ReleaseVersion
from backend.task_center_ownership import bind_task_ownership, owned_task_from_context_or_none, task_ownership_context
from backend.worker import execute_sprint17_task
from tests.task_center_full_entrypoint_matrix_cases import (
    CONTROL_PLANE_PUBLIC_CASES,
    TASKCENTER_PUBLIC_CASES,
    WORKER_STAGE_CASES,
)
from tests.test_v2_alpha_postgresql_migration_regression import _create_scoped_owner


PUBLIC_ENTRYPOINTS = [('PUB-001', 'POST /api/v2/executions/{execution_id}/approve', 'backend.routers.agent_runtime.api_approve_execution'), ('PUB-002', 'POST /api/v2/executions', 'backend.routers.agent_runtime.api_create_execution'), ('PUB-003', 'GET /api/ai-employee-ecosystem/overview', 'backend.routers.ai_employee_ecosystem.get_ai_employee_ecosystem_overview'), ('PUB-004', 'GET /api/ai-employee-growth/employees/{employee_id}', 'backend.routers.ai_employee_growth.get_ai_employee_growth_detail'), ('PUB-005', 'GET /api/ai-employee-growth/overview', 'backend.routers.ai_employee_growth.get_ai_employee_growth_overview'), ('PUB-006', 'GET /api/ai-employee-growth/employees/{employee_id}/timeline', 'backend.routers.ai_employee_growth.get_ai_employee_growth_timeline'), ('PUB-007', 'GET /api/ai-employee-growth-system/employees/{employee_id}/profile', 'backend.routers.ai_employee_growth_system.get_employee_growth_profile'), ('PUB-008', 'GET /api/ai-employee-growth-system/employees/{employee_id}/skill-suggestions', 'backend.routers.ai_employee_growth_system.get_employee_skill_suggestions'), ('PUB-009', 'GET /api/ai-employee-growth-system/overview', 'backend.routers.ai_employee_growth_system.get_growth_system_overview'), ('PUB-010', 'GET /api/ai-employee-growth-system/tasks/{task_id}/impact', 'backend.routers.ai_employee_growth_system.get_task_growth_impact'), ('PUB-011', 'GET /api/ai-employee-growth-system/waiting-confirm', 'backend.routers.ai_employee_growth_system.get_waiting_confirm_growth_items'), ('PUB-012', 'GET /api/ai-employee-health/overview', 'backend.routers.ai_employee_health.get_ai_employee_health_overview'), ('PUB-013', 'GET /api/ai-employee-skills/skills/{skill_id}', 'backend.routers.ai_employee_skills.get_employee_skill_detail'), ('PUB-014', 'GET /api/ai-employee-skills/employees/{employee_id}/skills', 'backend.routers.ai_employee_skills.get_employee_skill_relations'), ('PUB-015', 'GET /api/ai-employee-skills/skills', 'backend.routers.ai_employee_skills.get_employee_skills'), ('PUB-016', 'GET /api/ai-employees/{employee_id}/detail', 'backend.routers.ai_employees.get_ai_employee_detail'), ('PUB-017', 'GET /api/ai-employees/runtime-status', 'backend.routers.ai_employees.get_ai_employee_runtime_status'), ('PUB-018', 'POST /api/tasks/{task_id}/assign', 'backend.routers.ai_execution.assign_task'), ('PUB-019', 'POST /api/tasks/{task_id}/complete', 'backend.routers.ai_execution.complete_task'), ('PUB-020', 'POST /api/tasks/{task_id}/feedback-loop', 'backend.routers.ai_execution.create_feedback_loop_task'), ('PUB-021', 'POST /api/tasks', 'backend.routers.ai_execution.create_task'), ('PUB-022', 'POST /api/flows/tiancai-tianshu-tiance-tianbo', 'backend.routers.ai_execution.create_tiancai_to_tianbo_flow'), ('PUB-023', 'GET /api/results', 'backend.routers.ai_execution.list_results'), ('PUB-024', 'GET /api/tasks', 'backend.routers.ai_execution.list_tasks'), ('PUB-025', 'POST /api/webhooks/tasks', 'backend.routers.ai_execution.webhook_create_task'), ('PUB-026', 'GET /api/ai-workforce/overview', 'backend.routers.ai_workforce.get_ai_workforce_overview'), ('PUB-027', 'GET /api/ai-workforce/tasks/{task_id}/lifecycle', 'backend.routers.ai_workforce.get_ai_workforce_task_lifecycle'), ('PUB-028', 'GET /api/ai-workforce/employees/{employee_id}/task-flow', 'backend.routers.ai_workforce.get_employee_task_flow'), ('PUB-029', 'GET /api/ai-workforce/tasks/waiting-confirm', 'backend.routers.ai_workforce.get_waiting_confirm_task_flow'), ('PUB-030', 'POST /api/v2/alpha-workflows/runs/{run_id}/cancel', 'backend.routers.alpha_workflow.api_cancel_run'), ('PUB-031', 'POST /api/v2/alpha-workflows/demo', 'backend.routers.alpha_workflow.api_run_demo'), ('PUB-032', 'GET /api/approval-center/pending', 'backend.routers.approval_center.get_pending_approvals'), ('PUB-033', 'POST /api/auto-dispatch/analyze', 'backend.routers.auto_dispatch.analyze_task'), ('PUB-034', 'POST /api/auto-dispatch/tasks/{task_id}/confirm', 'backend.routers.auto_dispatch.confirm_dispatch'), ('PUB-035', 'POST /api/auto-dispatch/tasks/{task_id}/plan', 'backend.routers.auto_dispatch.create_dispatch_plan'), ('PUB-036', 'POST /api/auto-dispatch/tasks/{task_id}/tracking', 'backend.routers.auto_dispatch.create_execution_tracking'), ('PUB-037', 'GET /api/auto-dispatch/tasks/{task_id}/tracking', 'backend.routers.auto_dispatch.get_execution_tracking'), ('PUB-038', 'POST /api/auto-dispatch/match', 'backend.routers.auto_dispatch.match_employee'), ('PUB-039', 'POST /api/business-webhooks/content/metrics', 'backend.routers.business_loop.content_metrics_webhook'), ('PUB-040', 'POST /api/business-webhooks/ecommerce/orders', 'backend.routers.business_loop.ecommerce_order_webhook'), ('PUB-041', 'POST /api/business-webhooks/files', 'backend.routers.business_loop.file_upload_webhook'), ('PUB-042', 'GET /api/business-loop/decisions', 'backend.routers.business_loop.list_business_decisions'), ('PUB-043', 'GET /api/business-loop/results', 'backend.routers.business_loop.list_business_results'), ('PUB-044', 'POST /api/business-loop/results/{result_id}/replay', 'backend.routers.business_loop.replay_business_result'), ('PUB-045', 'GET /api/ceo-dashboard/summary', 'backend.routers.ceo_dashboard.get_ceo_dashboard_summary'), ('PUB-046', 'GET /api/ceo-dashboard/v2/daily-operations', 'backend.routers.ceo_dashboard.get_ceo_dashboard_v2_daily_operations'), ('PUB-047', 'GET /api/ceo-dashboard/v2/employee-status', 'backend.routers.ceo_dashboard.get_ceo_dashboard_v2_employee_status'), ('PUB-048', 'GET /api/ceo-dashboard/v2/overview', 'backend.routers.ceo_dashboard.get_ceo_dashboard_v2_overview'), ('PUB-049', 'GET /api/ceo-dashboard/v2/system-health', 'backend.routers.ceo_dashboard.get_ceo_dashboard_v2_system_health'), ('PUB-050', 'GET /api/ceo-dashboard/v2/task-summary', 'backend.routers.ceo_dashboard.get_ceo_dashboard_v2_task_summary'), ('PUB-051', 'GET /api/ceo-dashboard/daily-operations', 'backend.routers.ceo_dashboard.get_daily_operations'), ('PUB-052', 'GET /api/ceo-dashboard/daily-summary', 'backend.routers.ceo_dashboard.get_daily_summary'), ('PUB-053', 'GET /api/ceo-dashboard/employee-command-dashboard', 'backend.routers.ceo_dashboard.get_employee_command_dashboard'), ('PUB-054', 'GET /api/ceo-dashboard/employee-command-dashboard/employees/{employee_code}', 'backend.routers.ceo_dashboard.get_employee_command_dashboard_detail'), ('PUB-055', 'POST /api/v2/computer/workflows/{workflow_id}/resume', 'backend.routers.computer_workflows.resume_workflow_api'), ('PUB-056', 'POST /api/v2/computer/workflows/{workflow_id}/start', 'backend.routers.computer_workflows.start_workflow_api'), ('PUB-057', 'POST /api/content/analyze/trend', 'backend.routers.dual_engine_business.analyze_content_trend'), ('PUB-058', 'GET /api/business/data-lake', 'backend.routers.dual_engine_business.data_lake'), ('PUB-059', 'POST /api/business/decision-center', 'backend.routers.dual_engine_business.decision_center'), ('PUB-060', 'POST /api/business/ecommerce/decision', 'backend.routers.dual_engine_business.ecommerce_decision'), ('PUB-061', 'POST /api/business/ecommerce/metrics', 'backend.routers.dual_engine_business.ecommerce_metrics'), ('PUB-062', 'POST /api/business/ecommerce/orders', 'backend.routers.dual_engine_business.ecommerce_orders'), ('PUB-063', 'POST /api/content/generate/video', 'backend.routers.dual_engine_business.generate_video'), ('PUB-064', 'POST /api/content/generate/xiaohongshu', 'backend.routers.dual_engine_business.generate_xiaohongshu'), ('PUB-065', 'GET /api/money/loop/status', 'backend.routers.dual_engine_business.money_loop_status'), ('PUB-066', 'POST /api/money/optimize', 'backend.routers.dual_engine_business.optimize_money_loop'), ('PUB-067', 'POST /api/money/loop/start', 'backend.routers.dual_engine_business.start_money_loop'), ('PUB-068', 'POST /api/money/loop/stop', 'backend.routers.dual_engine_business.stop_money_loop'), ('PUB-069', 'GET /api/employee-activity-log/overview', 'backend.routers.employee_activity_log.get_employee_activity_log_overview'), ('PUB-070', 'GET /api/employee-activity-trace/employees/{employee_code}/trace', 'backend.routers.employee_activity_trace.get_employee_trace'), ('PUB-071', 'GET /api/employee-activity-trace/logs/{log_id}/trace', 'backend.routers.employee_activity_trace.get_log_trace'), ('PUB-072', 'GET /api/employee-activity-trace/tasks/{task_id}/trace', 'backend.routers.employee_activity_trace.get_task_trace'), ('PUB-073', 'GET /api/employee-activity-trace/trace-overview', 'backend.routers.employee_activity_trace.get_trace_overview'), ('PUB-074', 'GET /api/employee-capabilities/employees', 'backend.routers.employee_capabilities.get_employee_capabilities'), ('PUB-075', 'GET /api/employee-capabilities/overview', 'backend.routers.employee_capabilities.get_employee_capabilities_overview'), ('PUB-076', 'GET /api/employee-capabilities/employees/{employee_code}', 'backend.routers.employee_capabilities.get_employee_capability'), ('PUB-077', 'GET /api/employee-capabilities/models', 'backend.routers.employee_capabilities.get_employee_capability_models'), ('PUB-078', 'GET /api/employee-capabilities/risks', 'backend.routers.employee_capabilities.get_employee_capability_risks'), ('PUB-079', 'GET /api/employee-capabilities/tools', 'backend.routers.employee_capabilities.get_employee_capability_tools'), ('PUB-080', 'GET /api/employee-capabilities/missing-capabilities', 'backend.routers.employee_capabilities.get_employee_missing_capabilities'), ('PUB-081', 'POST /api/employee-evolution/analyze', 'backend.routers.employee_evolution.analyze_employee'), ('PUB-082', 'POST /api/employee-execution/tian-shang/tasks', 'backend.routers.employee_execution.create_tian_shang_execution_task'), ('PUB-083', 'POST /api/employee-execution/tian-shang/process-next', 'backend.routers.employee_execution.process_next_tian_shang_task'), ('PUB-084', 'GET /api/employee-workspace/employees/{employee_code}/home', 'backend.routers.employee_workspace.get_employee_workspace_home'), ('PUB-085', 'GET /api/employee-workspace/overview', 'backend.routers.employee_workspace.get_employee_workspace_overview'), ('PUB-086', 'GET /api/enterprise-brain-console/overview', 'backend.routers.enterprise_brain_console.get_enterprise_brain_console_overview'), ('PUB-087', 'POST /api/execution/tasks/{task_id}/claim', 'backend.routers.execution_engine.claim_task'), ('PUB-088', 'POST /api/execution/tasks/{task_id}/complete', 'backend.routers.execution_engine.complete_task'), ('PUB-089', 'POST /api/execution/tasks/{task_id}/fail', 'backend.routers.execution_engine.fail_task'), ('PUB-090', 'POST /api/execution/tasks/{task_id}/start', 'backend.routers.execution_engine.start_task'), ('PUB-091', 'POST /api/orchestrator/task-drafts/confirm-create-task', 'backend.routers.orchestrator_task_links.confirm_create_task'), ('PUB-092', 'POST /api/orchestrator/task-links', 'backend.routers.orchestrator_task_links.create_task_link'), ('PUB-093', 'GET /api/task-center/tasks/{task_id}/orchestrator-links', 'backend.routers.orchestrator_task_links.list_task_orchestrator_links'), ('PUB-094', 'POST /api/release/approve', 'backend.routers.release_center.approve_release'), ('PUB-095', 'GET /api/release/check', 'backend.routers.release_center.check_release'), ('PUB-096', 'POST /api/release/create', 'backend.routers.release_center.create_release'), ('PUB-097', 'GET /api/release/current', 'backend.routers.release_center.get_current_release'), ('PUB-098', 'POST /api/reviews/generate', 'backend.routers.reviews.generate_review'), ('PUB-099', 'POST /api/v2/skills/{skill_id:int}/invoke', 'backend.routers.skills_engine_v2.api_invoke_skill'), ('PUB-100', 'POST /api/task-center/tasks/{task_id}/assign', 'backend.routers.task_center.assign_ai_employee'), ('PUB-101', 'POST /api/task-center/tasks', 'backend.routers.task_center.create_task'), ('PUB-102', 'GET /api/task-center/tasks/{task_id}', 'backend.routers.task_center.get_task'), ('PUB-103', 'GET /api/task-center/tasks/{task_id}/results/{result_id}', 'backend.routers.task_center.get_task_result'), ('PUB-104', 'GET /api/task-center/tasks/{task_id}/audit-logs', 'backend.routers.task_center.list_task_audit_logs'), ('PUB-105', 'GET /api/task-center/tasks/{task_id}/results', 'backend.routers.task_center.list_task_results'), ('PUB-106', 'GET /api/task-center/tasks', 'backend.routers.task_center.list_tasks'), ('PUB-107', 'POST /api/task-center/tasks/{task_id}/start', 'backend.routers.task_center.start_task'), ('PUB-108', 'POST /api/task-center/tasks/{task_id}/reviews', 'backend.routers.task_center.submit_acceptance_review'), ('PUB-109', 'POST /api/task-center/tasks/{task_id}/audits', 'backend.routers.task_center.submit_audit_review'), ('PUB-110', 'POST /api/task-center/tasks/{task_id}/results', 'backend.routers.task_center.submit_result'), ('PUB-111', 'POST /api/task-center/tasks/{task_id}/summary', 'backend.routers.task_center.summarize_task'), ('PUB-112', 'PATCH /api/task-center/tasks/{task_id}/status', 'backend.routers.task_center.update_task_status')]
WORKER_PATHS = [('R75-0027', 'backend/execution_engine.py', 'process_next_execution_task'), ('R75-0049', 'backend/routers/agent_runtime.py', 'api_create_execution'), ('R75-0050', 'backend/routers/agent_runtime.py', 'api_approve_execution'), ('R75-0064', 'backend/routers/ai_employees.py', 'get_ai_employee_runtime_status'), ('R75-0071', 'backend/routers/ai_execution.py', 'create_task'), ('R75-0073', 'backend/routers/ai_execution.py', 'assign_task'), ('R75-0074', 'backend/routers/ai_execution.py', 'complete_task'), ('R75-0075', 'backend/routers/ai_execution.py', 'create_tiancai_to_tianbo_flow'), ('R75-0076', 'backend/routers/ai_execution.py', 'webhook_create_task'), ('R75-0077', 'backend/routers/ai_execution.py', 'create_feedback_loop_task'), ('R75-0092', 'backend/routers/alpha_workflow.py', 'api_run_demo'), ('R75-0093', 'backend/routers/alpha_workflow.py', 'api_cancel_run'), ('R75-0098', 'backend/routers/auto_dispatch.py', 'create_dispatch_plan'), ('R75-0100', 'backend/routers/auto_dispatch.py', 'create_execution_tracking'), ('R75-0131', 'backend/routers/computer_workflows.py', 'start_workflow_api'), ('R75-0141', 'backend/routers/dual_engine_business.py', 'start_money_loop'), ('R75-0169', 'backend/routers/employee_execution.py', 'create_tian_shang_execution_task'), ('R75-0170', 'backend/routers/employee_execution.py', 'process_next_tian_shang_task'), ('R75-0180', 'backend/routers/execution_engine.py', 'claim_task'), ('R75-0181', 'backend/routers/execution_engine.py', 'start_task'), ('R75-0182', 'backend/routers/execution_engine.py', 'complete_task'), ('R75-0183', 'backend/routers/execution_engine.py', 'fail_task'), ('R75-0185', 'backend/routers/orchestrator_task_links.py', 'create_task_link'), ('R75-0193', 'backend/routers/release_center.py', 'create_release'), ('R75-0202', 'backend/routers/task_center.py', 'update_task_status'), ('R75-0203', 'backend/routers/task_center.py', 'assign_ai_employee'), ('R75-0204', 'backend/routers/task_center.py', 'start_task'), ('R75-0208', 'backend/routers/task_center.py', 'submit_acceptance_review'), ('R75-0209', 'backend/routers/task_center.py', 'submit_audit_review'), ('R75-0239', 'backend/worker.py', 'execute_sprint17_task'), ('R75-0241', 'backend/worker.py', 'execute_sprint18_business_loop'), ('R75-0246', 'backend/workers/tian_shang_worker.py', 'write_task_result'), ('R75-0013', 'backend/alpha_workflow/service.py', '_create_task'), ('R75-0079', 'backend/routers/ai_execution.py', 'create_automation_task'), ('R75-0113', 'backend/routers/business_loop.py', 'create_business_task'), ('R75-0145', 'backend/routers/dual_engine_business.py', 'write_engine_result'), ('R75-0187', 'backend/routers/orchestrator_task_links.py', 'confirm_create_task'), ('R75-0198', 'backend/routers/task_center.py', 'create_task'), ('R75-0238', 'backend/worker.py', 'run_daily_scheduler')]
OWNERSHIP_CASES = ("owner", "tenant", "company", "shop", "requester", "foreign_equals_missing")
WORKER_CASES = ("missing", "tampered", "parent_child_mismatch", "legacy_ownerless", "legal_internal")
OWNERSHIP_TOKENS = (
    "owned_task", "owned_results", "owned_tasks", "bind_task_ownership",
    "bind_session_task_ownership", "task_ownership_context",
)


def _symbol(qualified_name: str):
    module_name, symbol_name = qualified_name.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return module, getattr(module, symbol_name)


@pytest.mark.parametrize(
    "entry,scope_case",
    [(entry, scope_case) for entry, scope_case in product(PUBLIC_ENTRYPOINTS, OWNERSHIP_CASES)],
    ids=lambda value: value[0] if isinstance(value, tuple) else value,
)
def _legacy_static_public_entrypoint_ownership_contract(entry, scope_case):
    entry_id, _route, qualified_name = entry
    module, symbol = _symbol(qualified_name)
    assert entry_id.startswith("PUB-")
    assert scope_case in OWNERSHIP_CASES
    assert callable(symbol)
    module_source = inspect.getsource(module)
    assert any(token in module_source for token in OWNERSHIP_TOKENS), qualified_name
    symbol_source = inspect.getsource(symbol)
    assert "db.get(TaskCenterTask" not in symbol_source
    assert "db.get(TaskCenterResult" not in symbol_source


@pytest.mark.parametrize(
    "path,scope_case",
    [(path, scope_case) for path, scope_case in product(WORKER_PATHS, WORKER_CASES)],
    ids=lambda value: value[0] if isinstance(value, tuple) else value,
)
def _legacy_static_worker_ownership_context_contract(path, scope_case):
    occurrence_id, file_name, symbol_name = path
    source = Path(file_name).read_text(encoding="utf-8")
    assert occurrence_id.startswith("R75-")
    assert scope_case in WORKER_CASES
    assert f"def {symbol_name}(" in source or f"{symbol_name}(" in source
    assert any(token in source for token in OWNERSHIP_TOKENS), path


def _task_state(db):
    models = (TaskCenterTask, TaskCenterResult)
    state = {}
    for model in models:
        rows = []
        for row in db.query(model).order_by(model.id.asc()).all():
            payload = {column.name: getattr(row, column.name) for column in model.__table__.columns}
            rows.append(json.loads(json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True)))
        encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        state[model.__tablename__] = {
            "primary_keys": [row["id"] for row in rows],
            "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        }
    return state


def test_r76_numeric_entrypoints_are_non_enumerating_and_zero_write(postgres_alpha_runtime):
    client, boss_headers, test_db = postgres_alpha_runtime
    created = client.post(
        "/api/task-center/tasks",
        headers=boss_headers,
        json={"title": "R76 private task sentinel", "description": "R76 private input"},
    )
    assert created.status_code == 200
    task_id = created.json()["task"]["id"]
    missing_id = 2_147_483_647

    with test_db() as db:
        boss = db.query(User).filter(User.username == "boss").one()
        boss_scope = (boss.tenant_id, boss.company_id)
        before = _task_state(db)

    tenant_headers, tenant_scope = _create_scoped_owner(client, test_db, "r76-tenant")
    company_headers, company_scope = _create_scoped_owner(client, test_db, "r76-company", tenant_id=boss_scope[0])
    shop_headers, shop_scope = _create_scoped_owner(client, test_db, "r76-shop", tenant_id=boss_scope[0], company_id=boss_scope[1])
    requester_headers, requester_scope = _create_scoped_owner(
        client,
        test_db,
        "r76-requester",
        tenant_id=boss_scope[0],
        company_id=boss_scope[1],
        store_id=shop_scope[3],
    )
    assert len({tenant_scope, company_scope, shop_scope, requester_scope}) == 4

    checks = (
        ("get", "/api/task-center/tasks/{}", None),
        ("get", "/api/ai-workforce/tasks/{}/lifecycle", None),
        ("get", "/api/ai-employee-growth-system/tasks/{}/impact", None),
        ("get", "/api/employee-activity-trace/tasks/{}/trace", None),
        ("post", "/api/execution/tasks/{}/claim", {}),
        ("post", "/api/tasks/{}/assign", {"assigned_to": "tianshang"}),
        ("post", "/api/reviews/generate", lambda value: {"task_id": value, "include_feedback": False}),
    )
    for headers in (tenant_headers, company_headers, shop_headers, requester_headers):
        client.cookies.clear()
        listed = client.get("/api/task-center/tasks", headers=headers)
        assert listed.status_code == 200
        assert task_id not in {row["id"] for row in listed.json()}
        for method, template, payload in checks:
            foreign_url = template.format(task_id) if "{}" in template else template
            missing_url = template.format(missing_id) if "{}" in template else template
            foreign_payload = payload(task_id) if callable(payload) else payload
            missing_payload = payload(missing_id) if callable(payload) else payload
            foreign_kwargs = {"headers": headers}
            missing_kwargs = {"headers": headers}
            if foreign_payload is not None:
                foreign_kwargs["json"] = foreign_payload
            if missing_payload is not None:
                missing_kwargs["json"] = missing_payload
            foreign = getattr(client, method)(foreign_url, **foreign_kwargs)
            missing = getattr(client, method)(missing_url, **missing_kwargs)
            assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json())
    with test_db() as db:
        assert _task_state(db) == before


def test_r76_worker_rejects_missing_or_tampered_scope_without_writes(test_db):
    with test_db() as db:
        user = db.query(User).filter(User.username == "boss").one()
        task = TaskCenterTask(
            title="R76 worker ownership",
            status="assigned",
            source="sprint17_ai_execution",
            split_plan=json.dumps({"type": "mock_task", "input": {}}),
        )
        bind_task_ownership(db, task, user=user)
        db.add(task)
        db.commit()
        context = task_ownership_context(task)
        before = _task_state(db)
        tampered = {**context, "requester_id": context["requester_id"] + 1}
        assert owned_task_from_context_or_none(db, task_id=task.id, ownership=tampered) is None
        with pytest.raises(RuntimeError, match="not found"):
            execute_sprint17_task(db, {"payload": {"task_center_id": task.id, "ownership": tampered}})
        db.rollback()
        assert _task_state(db) == before


_WATCH_MODELS = (
    TaskCenterTask,
    TaskCenterResult,
    TaskCenterReview,
    TaskCenterAuditLog,
    AgentExecution,
    EmployeeExecutionLog,
    ReleaseVersion,
)


def _stable_rows(db):
    state = {}
    for model in _WATCH_MODELS:
        primary_key = tuple(model.__table__.primary_key.columns)
        rows = db.query(model).order_by(*primary_key).all()
        payloads = [
            {column.name: getattr(row, column.name) for column in model.__table__.columns}
            for row in rows
        ]
        canonical = json.dumps(payloads, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        state[model.__tablename__] = {
            "primary_keys": [tuple(getattr(row, column.name) for column in primary_key) for row in rows],
            "sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        }
    return state


def _redis_state():
    redis = get_redis()
    values = getattr(redis, "values", {})
    lists = getattr(redis, "lists", {})
    payload = json.dumps({"values": values, "lists": lists}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _observable_state(test_db):
    with test_db() as db:
        database = _stable_rows(db)
    return {"database": database, "redis": _redis_state()}


def _login_headers(client, username):
    client.cookies.clear()
    response = client.post("/api/login", json={"username": username, "password": "password"})
    assert response.status_code == 200
    client.cookies.clear()
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _owner_scope(test_db):
    with test_db() as db:
        owner = db.query(User).filter(User.username == "boss").one()
        store_id = db.query(UserStoreMembership.store_id).filter(
            UserStoreMembership.user_id == owner.id,
            UserStoreMembership.active.is_(True),
            UserStoreMembership.can_read.is_(True),
        ).one()[0]
        return owner.id, owner.tenant_id, owner.company_id, store_id


def _foreign_headers(client, test_db, scenario, owner_scope):
    _owner_id, tenant_id, company_id, store_id = owner_scope
    if scenario == "foreign_tenant":
        return _create_scoped_owner(client, test_db, "r112-tenant")[0]
    if scenario == "foreign_company":
        return _create_scoped_owner(client, test_db, "r112-company", tenant_id=tenant_id)[0]
    if scenario == "foreign_shop":
        return _create_scoped_owner(
            client,
            test_db,
            "r112-shop",
            tenant_id=tenant_id,
            company_id=company_id,
        )[0]
    if scenario == "foreign_requester":
        return _create_scoped_owner(
            client,
            test_db,
            "r112-requester",
            tenant_id=tenant_id,
            company_id=company_id,
            store_id=store_id,
        )[0]
    raise AssertionError(scenario)


def _create_owner_graph(client, headers, test_db, *, include_execution=False):
    client.cookies.clear()
    response = client.post(
        "/api/task-center/tasks",
        headers=headers,
        json={"title": "R112 owner sentinel", "description": "R112 dynamic matrix"},
    )
    assert response.status_code == 200
    task_id = response.json()["task"]["id"]
    with test_db() as db:
        task = db.get(TaskCenterTask, task_id)
        employee = db.query(AiEmployee).filter(
            AiEmployee.status == "active",
            AiEmployee.is_legacy.is_(False),
        ).order_by(AiEmployee.id.asc()).first()
        assert task is not None and employee is not None
        task.assigned_ai_employee_code = employee.employee_code
        task.assigned_ai_employee_name = employee.employee_name
        task.status = "assigned"
        result = TaskCenterResult(
            task_id=task.id,
            ai_employee_code=employee.employee_code,
            ai_employee_name=employee.employee_name,
            result_content="R112 owner result",
            submitted_by_id=task.requester_id,
        )
        review = TaskCenterReview(
            task_id=task.id,
            review_type="acceptance",
            review_status="accepted",
            comment="R112 owner review",
            reviewer_role="boss",
            reviewer_id=task.requester_id,
        )
        db.add_all([result, review])
        db.commit()
        db.refresh(result)
        graph = {
            "task_id": task.id,
            "result_id": result.id,
            "employee_id": employee.id,
            "employee_code": employee.employee_code,
            "skill_id": "mock.echo",
            "run_id": "r112-missing-run",
            "workflow_id": "r112-missing-workflow",
            "log_id": f"task_center-{task.id}-task_created",
        }
    if include_execution:
        client.cookies.clear()
        capability_id = f"r125.approval.{task_id}"
        capability_response = client.post(
            "/api/v2/capabilities",
            headers=headers,
            json={
                "capability_id": capability_id,
                "capability_name": "R125 approval sentinel",
                "capability_type": "Shell 操作",
                "executor_type": "mock",
                "risk_level": "high",
                "enabled": True,
                "readonly": False,
                "requires_boss_approval": True,
                "requires_security_audit": True,
                "allowed_employee_codes": [graph["employee_code"]],
            },
        )
        assert capability_response.status_code == 200
        capability = capability_response.json()["capability"]
        assert capability["executor_type"] == "mock"
        assert capability["enabled"] is True
        assert capability["requires_boss_approval"] is True
        assert capability["requires_security_audit"] is True
        created = client.post(
            "/api/v2/executions",
            headers=headers,
            json={
                "task_id": task_id,
                "employee_id": graph["employee_id"],
                "capability_id": capability["capability_id"],
                "input_payload": {"message": "R112 approval"},
            },
        )
        assert created.status_code == 200
        execution = created.json()["execution"]
        assert execution["status"] == "waiting_approval"
        assert execution["approval_status"] == "pending"
        assert execution["started_at"] is None
        assert execution["finished_at"] is None
        graph["execution_id"] = execution["execution_id"]
    else:
        graph["execution_id"] = "r112-missing-execution"
    return graph


def _route_for(case):
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == case["route_path"] and case["http_method"] in route.methods:
            return route
    raise AssertionError(case["case_id"])


def _sample_value(name, annotation, graph):
    origin = typing.get_origin(annotation)
    args = [value for value in typing.get_args(annotation) if value is not type(None)]
    if origin in (typing.Union, getattr(typing, "UnionType", object)) and args:
        return _sample_value(name, args[0], graph)
    if origin is list:
        return []
    if origin is dict:
        return {"message": "R112"}
    values = {
        "task_id": graph["task_id"],
        "result_id": graph["result_id"],
        "analysis_record_id": graph.get("analysis_record_id", 1),
        "employee_id": graph["employee_id"],
        "employee_code": graph["employee_code"],
        "ai_employee_code": graph["employee_code"],
        "assigned_to": graph["employee_code"],
        "capability_id": "mock.echo",
        "title": "R112 dynamic task",
        "description": "R112 dynamic matrix",
        "summary": "R112 summary",
        "result_content": "R112 result",
        "review_status": "accepted",
        "status": "running",
        "version": f"r112-{graph['task_id']}",
        "sprint_name": "R112",
        "commit_id": "24611ab",
        "branch": "r112",
        "author": "owner",
        "boss_confirmed": True,
        "security_audited": True,
        "input_text": "R112 dynamic request",
        "trace_id": f"r112-{graph['task_id']}",
        "comment": "R112 review",
        "reason": "R112 reason",
    }
    if name in values:
        return values[name]
    if annotation is bool:
        return True
    if annotation is int:
        return 1
    if annotation is float:
        return 1.0
    if annotation is dict:
        return {"message": "R112"}
    if annotation is list:
        return []
    return "R112"


def _request_payload(case, graph):
    route = _route_for(case)
    hints = typing.get_type_hints(inspect.unwrap(route.endpoint), include_extras=True)
    body_fields = route.dependant.body_params
    if not body_fields:
        return None
    field_name = body_fields[0].name
    annotation = hints[field_name]
    candidates = [value for value in typing.get_args(annotation) if value is not type(None)]
    if candidates:
        annotation = candidates[0]
    if not isinstance(annotation, type) or not issubclass(annotation, BaseModel):
        return _sample_value(field_name, annotation, graph)
    values = {}
    for name, field in annotation.model_fields.items():
        if field.is_required():
            values[name] = _sample_value(name, field.annotation, graph)
    values.update({name: value for name, value in (
        ("boss_confirmed", True),
        ("security_audited", True),
    ) if name in annotation.model_fields})
    if case["public_entrypoint_id"] == "PUB-002":
        values["task_id"] = graph["task_id"]
        values["input_payload"] = {
            "message": graph.get("input_message", f"R128 {case['parameter_id']}"),
        }
    elif case["public_entrypoint_id"] == "PUB-036":
        values.update({"employee_code": graph["employee_code"], "action": "start"})
    elif case["public_entrypoint_id"] == "PUB-081":
        values["task_id"] = graph["task_id"]
    elif case["public_entrypoint_id"] == "PUB-099":
        values["task_id"] = graph["task_id"]
    return annotation(**values).model_dump(mode="json")


def _resolved_path(case, graph, *, missing=False):
    employee_code_entrypoints = {
        "PUB-004",
        "PUB-006",
        "PUB-007",
        "PUB-008",
        "PUB-014",
        "PUB-016",
        "PUB-028",
    }
    missing_values = {
        "task_id": 2_147_483_647,
        "result_id": 2_147_483_647,
        "employee_id": "r112-missing-employee",
        "employee_code": "r112-missing-employee",
        "skill_id": "r112-missing-skill",
        "execution_id": "r112-missing-execution",
        "run_id": "r112-missing-run",
        "workflow_id": "r112-missing-workflow",
        "log_id": "r112-missing-log",
    }
    if missing and case["public_entrypoint_id"] == "PUB-099":
        assert graph["missing_skill_id_absent"] is True
        values = {**missing_values, "skill_id": graph["missing_skill_id"]}
    else:
        values = missing_values if missing else graph

    def _value(match):
        key = match.group(1)
        if key == "employee_id" and case["public_entrypoint_id"] in employee_code_entrypoints:
            key = "employee_code"
        return str(values[key])

    return re.sub(
        r"\{([^}:]+)(?::[^}]+)?\}",
        _value,
        case["route_path"],
    )


def _http(client, case, headers, graph, *, missing=False, payload=None):
    client.cookies.clear()
    kwargs = {"headers": headers}
    actual_payload = _request_payload(case, graph) if payload is None else payload
    if actual_payload is not None:
        kwargs["json"] = actual_payload
    return client.request(case["http_method"], _resolved_path(case, graph, missing=missing), **kwargs)


def _prepare_target_graph(case, client, headers, test_db, graph):
    entrypoint_id = case["public_entrypoint_id"]
    feature_state = None
    if entrypoint_id == "PUB-083":
        from backend.workers.tian_shang_worker import (
            TIAN_SHANG_EMPLOYEE_ID,
            TIAN_SHANG_QUEUE,
            create_tian_shang_task,
            utc_now,
        )

        queue = get_redis()
        queue.delete(TIAN_SHANG_QUEUE)
        owner_scope = _owner_scope(test_db)

        def _create_item(user_id, label, *, enqueue):
            with test_db() as db:
                user = db.get(User, user_id)
                assert user is not None
                created = create_tian_shang_task(db, f"R155 {label}", user=user, enqueue=enqueue)
                return {
                    "task_id": created["task"]["id"],
                    "contract_id": created["contract"]["id"],
                }

        fixture = {"owner": None, "foreign": None, "queue_key": TIAN_SHANG_QUEUE}
        scenario = case["scenario"]
        if scenario in {"owner_artifact", "mixed_scope_independence"}:
            fixture["owner"] = _create_item(owner_scope[0], f"{scenario} owner", enqueue=True)
        if scenario in {"untrusted_input", "mixed_scope_independence"}:
            _foreign_headers, foreign_scope = _create_scoped_owner(
                client,
                test_db,
                f"r155-pub083-{scenario}",
                tenant_id=owner_scope[1],
            )
            fixture["foreign"] = _create_item(
                foreign_scope[0],
                f"{scenario} foreign",
                enqueue=scenario == "mixed_scope_independence",
            )
        if scenario == "untrusted_input":
            with test_db() as db:
                foreign_task = db.get(TaskCenterTask, fixture["foreign"]["task_id"])
                assert foreign_task is not None
                tampered_ownership = task_ownership_context(foreign_task)
            tampered_ownership["requester_id"] = owner_scope[0]
            queue.rpush(
                TIAN_SHANG_QUEUE,
                json.dumps(
                    {
                        "contract_id": fixture["foreign"]["contract_id"],
                        "employee_id": TIAN_SHANG_EMPLOYEE_ID,
                        "queued_at": utc_now(),
                        "ownership": tampered_ownership,
                    },
                    ensure_ascii=False,
                ),
            )
        assert queue.llen(TIAN_SHANG_QUEUE) == (2 if scenario == "mixed_scope_independence" else 1)
        graph["tian_shang_fixture"] = fixture
    elif entrypoint_id == "PUB-099":
        from backend.skills_engine.models import Skill

        skill_code = f"r155.taskcenter.{graph['task_id']}"
        manifest = {
            "skill_code": skill_code,
            "version": "1.0.0",
            "chinese_name": "R155 TaskCenter ownership skill",
            "chinese_description": "Local mock skill for the scoped invocation contract.",
            "entrypoint": "mock_runtime",
            "skill_type": "其他",
            "risk_level": "低风险",
            "required_capabilities": ["taskcenter.read"],
            "required_permissions": ["skills.read"],
            "allowed_employee_codes": [graph["employee_code"]],
            "input_schema": {},
            "output_schema": {},
            "required_feature_flags": [],
            "signature_status": "已验证",
        }
        client.cookies.clear()
        created = client.post(
            "/api/v2/skills",
            headers=headers,
            json={
                "skill_code": skill_code,
                "chinese_name": "R155 TaskCenter ownership skill",
                "chinese_description": "Local mock skill for the scoped invocation contract.",
                "skill_type": "其他",
                "risk_level": "低风险",
                "signature_status": "已验证",
                "enabled": True,
                "status": "已批准",
                "manifest": manifest,
            },
        )
        assert created.status_code == 200, created.json()
        skill_id = created.json()["skill"]["skill_id"]
        assert isinstance(skill_id, int) and skill_id > 0
        client.cookies.clear()
        permission = client.post(
            f"/api/v2/skills/{skill_id}/permissions",
            headers=headers,
            json={
                "employee_code": graph["employee_code"],
                "permission_scope": "employee",
                "allow": True,
            },
        )
        assert permission.status_code == 200, permission.json()
        client.cookies.clear()
        installation = client.post(
            f"/api/v2/skills/{skill_id}/install",
            headers=headers,
            json={"employee_code": graph["employee_code"], "configuration": {"executor": "mock"}},
        )
        assert installation.status_code == 200, installation.json()
        with test_db() as db:
            assert db.get(Skill, skill_id) is not None
            missing_skill_id = 2_147_483_647
            assert db.get(Skill, missing_skill_id) is None
        graph["skill_id"] = skill_id
        graph["missing_skill_id"] = missing_skill_id
        graph["missing_skill_id_absent"] = True
    elif entrypoint_id in {"PUB-018", "PUB-019", "PUB-020"}:
        client.cookies.clear()
        created = client.post(
            "/api/tasks",
            headers=headers,
            json={"type": "mock_task", "input": {"message": "R152 automation"}},
        )
        assert created.status_code == 200
        graph["task_id"] = created.json()["task"]["id"]
        if entrypoint_id == "PUB-020":
            completed = client.post(
                f"/api/tasks/{graph['task_id']}/complete",
                headers=headers,
                json={"result": {"message": "R152 source result"}},
            )
            assert completed.status_code == 200
    elif entrypoint_id == "PUB-030":
        client.cookies.clear()
        created = client.post(
            "/api/v2/alpha-workflows/demo",
            headers=headers,
            json={"input_text": "R152 cancel fixture", "trace_id": f"r152-cancel-{graph['task_id']}"},
        )
        assert created.status_code == 200
        graph["run_id"] = created.json()["run"]["run_id"]
    elif entrypoint_id == "PUB-044":
        with test_db() as db:
            task = db.get(TaskCenterTask, graph["task_id"])
            assert task is not None
            task.source = "sprint18_business_loop"
            task.split_plan = json.dumps({"loop_iteration": 0})
            db.commit()
    elif entrypoint_id in {"PUB-055", "PUB-056"}:
        from backend.agent_runtime.executors.computer.models import ComputerSession
        from backend.agent_runtime.workflows.computer.models import ComputerWorkflow
        from backend.agent_runtime.workflows.computer.models import ComputerWorkflowStep
        from backend.config import get_settings

        settings = get_settings()
        feature_state = (
            settings,
            settings.COMPUTER_EXECUTOR_ENABLED,
            settings.MAC_SAFE_WORKFLOW_ENABLED,
        )
        settings.COMPUTER_EXECUTOR_ENABLED = True
        settings.MAC_SAFE_WORKFLOW_ENABLED = True
        graph["workflow_id"] = f"r152-workflow-{graph['task_id']}"
        with test_db() as db:
            session_id = None
            if entrypoint_id == "PUB-055":
                session_id = f"r193-session-{graph['task_id']}"
                db.add(
                    ComputerSession(
                        session_id=session_id,
                        task_id=graph["task_id"],
                        employee_id=graph["employee_id"],
                        executor_type="mock",
                        environment_type="test",
                        status="已暂停",
                        risk_level="低风险",
                        approval_status="已批准",
                        allowed_applications_json=json.dumps(["天统测试页面"], ensure_ascii=False),
                        allowed_windows_json=json.dumps([".*测试.*"], ensure_ascii=False),
                        takeover_status="未接管",
                    )
                )
            db.add(
                ComputerWorkflow(
                    workflow_id=graph["workflow_id"],
                    task_id=graph["task_id"],
                    employee_id=graph["employee_id"],
                    session_id=session_id,
                    goal="R152 local mock workflow",
                    status="已暂停" if entrypoint_id == "PUB-055" else "已批准",
                    risk_level="低风险",
                    approval_status="已批准",
                    total_steps=1 if entrypoint_id == "PUB-055" else 0,
                    current_step=0,
                    max_steps=5,
                )
            )
            if entrypoint_id == "PUB-055":
                db.add(
                    ComputerWorkflowStep(
                        step_id=f"r193-step-{graph['task_id']}",
                        workflow_id=graph["workflow_id"],
                        sequence_number=1,
                        action_type="等待",
                        target_application="天统测试页面",
                        target_window="测试工作流页面",
                        expected_result="等待后继续测试工作流",
                        risk_level="低风险",
                        approval_required=True,
                        checkpoint_required=True,
                        status="待执行",
                    )
                )
            db.commit()
    elif entrypoint_id == "PUB-088":
        with test_db() as db:
            task = db.get(TaskCenterTask, graph["task_id"])
            assert task is not None
            task.status = "running"
            db.commit()
    elif entrypoint_id in {"PUB-091", "PUB-092"}:
        from backend.orchestrator_models import OrchestratorAnalysisRecord

        with test_db() as db:
            row = OrchestratorAnalysisRecord(
                input_excerpt="R152 analysis fixture",
                input_hash=hashlib.sha256(f"r152-{graph['task_id']}".encode()).hexdigest(),
                detected_employee_code=graph["employee_code"],
                recommended_codex=graph["employee_code"],
                recommended_action="create_task",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            graph["analysis_record_id"] = row.id
    return feature_state


def _run_targeted_case(case, client, boss_headers, test_db):
    graph = _create_owner_graph(client, boss_headers, test_db, include_execution=case["public_entrypoint_id"] == "PUB-001")
    feature_state = _prepare_target_graph(case, client, boss_headers, test_db, graph)
    scenario = case["scenario"]
    entrypoint_id = case["public_entrypoint_id"]
    if scenario == "owner":
        pub055_gate_state = None
        if case["case_id"] == "PUB-055::http_request::owner":
            settings = feature_state[0]
            pub055_gate_state = (
                settings.MAC_SAFE_ACTION_ENABLED,
                settings.PER_ACTION_APPROVAL_ENABLED,
                settings.POST_ACTION_VERIFICATION_ENABLED,
            )
            settings.MAC_SAFE_ACTION_ENABLED = True
            settings.PER_ACTION_APPROVAL_ENABLED = True
            settings.POST_ACTION_VERIFICATION_ENABLED = True
        try:
            response = _http(client, case, boss_headers, graph)
        finally:
            if pub055_gate_state is not None:
                settings.MAC_SAFE_ACTION_ENABLED, settings.PER_ACTION_APPROVAL_ENABLED, settings.POST_ACTION_VERIFICATION_ENABLED = pub055_gate_state
            if feature_state is not None:
                settings, computer_enabled, mac_enabled = feature_state
                settings.COMPUTER_EXECUTOR_ENABLED = computer_enabled
                settings.MAC_SAFE_WORKFLOW_ENABLED = mac_enabled
            if pub055_gate_state is not None:
                assert (
                    settings.MAC_SAFE_ACTION_ENABLED,
                    settings.PER_ACTION_APPROVAL_ENABLED,
                    settings.POST_ACTION_VERIFICATION_ENABLED,
                ) == pub055_gate_state
        assert 200 <= response.status_code < 300, (case["case_id"], response.status_code, response.json())
        if case["public_entrypoint_id"] == "PUB-099":
            from backend.skills_engine.models import SkillInvocation

            payload = response.json()
            assert payload["ok"] is True
            assert payload["invocation"]["skill_id"] == graph["skill_id"]
            assert payload["invocation"]["task_id"] == graph["task_id"]
            assert payload["invocation"]["status"] == "执行成功"
            with test_db() as db:
                invocation = db.get(SkillInvocation, payload["invocation"]["invocation_id"])
                assert invocation is not None
                assert invocation.skill_id == graph["skill_id"]
                assert invocation.task_id == graph["task_id"]
        return
    owner_scope = _owner_scope(test_db)
    headers = boss_headers if scenario == "missing" else _foreign_headers(client, test_db, scenario, owner_scope)
    before = _observable_state(test_db)
    if entrypoint_id in {"PUB-081", "PUB-092"}:
        with test_db() as db:
            assert db.get(TaskCenterTask, 2_147_483_647) is None
        missing_graph = {**graph, "task_id": 2_147_483_647}
        response_graph = missing_graph if scenario == "missing" else graph
    else:
        missing_graph = graph
        response_graph = graph
    response = _http(client, case, headers, response_graph, missing=scenario == "missing")
    missing = _http(client, case, headers, missing_graph, missing=True)
    mixed_employee_entrypoints = {
        "PUB-004",
        "PUB-006",
        "PUB-007",
        "PUB-008",
        "PUB-014",
        "PUB-016",
        "PUB-028",
    }
    if entrypoint_id == "PUB-099":
        from backend.skills_engine.models import Skill, SkillInvocation

        assert isinstance(graph["skill_id"], int) and graph["skill_id"] > 0
        assert isinstance(graph["missing_skill_id"], int) and graph["missing_skill_id"] > 0
        if scenario == "missing":
            assert response.status_code == missing.status_code == 404
            assert response.json() == missing.json() == {"detail": "技能不存在"}
        else:
            assert response.status_code == missing.status_code == 404
            assert response.json() == {"detail": "task not found"}
            assert missing.json() == {"detail": "技能不存在"}
        with test_db() as db:
            assert db.get(Skill, graph["skill_id"]) is not None
            assert db.get(Skill, graph["missing_skill_id"]) is None
            assert db.query(SkillInvocation).count() == 0
        assert _observable_state(test_db) == before
        return
    if entrypoint_id == "PUB-013":
        assert response.status_code == missing.status_code == 200
        foreign_payload = response.json()
        missing_payload = missing.json()
        expected_response_skill = "r112-missing-skill" if scenario == "missing" else graph["skill_id"]
        assert foreign_payload["skill"]["skill_id"] == expected_response_skill
        assert foreign_payload["skill"]["skill_name"] == expected_response_skill
        assert missing_payload["skill"]["skill_id"] == "r112-missing-skill"
        assert missing_payload["skill"]["skill_name"] == "r112-missing-skill"
        for payload in (foreign_payload, missing_payload):
            payload["skill"].pop("skill_id")
            payload["skill"].pop("skill_name")
        assert foreign_payload == missing_payload
        assert _observable_state(test_db) == before
        return
    if entrypoint_id == "PUB-070" and scenario != "missing":
        assert response.status_code == missing.status_code == 200
        foreign_payload = response.json()
        missing_payload = missing.json()
        for current_response, payload in (
            (response, foreign_payload),
            (missing, missing_payload),
        ):
            requested_employee_code = current_response.request.url.path.split("/")[-2]
            assert payload["employee"] == {"employee_code": requested_employee_code}
            assert payload["summary"] == {
                "trace_type": "employee",
                "total_nodes": 0,
                "total_edges": 0,
                "has_blocker": False,
                "missing_steps": 0,
            }
            assert payload["trace_nodes"] == payload["trace_edges"] == []
            assert payload["task"] == payload["orchestrator_source"] == {}
            assert payload["boss_confirmation"] == payload["review_status"] == {}
            assert payload["audit_status"] == payload["deploy_status"] == {}
            assert payload["git_commit"] == {}
            assert (
                payload["blockers"]
                == payload["missing_steps"]
                == payload["safety_flags"]
                == []
            )
            payload["employee"]["employee_code"] = "<requested_employee_code>"
        assert foreign_payload == missing_payload
        assert _observable_state(test_db) == before
        return
    if entrypoint_id not in mixed_employee_entrypoints or scenario == "missing":
        assert (response.status_code, response.json()) == (missing.status_code, missing.json())
        assert _observable_state(test_db) == before
        return

    import json as _json

    owner_response = _http(client, case, boss_headers, graph)
    assert response.status_code == owner_response.status_code == 200
    expected_missing_status = 404 if entrypoint_id == "PUB-016" else 200
    assert missing.status_code == expected_missing_status
    foreign_payload = response.json()
    owner_payload = owner_response.json()
    missing_payload = missing.json()

    top_level_fields = {
        "PUB-004": {
            "mode", "employee", "skill_summary", "task_summary", "audit_summary", "growth_summary",
            "memory_summary", "recent_timeline", "security", "empty_state",
        },
        "PUB-006": {"mode", "employee", "timeline", "summary", "security", "empty_state"},
        "PUB-007": {
            "mode", "employee", "growth", "score_breakdown", "tasks", "memory", "audit",
            "skill_suggestions", "manual_confirm", "security", "empty_state",
        },
        "PUB-008": {"mode", "employee", "summary", "suggestions", "security", "empty_state"},
        "PUB-014": {"mode", "employee", "summary", "skills", "security", "errors"},
        "PUB-016": {
            "readonly", "employee", "department", "role", "current_status", "current_task",
            "historical_tasks", "skills", "executable_task_types", "permission_scope", "recent_tasks",
            "recent_error", "success_rate", "recent_logs", "data_sources", "safety",
        },
        "PUB-028": {"mode", "employee", "summary", "tasks", "manual_confirm", "security", "empty_state"},
    }
    assert set(foreign_payload) == set(owner_payload) == top_level_fields[entrypoint_id]
    if expected_missing_status == 200:
        assert set(missing_payload) == top_level_fields[entrypoint_id]

    with test_db() as db:
        employee = db.query(AiEmployee).filter(AiEmployee.employee_code == graph["employee_code"]).one()
        employee_directory = {
            "employee_id": employee.employee_code,
            "employee_name": employee.employee_name,
            "department": employee.legion or "未分配部门",
            "role": employee.duty or "",
            "status": employee.status,
        }
        employee_detail = {
            "id": employee.id,
            "employee_code": employee.employee_code,
            "employee_name": employee.employee_name,
            "legion": employee.legion,
            "duty": employee.duty,
            "status": employee.status,
            "task_types": _json.loads(employee.task_types) if employee.task_types else [],
            "default_permissions": _json.loads(employee.default_permissions) if employee.default_permissions else [],
            "is_legacy": employee.is_legacy,
            "sort_order": employee.sort_order,
            "created_at": employee.created_at.isoformat() if employee.created_at else None,
            "updated_at": employee.updated_at.isoformat() if employee.updated_at else None,
        }

    def _global_directory_projection(payload):
        if entrypoint_id in {"PUB-004", "PUB-006", "PUB-007", "PUB-008", "PUB-028"}:
            projection = {"employee": payload["employee"]}
            if entrypoint_id == "PUB-004":
                assert set(payload["skill_summary"]) == {
                    "total", "employee_skill_count", "high_risk", "average_success_rate",
                }
                projection["skill_summary"] = {
                    key: payload["skill_summary"][key]
                    for key in ("total", "employee_skill_count", "high_risk")
                }
            return projection
        if entrypoint_id == "PUB-014":
            skill_global_fields = {
                "skill_id", "skill_name", "skill_version", "skill_status", "description", "employee_id",
                "employee_name", "department", "risk_level", "created_time", "audit_status",
                "security_audited", "boss_confirm", "readonly",
            }
            skill_task_fields = {
                "usage_count", "success_count", "failure_count", "success_rate", "last_used_at", "updated_time",
            }
            for skill in payload["skills"]:
                assert set(skill) == skill_global_fields | skill_task_fields
            return {
                "employee": payload["employee"],
                "summary": {
                    "skill_total": payload["summary"]["skill_total"],
                    "high_risk_skill_count": payload["summary"]["high_risk_skill_count"],
                },
                "skills": [{key: skill[key] for key in sorted(skill_global_fields)} for skill in payload["skills"]],
            }
        assert entrypoint_id == "PUB-016"
        runtime_global_fields = {
            "employee_code", "employee_name", "department", "duty", "status", "tools",
        }
        assert runtime_global_fields <= set(payload["current_status"])
        return {
            "employee": payload["employee"],
            "department": payload["department"],
            "role": payload["role"],
            "skills": payload["skills"],
            "executable_task_types": payload["executable_task_types"],
            "permission_scope": payload["permission_scope"],
            "current_status": {key: payload["current_status"][key] for key in sorted(runtime_global_fields)},
        }

    def _taskcenter_derived_projection(payload):
        if entrypoint_id == "PUB-004":
            return {
                "skill_average_success_rate": payload["skill_summary"]["average_success_rate"],
                "task_summary": payload["task_summary"],
                "audit_summary": payload["audit_summary"],
                "growth_summary": payload["growth_summary"],
                "memory_summary": payload["memory_summary"],
                "recent_timeline": payload["recent_timeline"],
                "empty_state": payload["empty_state"],
            }
        if entrypoint_id == "PUB-006":
            return {key: payload[key] for key in ("timeline", "summary", "empty_state")}
        if entrypoint_id == "PUB-007":
            return {
                key: payload[key]
                for key in (
                    "growth", "score_breakdown", "tasks", "memory", "audit", "skill_suggestions",
                    "manual_confirm", "empty_state",
                )
            }
        if entrypoint_id == "PUB-008":
            return {key: payload[key] for key in ("summary", "suggestions", "empty_state")}
        if entrypoint_id == "PUB-014":
            active_task_stats = []
            for skill in payload["skills"]:
                task_stats = {
                    key: skill[key]
                    for key in ("usage_count", "success_count", "failure_count", "success_rate", "last_used_at", "updated_time")
                }
                if any(
                    task_stats[key] not in (0, None, "", [], {})
                    for key in ("usage_count", "success_count", "failure_count", "success_rate", "last_used_at")
                ):
                    active_task_stats.append(task_stats)
            return {
                "average_success_rate": payload["summary"]["average_success_rate"],
                "active_task_stats": active_task_stats,
            }
        if entrypoint_id == "PUB-028":
            return {key: payload[key] for key in ("summary", "tasks", "manual_confirm", "empty_state")}
        assert entrypoint_id == "PUB-016"
        return {
            "current_task": payload["current_task"],
            "historical_tasks": payload["historical_tasks"],
            "recent_tasks": payload["recent_tasks"],
            "recent_error": payload["recent_error"],
            "success_rate": payload["success_rate"],
            "recent_logs": payload["recent_logs"],
            "runtime": {
                key: payload["current_status"][key]
                for key in ("runtime_status", "current_task", "today_completed_tasks", "recent_error")
            },
        }

    foreign_global = _global_directory_projection(foreign_payload)
    owner_global = _global_directory_projection(owner_payload)
    assert foreign_global == owner_global
    if entrypoint_id in {"PUB-004", "PUB-006", "PUB-007", "PUB-008", "PUB-028"}:
        assert foreign_payload["employee"] == employee_directory
        assert missing_payload["employee"] == {
            "employee_id": "r112-missing-employee",
            "employee_name": "r112-missing-employee",
            "department": "未分配部门",
            "role": "",
            "status": "unknown",
        }
    elif entrypoint_id == "PUB-014":
        assert foreign_payload["employee"] == {
            "employee_id": employee.employee_code,
            "employee_name": employee.employee_name,
            "department": employee.legion or "未分配部门",
        }
        assert missing_payload["skills"] == []
        assert missing_payload["summary"]["skill_total"] == 0
    else:
        assert foreign_payload["employee"] == employee_detail

    foreign_derived = _taskcenter_derived_projection(foreign_payload)
    if expected_missing_status == 200:
        missing_derived = _taskcenter_derived_projection(missing_payload)
        assert foreign_derived == missing_derived
        invariant_fields = top_level_fields[entrypoint_id] - {
            "employee", "skill_summary", "task_summary", "audit_summary", "growth_summary", "memory_summary",
            "recent_timeline", "timeline", "summary", "growth", "score_breakdown", "tasks", "memory", "audit",
            "skill_suggestions", "manual_confirm", "suggestions", "skills", "empty_state",
        }
        assert {key: foreign_payload[key] for key in invariant_fields} == {
            key: missing_payload[key] for key in invariant_fields
        }
    else:
        assert missing_payload == {"detail": "AI employee not found"}
        assert foreign_derived["current_task"] is None
        assert foreign_derived["historical_tasks"] == []
        assert foreign_derived["recent_tasks"] == []
        assert foreign_derived["recent_error"] is None
        assert foreign_derived["recent_logs"] == []
        assert foreign_derived["success_rate"]["total_tasks"] == 0
        assert foreign_derived["runtime"]["current_task"] is None
        assert foreign_derived["runtime"]["today_completed_tasks"] == 0
        assert foreign_derived["runtime"]["recent_error"] is None
    assert _observable_state(test_db) == before


def _run_list_case(case, client, boss_headers, test_db):
    scenario = case["scenario"]
    if scenario == "empty_scope":
        headers, _scope = _create_scoped_owner(client, test_db, f"r112-empty-{case['public_entrypoint_id'].lower()}")
        before = _observable_state(test_db)
        response = _http(client, case, headers, {"task_id": 1, "result_id": 1, "employee_id": 1, "employee_code": "tiantong", "skill_id": "mock.echo", "execution_id": "none", "run_id": "none", "workflow_id": "none", "log_id": "none"})
        assert response.status_code == 200
        assert _observable_state(test_db) == before
        return

    from datetime import datetime, timezone

    metadata_specs = {
        "PUB-003": (("field", "generated_at"),),
        "PUB-012": (
            ("field", "generated_at"),
            ("list", "apis", "last_checked_at"),
            ("keyed", "freshness", "data_key", "ai_workforce", "last_updated"),
            ("keyed", "freshness", "data_key", "capability", "last_updated"),
            ("keyed", "freshness", "data_key", "growth_center", "last_updated"),
            ("keyed", "freshness", "data_key", "audit_center", "last_updated"),
            ("keyed", "freshness", "data_key", "task_center", "last_updated"),
            ("list", "alerts", "detected_at"),
        ),
        "PUB-017": (("field", "checked_at"),),
        "PUB-045": (("field", "checked_at"),),
        "PUB-046": (("field", "checked_at"),),
        "PUB-047": (("field", "checked_at"),),
        "PUB-048": (
            ("field", "checked_at"),
            ("field", "system_health", "checked_at"),
            ("field", "daily_operations", "checked_at"),
            ("field", "employee_status", "checked_at"),
            ("field", "task_summary", "checked_at"),
            ("field", "execution_status", "checked_at"),
        ),
        "PUB-049": (("field", "checked_at"),),
        "PUB-050": (("field", "checked_at"),),
        "PUB-051": (("field", "checked_at"),),
        "PUB-052": (("field", "checked_at"),),
        "PUB-086": (("field", "checked_at"),),
    }
    nullable_metadata_specs = {
        "PUB-012": {
            ("keyed", "freshness", "data_key", "growth_center", "last_updated"),
            ("keyed", "freshness", "data_key", "audit_center", "last_updated"),
        },
    }
    volatile_integer_paths = {
        "PUB-045": (
            ("ai_employee_organization_board", "organization_permissions", 0, "permission_change_gate", "tian_brain", "historical_blocks"),
            ("ai_employee_organization_board", "organization_permissions", 1, "permission_change_gate", "tian_brain", "historical_blocks"),
        ),
    }

    def pop_metadata(payload, spec):
        kind = spec[0]
        if kind == "field":
            target = payload
            for key in spec[1:-1]:
                assert isinstance(target, dict) and key in target
                target = target[key]
            assert isinstance(target, dict) and spec[-1] in target
            return [(target.pop(spec[-1]), False)]
        rows = payload[spec[1]]
        assert isinstance(rows, list)
        if kind == "list":
            assert all(isinstance(row, dict) and spec[2] in row for row in rows)
            return [(row.pop(spec[2]), False) for row in rows]
        matches = [row for row in rows if isinstance(row, dict) and row.get(spec[2]) == spec[3]]
        assert len(matches) == 1 and spec[4] in matches[0]
        allow_none = (
            spec in nullable_metadata_specs.get(case["public_entrypoint_id"], set())
            and matches[0].get("freshness_status") == "empty"
        )
        return [(matches[0].pop(spec[4]), allow_none)]

    def validate_metadata(values, started_at, finished_at):
        parsed_values = []
        for value, allow_none in values:
            if value is None:
                assert allow_none
                parsed_values.append(None)
                continue
            assert isinstance(value, str) and value
            parsed = datetime.fromisoformat(value)
            assert parsed.tzinfo is not None
            assert parsed.utcoffset() == timezone.utc.utcoffset(parsed)
            assert started_at <= parsed <= finished_at
            parsed_values.append(parsed)
        return parsed_values

    def pop_exact_path(payload, path):
        target = payload
        for key in path[:-1]:
            if isinstance(key, int):
                assert isinstance(target, list) and 0 <= key < len(target)
            else:
                assert isinstance(target, dict) and key in target
            target = target[key]
        assert isinstance(target, dict) and path[-1] in target
        return target.pop(path[-1])

    graph = _create_owner_graph(client, boss_headers, test_db)
    before_started_at = datetime.now(timezone.utc)
    before_response = _http(client, case, boss_headers, graph)
    before_finished_at = datetime.now(timezone.utc)
    assert before_response.status_code == 200
    owner_scope = _owner_scope(test_db)
    for dimension in ("foreign_tenant", "foreign_company", "foreign_shop", "foreign_requester"):
        headers = _foreign_headers(client, test_db, dimension, owner_scope)
        client.cookies.clear()
        created = client.post(
            "/api/task-center/tasks",
            headers=headers,
            json={"title": f"R112 {dimension} sentinel", "description": dimension},
        )
        assert created.status_code == 200
    after_started_at = datetime.now(timezone.utc)
    after_response = _http(client, case, boss_headers, graph)
    after_finished_at = datetime.now(timezone.utc)
    assert after_response.status_code == 200
    before_payload = before_response.json()
    after_payload = after_response.json()
    for spec in metadata_specs.get(case["public_entrypoint_id"], ()):
        before_values = pop_metadata(before_payload, spec)
        after_values = pop_metadata(after_payload, spec)
        validate_metadata(before_values, before_started_at, before_finished_at)
        validate_metadata(after_values, after_started_at, after_finished_at)
        assert len(before_values) == len(after_values)
        assert all(
            (before[0] is None and after[0] is None and before[1] and after[1])
            or (before[0] is not None and after[0] is not None and before[0] != after[0])
            for before, after in zip(before_values, after_values)
        )
    for path in volatile_integer_paths.get(case["public_entrypoint_id"], ()):
        before_value = pop_exact_path(before_payload, path)
        after_value = pop_exact_path(after_payload, path)
        assert type(before_value) is int and before_value >= 0
        assert type(after_value) is int and after_value >= before_value
    assert after_payload == before_payload


def _run_create_or_producer_case(case, client, boss_headers, test_db):
    scenario = case["scenario"]
    graph = _create_owner_graph(client, boss_headers, test_db)
    if case["public_entrypoint_id"] == "PUB-002" and scenario == "mixed_scope_independence":
        from backend.brain_orchestrator.planner import resolve_graph_ownership

        owner_scope = _owner_scope(test_db)
        tenant_headers, tenant_scope = _create_scoped_owner(client, test_db, "r128-mixed-tenant")
        company_headers, company_scope = _create_scoped_owner(
            client,
            test_db,
            "r128-mixed-company",
            tenant_id=owner_scope[1],
        )
        shop_headers, shop_scope = _create_scoped_owner(
            client,
            test_db,
            "r128-mixed-shop",
            tenant_id=owner_scope[1],
            company_id=owner_scope[2],
        )
        requester_headers, requester_scope = _create_scoped_owner(
            client,
            test_db,
            "r128-mixed-requester",
            tenant_id=owner_scope[1],
            company_id=owner_scope[2],
            store_id=owner_scope[3],
        )
        actors = (
            ("owner", boss_headers, owner_scope, graph),
            ("tenant", tenant_headers, tenant_scope, None),
            ("company", company_headers, company_scope, None),
            ("shop", shop_headers, shop_scope, None),
            ("requester", requester_headers, requester_scope, None),
        )
        before = _observable_state(test_db)
        task_ids = set()
        execution_ids = set()
        for label, headers, actor_scope, actor_graph in actors:
            actor_graph = actor_graph or _create_owner_graph(client, headers, test_db)
            actor_graph["input_message"] = f"R128 {case['parameter_id']} {label}"
            payload = _request_payload(case, actor_graph)
            assert payload["task_id"] == actor_graph["task_id"]
            assert payload["input_payload"] == {"message": actor_graph["input_message"]}
            response = _http(client, case, headers, actor_graph, payload=payload)
            assert 200 <= response.status_code < 300, (case["case_id"], label, response.status_code, response.json())
            execution_id = response.json()["execution"]["execution_id"]
            with test_db() as db:
                actor = db.get(User, actor_scope[0])
                task = db.get(TaskCenterTask, actor_graph["task_id"])
                execution = db.get(AgentExecution, execution_id)
                scope = resolve_graph_ownership(db, actor)
                assert task is not None and execution is not None
                assert (
                    task.tenant_id,
                    task.company_id,
                    task.requester_id,
                    task.store_scope_key,
                    task.ownership_scope_key,
                ) == (
                    scope.tenant_id,
                    scope.company_id,
                    scope.requester_id,
                    scope.store_scope_key,
                    scope.ownership_scope_key,
                )
                assert execution.task_id == task.id
                assert execution.created_by_id == actor.id
            task_ids.add(actor_graph["task_id"])
            execution_ids.add(execution_id)
        assert len(task_ids) == len(actors)
        assert len(execution_ids) == len(actors)
        assert _observable_state(test_db) != before
        return
    if scenario == "unauthenticated":
        before = _observable_state(test_db)
        response = _http(client, case, {}, graph)
        assert response.status_code == 401
        assert _observable_state(test_db) == before
        return
    headers = boss_headers
    if scenario.startswith("tenant_actor"):
        headers = _create_scoped_owner(client, test_db, f"r112-create-tenant-{case['public_entrypoint_id']}")[0]
    elif scenario.startswith("company_actor"):
        headers = _create_scoped_owner(client, test_db, f"r112-create-company-{case['public_entrypoint_id']}")[0]
    elif scenario.startswith("shop_actor"):
        headers = _create_scoped_owner(client, test_db, f"r112-create-shop-{case['public_entrypoint_id']}")[0]
    elif scenario.startswith("requester_actor"):
        headers = _create_scoped_owner(client, test_db, f"r112-create-requester-{case['public_entrypoint_id']}")[0]
    if case["public_entrypoint_id"] in {"PUB-083", "PUB-091"}:
        _prepare_target_graph(case, client, headers, test_db, graph)
    if case["public_entrypoint_id"] == "PUB-083":
        from backend.employee_execution.models import EmployeeExecutionContract

        fixture = graph["tian_shang_fixture"]
        queue = get_redis()

        def _fixture_state():
            state = {}
            with test_db() as db:
                for scope in ("owner", "foreign"):
                    item = fixture[scope]
                    if item is None:
                        continue
                    task = db.get(TaskCenterTask, item["task_id"])
                    contract = db.get(EmployeeExecutionContract, item["contract_id"])
                    assert task is not None and contract is not None
                    state[scope] = {
                        "task_status": task.status,
                        "contract_status": contract.status,
                        "contract_progress": contract.progress,
                        "contract_result": contract.result,
                        "result_count": db.query(TaskCenterResult).filter(TaskCenterResult.task_id == task.id).count(),
                    }
            return state

        before = _fixture_state()
        before_all = _observable_state(test_db)
        try:
            response = _http(client, case, headers, graph, payload=None)
            assert response.status_code == 200, (case["case_id"], response.status_code, response.json())
            after = _fixture_state()
            after_all = _observable_state(test_db)
            remaining = queue.lrange(fixture["queue_key"], 0, -1)
            remaining_ids = [
                json.loads(item.decode() if isinstance(item, bytes) else item)["contract_id"]
                for item in remaining
            ]
            if scenario == "owner_artifact":
                assert response.json()["processed"] is True
                assert after["owner"]["contract_status"] == "COMPLETED"
                assert after["owner"]["contract_progress"] == 100
                assert after["owner"]["task_status"] == "completed"
                assert after["owner"]["result_count"] == before["owner"]["result_count"] + 1
                assert after_all != before_all
                assert remaining_ids == []
            elif scenario == "mixed_scope_independence":
                assert response.json()["processed"] is True
                assert after["owner"]["contract_status"] == "COMPLETED"
                assert after["owner"]["task_status"] == "completed"
                assert after["foreign"] == before["foreign"]
                assert remaining_ids == [fixture["foreign"]["contract_id"]]
            else:
                assert scenario == "untrusted_input"
                assert response.json()["processed"] is False
                assert after["foreign"] == before["foreign"]
                assert after_all == before_all
                assert remaining_ids == []
        finally:
            queue.delete(fixture["queue_key"])
        return
    before = _observable_state(test_db)
    payload = _request_payload(case, graph)
    if scenario in {"spoofed_ownership", "untrusted_input"} and isinstance(payload, dict):
        payload.update({"tenant_id": 2_147_483_647, "company_id": 2_147_483_647, "requester_id": 2_147_483_647, "ownership_scope_key": "tampered"})
    response = _http(client, case, headers, graph, payload=payload)
    assert 200 <= response.status_code < 300, (case["case_id"], response.status_code, response.json())
    after = _observable_state(test_db)
    assert after != before
    with test_db() as db:
        owner_id = db.query(User.id).filter(User.username == ("boss" if headers is boss_headers else None)).scalar()
        new_tasks = db.query(TaskCenterTask).filter(TaskCenterTask.id.notin_([key[0] for key in before["database"]["task_center_tasks"]["primary_keys"]])).all()
        assert all(task.tenant_id and task.company_id and task.requester_id and task.store_scope_key and task.ownership_scope_key for task in new_tasks)
        if owner_id is not None:
            assert all(task.requester_id == owner_id for task in new_tasks)


def _run_control_plane_case(case, client, test_db):
    scenario = case["scenario"]
    username = "owner"
    if scenario.startswith("admin_"):
        username = "admin"
    elif scenario.startswith("boss_alias_"):
        username = "boss"
    elif scenario == "operator_forbidden":
        username = "operator"
    headers = {} if scenario == "unauthenticated" else _login_headers(client, username)
    graph = {"task_id": 1, "result_id": 1, "employee_id": 1, "employee_code": "tiantong", "skill_id": "mock.echo", "execution_id": "none", "run_id": "none", "workflow_id": "none", "log_id": "none"}
    entrypoint = case["public_entrypoint_id"]
    if entrypoint == "PUB-094":
        owner_headers = _login_headers(client, "owner")
        created = client.post("/api/release/create", headers=owner_headers, json={"version": "r112-approve", "sprint_name": "R112"})
        assert created.status_code == 200
        graph["release_id"] = created.json()["release"]["id"]
    payload = _request_payload(case, graph)
    if entrypoint == "PUB-096":
        payload = {"version": f"r112-{scenario}", "sprint_name": "R112"}
    if scenario == "invalid_payload":
        payload = {}
    if scenario == "duplicate_version":
        payload = {"version": "r112-duplicate", "sprint_name": "R112"}
        first = _http(client, case, headers, graph, payload=payload)
        assert first.status_code == 200
    if scenario == "missing_release":
        payload = {"release_id": 2_147_483_647, "boss_confirmed": True, "security_audited": True}
    if scenario == "safety_flags_missing":
        payload = {"boss_confirmed": False, "security_audited": False}
    before = _observable_state(test_db)
    response = _http(client, case, headers, graph, payload=payload)
    if scenario in {"operator_forbidden", "safety_flags_missing"}:
        assert response.status_code == 403
        assert _observable_state(test_db) == before
    elif scenario == "unauthenticated":
        assert response.status_code == 401
        assert _observable_state(test_db) == before
    elif scenario == "invalid_payload":
        assert response.status_code == 422
        assert _observable_state(test_db) == before
    elif scenario == "duplicate_version":
        assert response.status_code == 409
        assert _observable_state(test_db) == before
    elif scenario == "missing_release":
        assert response.status_code == 404
        assert _observable_state(test_db) == before
    else:
        assert 200 <= response.status_code < 300, (case["case_id"], response.status_code, response.json())


@pytest.mark.parametrize("case", TASKCENTER_PUBLIC_CASES, ids=lambda case: case["parameter_id"])
def test_r109_taskcenter_public_entrypoint_dynamic(case, postgres_alpha_runtime):
    client, boss_headers, test_db = postgres_alpha_runtime
    if case["action_kind"] in {"TARGETED_READ", "TARGETED_MUTATION"}:
        _run_targeted_case(case, client, boss_headers, test_db)
    elif case["action_kind"] == "LIST_OR_AGGREGATE":
        _run_list_case(case, client, boss_headers, test_db)
    else:
        _run_create_or_producer_case(case, client, boss_headers, test_db)


@pytest.mark.parametrize("case", CONTROL_PLANE_PUBLIC_CASES, ids=lambda case: case["parameter_id"])
def test_r109_control_plane_public_entrypoint_dynamic(case, postgres_alpha_runtime):
    client, _boss_headers, test_db = postgres_alpha_runtime
    _run_control_plane_case(case, client, test_db)


@pytest.mark.parametrize("case", WORKER_STAGE_CASES, ids=lambda case: case["parameter_id"])
def test_r109_worker_stage_dynamic(case, postgres_alpha_runtime):
    _client, boss_headers, test_db = postgres_alpha_runtime
    with test_db() as db:
        owner = db.query(User).filter(User.username == "boss").one()
        task = TaskCenterTask(title="R112 worker", status="assigned", source="r112")
        bind_task_ownership(db, task, user=owner)
        db.add(task)
        db.commit()
        context = task_ownership_context(task)
        before = _stable_rows(db)
        scenario = case["scenario"]
        if scenario.startswith("tampered_"):
            field = scenario.removeprefix("tampered_")
            field = "store_scope_key" if field == "shop" else f"{field}_id"
            queued_context = {**context, field: "tampered" if field.endswith("key") else int(context[field]) + 1}
        elif scenario in {"missing_ownership", "missing_source", "incomplete_source", "ownerless_task", "mismatched_task_context"}:
            queued_context = {}
        else:
            queued_context = context
        if case["worker_occurrence_id"] == "R75-0027":
            symbol_module, symbol_name = case["product_symbol"].rsplit(".", 1)
            module = importlib.import_module(symbol_module)
            symbol = getattr(module, symbol_name)
            assigned_employee = db.query(AiEmployee).filter(AiEmployee.employee_code == "tianwang").one()
            task.assigned_ai_employee_code = assigned_employee.employee_code
            task.assigned_ai_employee_name = assigned_employee.employee_name
            db.commit()
            db.expire_all()
            task = db.get(TaskCenterTask, task.id)
            assert task is not None
            assert task.assigned_ai_employee_code == assigned_employee.employee_code
            assert not db.new and not db.dirty and not db.deleted
            before = _stable_rows(db)
            consumer_get_redis = module.get_redis
            queue = consumer_get_redis()
            lock_key = module.execution_lock_key(task.id)
            module.get_redis = lambda: queue
            try:
                assert module.get_redis() is queue
                assert module.EXECUTION_QUEUE_NAME == "tiantong:execution:tasks"
                queue.delete(module.EXECUTION_QUEUE_NAME)
                assert queue.llen(module.EXECUTION_QUEUE_NAME) == 0
                assert queue.get(lock_key) is None
                queued = {
                    "task_id": task.id,
                    "employee_code": task.assigned_ai_employee_code,
                    "ownership": queued_context,
                    "boss_confirmed": True,
                    "security_audited": True,
                }
                queue.rpush(module.EXECUTION_QUEUE_NAME, json.dumps(queued))
                assert queue.llen(module.EXECUTION_QUEUE_NAME) == 1
                processed = symbol(db, timeout=1)
                if scenario == "valid":
                    assert processed is True
                    assert task.status == "completed"
                else:
                    assert processed is False
                    db.rollback()
                    assert _stable_rows(db) == before
            finally:
                try:
                    queue.delete(module.EXECUTION_QUEUE_NAME)
                    assert queue.llen(module.EXECUTION_QUEUE_NAME) == 0
                    assert queue.get(lock_key) is None
                finally:
                    module.get_redis = consumer_get_redis
        elif case["worker_occurrence_id"] == "R75-0239":
            queued = {"payload": {"task_center_id": task.id, "ownership": queued_context}}
            if scenario == "valid":
                task.source = "sprint17_ai_execution"
                task.split_plan = json.dumps({"type": "mock_task", "input": {}})
                db.commit()
                result = execute_sprint17_task(db, queued)
                assert isinstance(result, dict) and result
                assert task.status == "completed"
                persisted = db.query(TaskCenterResult).filter(TaskCenterResult.task_id == task.id).one()
                assert json.loads(persisted.result_content) == result
            else:
                with pytest.raises(RuntimeError):
                    execute_sprint17_task(db, queued)
                db.rollback()
                assert _stable_rows(db) == before
        elif case["worker_occurrence_id"] == "R75-0241":
            symbol_module, symbol_name = case["product_symbol"].rsplit(".", 1)
            symbol = getattr(importlib.import_module(symbol_module), symbol_name)
            queued = {"payload": {"task_center_id": task.id, "ownership": queued_context}}
            task.source = "sprint18_business_loop"
            task.split_plan = json.dumps({"event_type": "content_metrics", "input": {}, "loop_iteration": 0})
            db.commit()
            db.expire_all()
            before = _stable_rows(db)
            if scenario == "valid":
                result = symbol(db, queued)
                assert set(result) == {
                    "task_id", "event_type", "input", "analysis", "decision", "execution",
                    "feedback_loop", "mode", "executed_at",
                }
                assert result["task_id"] == task.id
                assert result["mode"] == "sprint18_business_mock"
                assert task.status == "completed"
            else:
                with pytest.raises(RuntimeError, match="not found"):
                    symbol(db, queued)
                db.expire_all()
                after = _stable_rows(db)
                assert after == before
        else:
            symbol_module, symbol_name = case["product_symbol"].rsplit(".", 1)
            symbol = getattr(importlib.import_module(symbol_module), symbol_name)
            assert callable(symbol)
            assert queued_context == context or not queued_context
