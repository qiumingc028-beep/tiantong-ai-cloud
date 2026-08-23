from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session as OrmSession

from backend.agent_runtime.workflows.computer.constants import WORKFLOW_ACTION_TYPES
from backend.agent_runtime.executors.computer.models import (
    ComputerAction,
    ComputerEvidence,
    ComputerPolicyEvent,
    ComputerSession,
)
from backend.agent_runtime.executors.computer.actions.models import (
    ComputerActionApproval,
    ComputerActionPlan,
    ComputerActionTarget,
)
from backend.agent_runtime.workflows.computer.models import (
    ComputerWorkflow,
    ComputerWorkflowApproval,
    ComputerWorkflowCheckpoint,
    ComputerWorkflowRecovery,
    ComputerWorkflowStep,
    ComputerWorkflowVerification,
)
from backend.agent_runtime.workflows.computer.recovery import record_recovery
from backend.agent_runtime.workflows.computer.verifier import verify_step_result
from backend.models import User, UserStoreMembership
from backend.task_center_ownership import bind_session_task_ownership
from tests.test_v2_alpha_postgresql_migration_regression import _create_scoped_owner


def _enable_workflow_flags(monkeypatch):
    class _Settings:
        IS_PRODUCTION = False
        MAC_SAFE_WORKFLOW_ENABLED = True
        MAC_MULTI_STEP_ENABLED = True
        COMPUTER_EXECUTOR_ENABLED = True
        OPENCLAW_ADAPTER_ENABLED = False
        ISOLATED_DESKTOP_ENABLED = False
        SCREEN_CAPTURE_ENABLED = True
        HUMAN_TAKEOVER_ENABLED = False
        COMPUTER_ALLOWED_APPLICATIONS = ["天统测试页面"]
        COMPUTER_BLOCKED_APPLICATIONS = ["Terminal", "iTerm", "系统设置", "钥匙串", "密码管理器"]
        COMPUTER_ALLOWED_WINDOW_PATTERNS = [".*测试.*"]
        COMPUTER_BLOCKED_WINDOW_PATTERNS = ["Terminal", "iTerm", "系统设置", "钥匙串", "密码管理器"]
        WORKFLOW_SCOPE_APPROVAL_ENABLED = True
        WORKFLOW_CHECKPOINT_APPROVAL_ENABLED = True
        WORKFLOW_AUTO_CONTINUE_ENABLED = False
        MAC_SAFE_ACTION_ENABLED = True
        MAC_SAFE_MOUSE_MOVE_ENABLED = True
        MAC_SAFE_CLICK_ENABLED = True
        MAC_SAFE_TEXT_INPUT_ENABLED = True
        PER_ACTION_APPROVAL_ENABLED = True
        POST_ACTION_VERIFICATION_ENABLED = True
        CLIPBOARD_READ_ENABLED = False
        CLIPBOARD_WRITE_ENABLED = False
        FILE_UPLOAD_ENABLED = False
        FILE_DOWNLOAD_ENABLED = False

    monkeypatch.setattr("backend.agent_runtime.workflows.computer.validator.get_settings", lambda: _Settings())
    monkeypatch.setattr("backend.agent_runtime.workflows.computer.runner.get_settings", lambda: _Settings())
    monkeypatch.setattr("backend.agent_runtime.executors.computer.actions.policy.get_settings", lambda: _Settings())
    monkeypatch.setattr("backend.agent_runtime.executors.computer.policy.get_settings", lambda: _Settings())
    monkeypatch.setattr(
        "backend.skills_engine.permissions.get_flag",
        lambda name: name in {
            "COMPUTER_EXECUTOR_ENABLED",
            "MAC_SAFE_WORKFLOW_ENABLED",
            "MAC_MULTI_STEP_ENABLED",
            "WORKFLOW_SCOPE_APPROVAL_ENABLED",
            "WORKFLOW_CHECKPOINT_APPROVAL_ENABLED",
            "MAC_SAFE_ACTION_ENABLED",
            "PER_ACTION_APPROVAL_ENABLED",
            "POST_ACTION_VERIFICATION_ENABLED",
            "MAC_SAFE_MOUSE_MOVE_ENABLED",
            "MAC_SAFE_CLICK_ENABLED",
            "MAC_SAFE_TEXT_INPUT_ENABLED",
        },
    )
    return _Settings


def _create_workflow_payload(task_id=None):
    payload = {
        "goal": "测试工作流：先观察，再点击测试按钮",
        "risk_level": "低风险",
        "max_steps": 5,
        "steps": [
            {
                "action_type": "移动鼠标",
                "target_application": "天统测试页面",
                "target_window": "测试工作流页面",
                "expected_result": "鼠标移动到测试按钮附近",
                "risk_level": "低风险",
                "approval_required": False,
                "checkpoint_required": False,
            },
            {
                "action_type": "单击",
                "target_application": "天统测试页面",
                "target_window": "测试工作流页面",
                "target_control": "普通按钮",
                "target_description": "测试按钮",
                "expected_result": "按钮完成单击",
                "risk_level": "中低风险",
                "approval_required": True,
                "checkpoint_required": True,
            },
        ],
    }
    if task_id is not None:
        payload["task_id"] = task_id
    return payload


def _create_owned_task(client, headers, title):
    client.cookies.clear()
    response = client.post(
        "/api/task-center/tasks",
        headers=headers,
        json={"title": title, "description": "ComputerWorkflow ownership regression"},
    )
    assert response.status_code == 200, response.text
    return response.json()["task"]["id"]


def _workflow_state(db):
    models = (
        ComputerSession,
        ComputerWorkflow,
        ComputerWorkflowStep,
        ComputerWorkflowApproval,
        ComputerWorkflowCheckpoint,
        ComputerWorkflowVerification,
        ComputerWorkflowRecovery,
    )
    state = {}
    for model in models:
        primary_key = tuple(model.__table__.primary_key.columns)
        rows = db.query(model).order_by(*primary_key).all()
        state[model.__tablename__] = json.dumps(
            [{column.name: getattr(row, column.name) for column in model.__table__.columns} for row in rows],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    return state


def _action_plan_counts(db):
    return tuple(db.query(model).count() for model in (ComputerActionPlan, ComputerActionTarget, ComputerActionApproval))


def test_computer_workflow_api_and_execution_flow(client, admin_headers, monkeypatch):
    _enable_workflow_flags(monkeypatch)

    health = client.get("/api/v2/computer-workflow/health")
    assert health.status_code == 200
    assert health.json()["feature_flags"]["MAC_SAFE_WORKFLOW_ENABLED"] is False

    task_id = _create_owned_task(client, admin_headers, "ComputerWorkflow owner flow")
    create_response = client.post(
        "/api/v2/computer/workflows",
        json=_create_workflow_payload(task_id),
        headers=admin_headers,
    )
    assert create_response.status_code == 200, create_response.text
    payload = create_response.json()
    workflow_id = payload["workflow"]["workflow_id"]

    assert payload["workflow"]["status"] == "等待批准"
    assert payload["workflow"]["total_steps"] == 2
    assert len(payload["steps"]) == 2
    assert payload["approval"]["approval_status"] == "等待审批"
    assert payload["preview"]["step_count"] == 2

    list_response = client.get("/api/v2/computer/workflows", headers=admin_headers)
    assert list_response.status_code == 200
    assert list_response.json()["items"]

    detail_response = client.get(f"/api/v2/computer/workflows/{workflow_id}", headers=admin_headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["workflow"]["workflow_id"] == workflow_id
    assert len(detail["steps"]) == 2
    assert len(detail["approvals"]) >= 1

    preview_response = client.post(f"/api/v2/computer/workflows/{workflow_id}/preview", headers=admin_headers)
    assert preview_response.status_code == 200
    assert preview_response.json()["preview"]["goal"] == payload["workflow"]["goal"]

    approve_response = client.post(f"/api/v2/computer/workflows/{workflow_id}/approve", headers=admin_headers)
    assert approve_response.status_code == 200
    assert approve_response.json()["workflow"]["approval_status"] == "已批准"

    start_response = client.post(f"/api/v2/computer/workflows/{workflow_id}/start", headers=admin_headers)
    assert start_response.status_code == 200
    started = start_response.json()["workflow"]
    assert started["status"] in {"已暂停", "等待关键节点确认", "执行中", "已失败"}

    steps_response = client.get(f"/api/v2/computer/workflows/{workflow_id}/steps", headers=admin_headers)
    assert steps_response.status_code == 200
    assert len(steps_response.json()["items"]) == 2

    checkpoints_response = client.get(f"/api/v2/computer/workflows/{workflow_id}/checkpoints", headers=admin_headers)
    assert checkpoints_response.status_code == 200

    audit_response = client.get(f"/api/v2/computer/workflows/{workflow_id}/audit", headers=admin_headers)
    assert audit_response.status_code == 200
    audit_payload = audit_response.json()
    assert audit_payload["workflow_id"] == workflow_id
    assert any(event["event"] == "WORKFLOW_PLAN_CREATED" for event in audit_payload["events"])


def test_real_workflow_missing_target_url_fails_before_plan_or_workflow_write(client, admin_headers, test_db, monkeypatch):
    settings = _enable_workflow_flags(monkeypatch)
    settings.OPENCLAW_ADAPTER_ENABLED = True
    settings.PAGE_CAPTURE_ALLOWED_ORIGINS = ["http://127.0.0.1:59200"]
    settings.PAGE_CAPTURE_CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    settings.PAGE_CAPTURE_OUTPUT_ROOT = "/private/tmp/tiantong-r185-test-captures"
    settings.PAGE_CAPTURE_TIMEOUT_SECONDS = 10
    monkeypatch.setattr("backend.agent_runtime.executors.computer.runtime.get_settings", lambda: settings)

    task_id = _create_owned_task(client, admin_headers, "ComputerWorkflow missing target URL")
    workflow_payload = {
        "task_id": task_id,
        "goal": "Real page capture requires a bound target",
        "risk_level": "低风险",
        "max_steps": 2,
        "steps": [
            {"action_type": "截图", "expected_result": "真实页面PNG"},
            {"action_type": "等待", "expected_result": "安全结束"},
        ],
    }
    with test_db() as db:
        before_workflow = _workflow_state(db)
        before_plans = _action_plan_counts(db)

    response = client.post(
        "/api/v2/computer/workflows",
        json=workflow_payload,
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "截图动作必须提供允许的target_url"
    with test_db() as db:
        assert _workflow_state(db) == before_workflow
        assert _action_plan_counts(db) == before_plans


def test_real_workflow_unavailable_adapter_fails_before_plan_or_workflow_write(client, admin_headers, test_db, monkeypatch):
    settings = _enable_workflow_flags(monkeypatch)
    settings.OPENCLAW_ADAPTER_ENABLED = True
    settings.PAGE_CAPTURE_ALLOWED_ORIGINS = ["http://127.0.0.1:59200"]
    settings.PAGE_CAPTURE_CHROME_PATH = "/private/tmp/r185-missing-chrome"
    settings.PAGE_CAPTURE_OUTPUT_ROOT = "/private/tmp/tiantong-r185-test-captures"
    settings.PAGE_CAPTURE_TIMEOUT_SECONDS = 10
    monkeypatch.setattr("backend.agent_runtime.executors.computer.runtime.get_settings", lambda: settings)
    task_id = _create_owned_task(client, admin_headers, "ComputerWorkflow unavailable adapter")
    with test_db() as db:
        before_workflow = _workflow_state(db)
        before_plans = _action_plan_counts(db)

    response = client.post(
        "/api/v2/computer/workflows",
        headers=admin_headers,
        json={
            "task_id": task_id,
            "goal": "Unavailable adapter must not write",
            "max_steps": 2,
            "steps": [
                {
                    "action_type": "截图",
                    "target_url": "http://127.0.0.1:59200/computer-workflow-center.html",
                },
                {"action_type": "等待"},
            ],
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "真实页面截图适配器不可用"
    with test_db() as db:
        assert _workflow_state(db) == before_workflow
        assert _action_plan_counts(db) == before_plans


def test_computer_workflow_public_routes_enforce_task_ownership(client, admin_headers, test_db, monkeypatch):
    from backend.agent_runtime.executors.computer.openclaw_adapter import validate_capture_target_url
    from backend.config import UAT_PAGE_CAPTURE_ORIGIN, get_settings

    _enable_workflow_flags(monkeypatch)
    allowed_origins = list(get_settings().PAGE_CAPTURE_ALLOWED_ORIGINS or [UAT_PAGE_CAPTURE_ORIGIN])
    assert allowed_origins == [UAT_PAGE_CAPTURE_ORIGIN]
    target_url = validate_capture_target_url(
        f"{allowed_origins[0]}/computer-workflow-center.html",
        allowed_origins,
    )

    def ownership_workflow_payload(task_id):
        return {
            "task_id": task_id,
            "goal": "验证ComputerWorkflow ownership隔离",
            "risk_level": "低风险",
            "max_steps": 2,
            "steps": [
                {
                    "action_type": "截图",
                    "target_url": target_url,
                    "expected_result": "真实页面PNG",
                    "risk_level": "低风险",
                    "approval_required": False,
                    "checkpoint_required": False,
                },
                {
                    "action_type": "等待",
                    "expected_result": "安全结束",
                    "risk_level": "低风险",
                    "approval_required": False,
                    "checkpoint_required": False,
                },
            ],
        }

    owner_task_id = _create_owned_task(client, admin_headers, "ComputerWorkflow private sentinel")
    owner_create = client.post(
        "/api/v2/computer/workflows",
        headers=admin_headers,
        json=ownership_workflow_payload(owner_task_id),
    )
    assert owner_create.status_code == 200, owner_create.text
    workflow_id = owner_create.json()["workflow"]["workflow_id"]

    with test_db() as db:
        owner = db.query(User).filter(User.username == "admin").one()
        owner_store_id = db.query(UserStoreMembership.store_id).filter(
            UserStoreMembership.user_id == owner.id,
            UserStoreMembership.active.is_(True),
            UserStoreMembership.can_read.is_(True),
        ).scalar()
        owner_scope = (owner.id, owner.tenant_id, owner.company_id, owner_store_id)
        step_id = db.query(ComputerWorkflowStep.step_id).filter(
            ComputerWorkflowStep.workflow_id == workflow_id
        ).order_by(ComputerWorkflowStep.sequence_number.asc()).first()[0]
        checkpoint = ComputerWorkflowCheckpoint(
            checkpoint_id=uuid.uuid4().hex,
            workflow_id=workflow_id,
            step_id=step_id,
            checkpoint_type="执行前确认",
            reason="R165 foreign checkpoint sentinel",
            risk_level="中低风险",
            approval_status="等待审批",
        )
        db.add(checkpoint)
        db.commit()
        checkpoint_id = checkpoint.checkpoint_id

    foreign_headers = (
        _create_scoped_owner(client, test_db, "r165-tenant")[0],
        _create_scoped_owner(client, test_db, "r165-company", tenant_id=owner_scope[1])[0],
        _create_scoped_owner(
            client,
            test_db,
            "r165-shop",
            tenant_id=owner_scope[1],
            company_id=owner_scope[2],
        )[0],
        _create_scoped_owner(
            client,
            test_db,
            "r165-requester",
            tenant_id=owner_scope[1],
            company_id=owner_scope[2],
            store_id=owner_scope[3],
        )[0],
    )
    missing_workflow_id = "r165-missing-workflow"
    missing_checkpoint_id = "r165-missing-checkpoint"
    workflow_routes = (
        ("get", f"/api/v2/computer/workflows/{workflow_id}", f"/api/v2/computer/workflows/{missing_workflow_id}"),
        ("post", f"/api/v2/computer/workflows/{workflow_id}/preview", f"/api/v2/computer/workflows/{missing_workflow_id}/preview"),
        ("post", f"/api/v2/computer/workflows/{workflow_id}/approve", f"/api/v2/computer/workflows/{missing_workflow_id}/approve"),
        ("post", f"/api/v2/computer/workflows/{workflow_id}/reject", f"/api/v2/computer/workflows/{missing_workflow_id}/reject"),
        ("post", f"/api/v2/computer/workflows/{workflow_id}/start", f"/api/v2/computer/workflows/{missing_workflow_id}/start"),
        ("post", f"/api/v2/computer/workflows/{workflow_id}/pause", f"/api/v2/computer/workflows/{missing_workflow_id}/pause"),
        ("post", f"/api/v2/computer/workflows/{workflow_id}/resume", f"/api/v2/computer/workflows/{missing_workflow_id}/resume"),
        ("post", f"/api/v2/computer/workflows/{workflow_id}/cancel", f"/api/v2/computer/workflows/{missing_workflow_id}/cancel"),
        ("get", f"/api/v2/computer/workflows/{workflow_id}/steps", f"/api/v2/computer/workflows/{missing_workflow_id}/steps"),
        ("get", f"/api/v2/computer/workflows/{workflow_id}/checkpoints", f"/api/v2/computer/workflows/{missing_workflow_id}/checkpoints"),
        ("get", f"/api/v2/computer/workflows/{workflow_id}/audit", f"/api/v2/computer/workflows/{missing_workflow_id}/audit"),
        ("post", f"/api/v2/computer/checkpoints/{checkpoint_id}/approve", f"/api/v2/computer/checkpoints/{missing_checkpoint_id}/approve"),
        ("post", f"/api/v2/computer/checkpoints/{checkpoint_id}/reject", f"/api/v2/computer/checkpoints/{missing_checkpoint_id}/reject"),
    )

    for headers in foreign_headers:
        client.cookies.clear()
        listed = client.get("/api/v2/computer/workflows", headers=headers)
        assert listed.status_code == 200
        assert workflow_id not in {row["workflow_id"] for row in listed.json()["items"]}

        for method, foreign_path, missing_path in workflow_routes:
            with test_db() as db:
                before = _workflow_state(db)
            client.cookies.clear()
            foreign = getattr(client, method)(foreign_path, headers=headers)
            client.cookies.clear()
            missing = getattr(client, method)(missing_path, headers=headers)
            assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json())
            with test_db() as db:
                assert _workflow_state(db) == before

        foreign_task_id = _create_owned_task(client, headers, "R165 foreign create sentinel")
        with test_db() as db:
            before = _workflow_state(db)
        client.cookies.clear()
        foreign_create = client.post(
            "/api/v2/computer/workflows",
            headers=admin_headers,
            json=ownership_workflow_payload(foreign_task_id),
        )
        client.cookies.clear()
        missing_create = client.post(
            "/api/v2/computer/workflows",
            headers=admin_headers,
            json=ownership_workflow_payload(2_147_483_647),
        )
        assert (foreign_create.status_code, foreign_create.json()) == (
            missing_create.status_code,
            missing_create.json(),
        )
        with test_db() as db:
            assert _workflow_state(db) == before


def test_computer_workflow_api_rejects_forbidden_actions():
    assert "单击" in WORKFLOW_ACTION_TYPES
    assert "输入普通文本" in WORKFLOW_ACTION_TYPES


@pytest.mark.parametrize(
    "failure_symbol",
    (
        "runtime-evidence",
        "runtime-policy-event",
        "service-verification",
        "service-policy-event",
        "service-refresh",
        "workflow-verification",
    ),
)
def test_workflow_post_action_failure_rolls_back_workflow_step_and_action_graph(
    client,
    admin_headers,
    test_db,
    monkeypatch,
    tmp_path,
    failure_symbol,
):
    settings_type = _enable_workflow_flags(monkeypatch)
    monkeypatch.setattr(
        "backend.agent_runtime.executors.computer.runtime.get_settings",
        lambda: settings_type(),
    )
    task_id = _create_owned_task(client, admin_headers, "R193 atomic workflow rollback")
    created = client.post(
        "/api/v2/computer/workflows",
        json=_create_workflow_payload(task_id),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow"]["workflow_id"]
    approved = client.post(f"/api/v2/computer/workflows/{workflow_id}/approve", headers=admin_headers)
    assert approved.status_code == 200, approved.text

    def fail_after_action(*_args, **_kwargs):
        raise RuntimeError("R193 forced post-action workflow verification failure")

    original_commit = OrmSession.commit
    original_refresh = OrmSession.refresh
    commit_count = 0
    refresh_failure_ready = False

    def tracked_commit(db):
        nonlocal commit_count
        commit_count += 1
        return original_commit(db)

    from backend.agent_runtime.executors.computer import runtime as runtime_module
    from backend.agent_runtime.executors.computer.actions import service as action_service

    capture_path = tmp_path / "r193-orphan-capture.png"
    settings_type.PAGE_CAPTURE_OUTPUT_ROOT = str(tmp_path)
    original_runtime_execute = runtime_module.ComputerRuntime.execute_action

    def execute_with_capture(*args, **kwargs):
        result = original_runtime_execute(*args, **kwargs)
        capture_path.write_bytes(b"\x89PNG\r\n\x1a\nR193")
        result["action"]["screenshot_after"] = capture_path.as_uri()
        return result

    original_service_policy_event = action_service.add_policy_event

    def fail_service_policy_event(*args, **kwargs):
        if str(kwargs.get("event_code") or "").startswith("ACTION_EXECUTION_"):
            fail_after_action()
        return original_service_policy_event(*args, **kwargs)

    def record_service_policy_event(*args, **kwargs):
        nonlocal refresh_failure_ready
        result = original_service_policy_event(*args, **kwargs)
        if str(kwargs.get("event_code") or "").startswith("ACTION_EXECUTION_"):
            refresh_failure_ready = True
        return result

    def fail_service_refresh(db, instance, *args, **kwargs):
        if refresh_failure_ready and isinstance(instance, ComputerActionPlan):
            fail_after_action()
        return original_refresh(db, instance, *args, **kwargs)

    with monkeypatch.context() as failure_patch:
        failure_patch.setattr(runtime_module.ComputerRuntime, "execute_action", staticmethod(execute_with_capture))
        failure_patch.setattr("backend.config.get_settings", lambda: settings_type())
        if failure_symbol == "runtime-evidence":
            failure_patch.setattr(runtime_module, "add_evidence_row", fail_after_action)
        elif failure_symbol == "runtime-policy-event":
            failure_patch.setattr(runtime_module, "add_policy_event", fail_after_action)
        elif failure_symbol == "service-verification":
            failure_patch.setattr(action_service, "verify_action_result", fail_after_action)
        elif failure_symbol == "service-policy-event":
            failure_patch.setattr(action_service, "add_policy_event", fail_service_policy_event)
        elif failure_symbol == "service-refresh":
            failure_patch.setattr(action_service, "add_policy_event", record_service_policy_event)
            failure_patch.setattr(OrmSession, "refresh", fail_service_refresh)
        else:
            failure_patch.setattr(
                "backend.agent_runtime.workflows.computer.runner.verify_step_result",
                fail_after_action,
            )
        failure_patch.setattr(OrmSession, "commit", tracked_commit)
        with pytest.raises(RuntimeError, match="R193 forced post-action"):
            client.post(f"/api/v2/computer/workflows/{workflow_id}/start", headers=admin_headers)
    assert commit_count == 0
    assert not capture_path.exists()

    with test_db() as db:
        workflow = db.get(ComputerWorkflow, workflow_id)
        step = (
            db.query(ComputerWorkflowStep)
            .filter(ComputerWorkflowStep.workflow_id == workflow_id)
            .order_by(ComputerWorkflowStep.sequence_number.asc())
            .first()
        )
        assert workflow.status == "已批准"
        assert workflow.current_step == 0
        assert workflow.started_at is None
        assert step.status == "待执行"
        assert step.started_at is None
        assert step.action_id is None
        assert db.query(ComputerActionPlan).filter(ComputerActionPlan.session_id == workflow.session_id).count() == 0
        assert db.query(ComputerAction).filter(ComputerAction.session_id == workflow.session_id).count() == 0
        assert db.query(ComputerPolicyEvent).filter(ComputerPolicyEvent.session_id == workflow.session_id).count() == 0
        assert db.query(ComputerEvidence).filter(ComputerEvidence.session_id == workflow.session_id).count() == 0

    retried = client.post(f"/api/v2/computer/workflows/{workflow_id}/start", headers=admin_headers)
    assert retried.status_code == 200, retried.text
    with test_db() as db:
        workflow = db.get(ComputerWorkflow, workflow_id)
        action_ids = [row.action_id for row in db.query(ComputerAction).filter(ComputerAction.session_id == workflow.session_id)]
        event_ids = [row.event_id for row in db.query(ComputerPolicyEvent).filter(ComputerPolicyEvent.session_id == workflow.session_id)]
        evidence_ids = [row.evidence_id for row in db.query(ComputerEvidence).filter(ComputerEvidence.session_id == workflow.session_id)]
        assert len(action_ids) == len(set(action_ids)) == 1
        assert len(event_ids) == len(set(event_ids))
        assert len(evidence_ids) == len(set(evidence_ids)) == 1


def test_resume_rejects_non_resumable_and_inconsistent_states_without_writes(
    client,
    admin_headers,
    test_db,
    monkeypatch,
):
    _enable_workflow_flags(monkeypatch)
    task_id = _create_owned_task(client, admin_headers, "R193 resume state allowlist")
    created = client.post(
        "/api/v2/computer/workflows",
        json=_create_workflow_payload(task_id),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow"]["workflow_id"]
    approved = client.post(f"/api/v2/computer/workflows/{workflow_id}/approve", headers=admin_headers)
    assert approved.status_code == 200, approved.text

    for status in ("已批准", "执行中", "等待关键节点确认", "已失败", "已完成", "已取消"):
        with test_db() as db:
            workflow = db.get(ComputerWorkflow, workflow_id)
            workflow.status = status
            db.commit()
            before = _workflow_state(db)
        response = client.post(f"/api/v2/computer/workflows/{workflow_id}/resume", headers=admin_headers)
        assert response.status_code == 409
        assert response.json()["detail"] == "工作流状态不允许恢复"
        with test_db() as db:
            assert _workflow_state(db) == before


def test_independent_action_service_keeps_default_commit_behavior(
    client,
    admin_headers,
    test_db,
    monkeypatch,
):
    settings_type = _enable_workflow_flags(monkeypatch)
    monkeypatch.setattr(
        "backend.agent_runtime.executors.computer.runtime.get_settings",
        lambda: settings_type(),
    )
    task_id = _create_owned_task(client, admin_headers, "R193 independent action")
    created_session = client.post(
        "/api/v2/computer/sessions",
        headers=admin_headers,
        json={
            "task_id": task_id,
            "executor_type": "mock",
            "environment_type": "test",
            "risk_level": "中低",
            "approval_status": "等待审批",
            "allowed_applications": ["天统测试页面"],
            "allowed_windows": [".*测试.*"],
            "trace_id": "r193-independent-session",
        },
    )
    assert created_session.status_code == 200, created_session.text
    session_id = created_session.json()["session"]["session_id"]
    created_plan = client.post(
        "/api/v2/computer/action-plans",
        headers=admin_headers,
        json={
            "session_id": session_id,
            "target_application": "天统测试页面",
            "target_window": "测试工作流页面",
            "goal": "R193 independent action commit compatibility",
            "action_type": "移动鼠标",
            "target_description": "测试按钮",
            "coordinates": {"x": 12, "y": 18},
            "trace_id": "r193-independent-plan",
        },
    )
    assert created_plan.status_code == 200, created_plan.text
    plan_id = created_plan.json()["plan"]["plan_id"]
    action_id = created_plan.json()["target"]["action_id"]
    approved = client.post(
        f"/api/v2/computer/actions/{action_id}/approve?trace_id=r193-independent-approve",
        headers=admin_headers,
    )
    assert approved.status_code == 200, approved.text
    executed = client.post(
        f"/api/v2/computer/actions/{action_id}/execute"
        "?current_application=天统测试页面&current_window=测试工作流页面"
        "&trace_id=r193-independent-execute",
        headers=admin_headers,
    )
    assert executed.status_code == 200, executed.text

    with test_db() as db:
        assert db.get(ComputerActionPlan, plan_id).status == "已暂停"
        assert db.get(ComputerAction, action_id) is not None
        evidence = (
            db.query(ComputerEvidence)
            .filter(ComputerEvidence.session_id == session_id)
            .one_or_none()
        )
        assert evidence is not None
        assert evidence.action_id == action_id
        assert db.query(ComputerPolicyEvent).filter(ComputerPolicyEvent.action_id == action_id).count() >= 1


def test_independent_action_service_post_runtime_failure_preserves_committed_capture(
    client,
    admin_headers,
    test_db,
    monkeypatch,
    tmp_path,
):
    settings_type = _enable_workflow_flags(monkeypatch)
    monkeypatch.setattr(
        "backend.agent_runtime.executors.computer.runtime.get_settings",
        lambda: settings_type(),
    )
    task_id = _create_owned_task(client, admin_headers, "R193 independent failure")
    created_session = client.post(
        "/api/v2/computer/sessions",
        headers=admin_headers,
        json={
            "task_id": task_id,
            "executor_type": "mock",
            "environment_type": "test",
            "risk_level": "中低",
            "approval_status": "等待审批",
            "allowed_applications": ["天统测试页面"],
            "allowed_windows": [".*测试.*"],
            "trace_id": "r193-independent-failure-session",
        },
    )
    assert created_session.status_code == 200, created_session.text
    session_id = created_session.json()["session"]["session_id"]
    created_plan = client.post(
        "/api/v2/computer/action-plans",
        headers=admin_headers,
        json={
            "session_id": session_id,
            "target_application": "天统测试页面",
            "target_window": "测试工作流页面",
            "goal": "R193 independent post-runtime failure compatibility",
            "action_type": "移动鼠标",
            "target_description": "测试按钮",
            "coordinates": {"x": 12, "y": 18},
            "trace_id": "r193-independent-failure-plan",
        },
    )
    assert created_plan.status_code == 200, created_plan.text
    action_id = created_plan.json()["target"]["action_id"]
    approved = client.post(
        f"/api/v2/computer/actions/{action_id}/approve?trace_id=r193-independent-failure-approve",
        headers=admin_headers,
    )
    assert approved.status_code == 200, approved.text

    from backend.agent_runtime.executors.computer import runtime as runtime_module
    from backend.agent_runtime.executors.computer.actions import service as action_service

    capture_path = tmp_path / "r193-committed-capture.png"
    original_runtime_execute = runtime_module.ComputerRuntime.execute_action

    def execute_with_committed_capture(db, *args, **kwargs):
        result = original_runtime_execute(db, *args, **kwargs)
        capture_path.write_bytes(b"\x89PNG\r\n\x1a\nR193")
        action = db.get(ComputerAction, result["action"]["action_id"])
        action.screenshot_after = capture_path.as_uri()
        db.commit()
        result["action"]["screenshot_after"] = capture_path.as_uri()
        return result

    def fail_verification(*_args, **_kwargs):
        raise RuntimeError("R193 forced independent post-runtime failure")

    monkeypatch.setattr(runtime_module.ComputerRuntime, "execute_action", staticmethod(execute_with_committed_capture))
    monkeypatch.setattr(action_service, "verify_action_result", fail_verification)
    with pytest.raises(RuntimeError, match="R193 forced independent post-runtime"):
        client.post(
            f"/api/v2/computer/actions/{action_id}/execute"
            "?current_application=天统测试页面&current_window=测试工作流页面"
            "&trace_id=r193-independent-failure-execute",
            headers=admin_headers,
        )
    assert capture_path.is_file()
    with test_db() as db:
        action = db.get(ComputerAction, action_id)
        assert action.screenshot_after == capture_path.as_uri()
        evidence = db.query(ComputerEvidence).filter(ComputerEvidence.action_id == action_id).one()
        assert evidence is not None


@pytest.mark.parametrize("failure_stage", ["refresh", "commit_ack"])
def test_independent_action_post_commit_refresh_preserves_capture_and_blocks_reexecution(
    client,
    admin_headers,
    test_db,
    monkeypatch,
    tmp_path,
    failure_stage,
):
    settings_type = _enable_workflow_flags(monkeypatch)
    settings_type.PAGE_CAPTURE_OUTPUT_ROOT = str(tmp_path)
    monkeypatch.setattr(
        "backend.agent_runtime.executors.computer.runtime.get_settings",
        lambda: settings_type(),
    )
    task_id = _create_owned_task(client, admin_headers, "R194 independent post-commit")
    created_session = client.post(
        "/api/v2/computer/sessions",
        headers=admin_headers,
        json={
            "task_id": task_id,
            "executor_type": "mock",
            "environment_type": "test",
            "risk_level": "中低",
            "approval_status": "等待审批",
            "allowed_applications": ["天统测试页面"],
            "allowed_windows": [".*测试.*"],
            "trace_id": "r194-runtime-refresh-session",
        },
    )
    assert created_session.status_code == 200, created_session.text
    session_id = created_session.json()["session"]["session_id"]
    created_plan = client.post(
        "/api/v2/computer/action-plans",
        headers=admin_headers,
        json={
            "session_id": session_id,
            "target_application": "天统测试页面",
            "target_window": "测试工作流页面",
            "goal": "R194 runtime post-commit refresh boundary",
            "action_type": "移动鼠标",
            "target_description": "测试按钮",
            "coordinates": {"x": 12, "y": 18},
            "trace_id": "r194-runtime-refresh-plan",
        },
    )
    assert created_plan.status_code == 200, created_plan.text
    action_id = created_plan.json()["target"]["action_id"]
    approved = client.post(
        f"/api/v2/computer/actions/{action_id}/approve?trace_id=r194-runtime-refresh-approve",
        headers=admin_headers,
    )
    assert approved.status_code == 200, approved.text

    from backend.agent_runtime.executors.computer import runtime as runtime_module
    from backend.agent_runtime.executors.computer.base import ComputerExecutorOutcome

    capture_path = tmp_path / "r194-runtime-committed.png"
    execute_count = 0

    class CaptureExecutor:
        def execute_action(self, _context):
            nonlocal execute_count
            execute_count += 1
            capture_path.write_bytes(b"\x89PNG\r\n\x1a\nR194-runtime")
            capture_path.chmod(0o600)
            return ComputerExecutorOutcome(
                success=True,
                action_result={"processed": True},
                screenshot_reference=capture_path.as_uri(),
                duration_ms=1,
            )

    original_commit = OrmSession.commit
    original_refresh = OrmSession.refresh
    commit_succeeded = False
    commit_ack_failure_count = 0
    refresh_failure_count = 0

    def commit_then_mark(db):
        nonlocal commit_succeeded, commit_ack_failure_count
        result = original_commit(db)
        commit_succeeded = True
        if failure_stage == "commit_ack" and commit_ack_failure_count == 0:
            commit_ack_failure_count += 1
            raise RuntimeError("R194 forced runtime commit acknowledgement loss")
        return result

    def fail_first_post_commit_session_refresh(db, instance, *args, **kwargs):
        nonlocal refresh_failure_count
        if failure_stage == "refresh" and commit_succeeded and refresh_failure_count == 0 and isinstance(instance, ComputerSession):
            refresh_failure_count += 1
            raise RuntimeError("R194 forced runtime post-commit refresh failure")
        return original_refresh(db, instance, *args, **kwargs)

    monkeypatch.setattr(runtime_module, "_executor_for_settings", lambda _session: CaptureExecutor())
    monkeypatch.setattr(OrmSession, "commit", commit_then_mark)
    monkeypatch.setattr(OrmSession, "refresh", fail_first_post_commit_session_refresh)
    executed = client.post(
        f"/api/v2/computer/actions/{action_id}/execute"
        "?current_application=天统测试页面&current_window=测试工作流页面"
        "&trace_id=r194-runtime-refresh-execute",
        headers=admin_headers,
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["result"]["commit_status"] == "committed_requery_recovered"
    assert refresh_failure_count == (1 if failure_stage == "refresh" else 0)
    assert commit_ack_failure_count == (1 if failure_stage == "commit_ack" else 0)
    assert execute_count == 1
    assert capture_path.is_file()
    capture_sha = __import__("hashlib").sha256(capture_path.read_bytes()).hexdigest()

    retried = client.post(
        f"/api/v2/computer/actions/{action_id}/execute"
        "?current_application=天统测试页面&current_window=测试工作流页面"
        "&trace_id=r194-runtime-refresh-retry",
        headers=admin_headers,
    )
    assert retried.status_code == 409
    assert retried.json()["detail"] == "动作已提交，禁止重复执行"
    assert execute_count == 1
    assert __import__("hashlib").sha256(capture_path.read_bytes()).hexdigest() == capture_sha
    with test_db() as db:
        action = db.get(ComputerAction, action_id)
        assert action.screenshot_after == capture_path.as_uri()
        assert db.query(ComputerAction).filter(ComputerAction.action_id == action_id).count() == 1
        assert db.query(ComputerEvidence).filter(ComputerEvidence.action_id == action_id).count() == 1


@pytest.mark.parametrize("failure_stage", ["refresh", "commit_ack"])
def test_workflow_post_commit_refresh_preserves_committed_graph_and_capture(
    client,
    admin_headers,
    test_db,
    monkeypatch,
    tmp_path,
    failure_stage,
):
    settings_type = _enable_workflow_flags(monkeypatch)
    monkeypatch.setattr(
        "backend.agent_runtime.executors.computer.runtime.get_settings",
        lambda: settings_type(),
    )
    task_id = _create_owned_task(client, admin_headers, "R194 workflow post-commit refresh")
    created = client.post(
        "/api/v2/computer/workflows",
        json=_create_workflow_payload(task_id),
        headers=admin_headers,
    )
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow"]["workflow_id"]
    approved = client.post(f"/api/v2/computer/workflows/{workflow_id}/approve", headers=admin_headers)
    assert approved.status_code == 200, approved.text

    from backend.agent_runtime.executors.computer import runtime as runtime_module

    capture_path = tmp_path / "r194-workflow-committed.png"
    settings_type.PAGE_CAPTURE_OUTPUT_ROOT = str(tmp_path)
    original_runtime_execute = runtime_module.ComputerRuntime.execute_action
    execute_count = 0

    def execute_with_capture(db, *args, **kwargs):
        nonlocal execute_count
        execute_count += 1
        result = original_runtime_execute(db, *args, **kwargs)
        capture_path.write_bytes(b"\x89PNG\r\n\x1a\nR194-workflow")
        capture_path.chmod(0o600)
        action = db.get(ComputerAction, result["action"]["action_id"])
        action.screenshot_after = capture_path.as_uri()
        result["action"]["screenshot_after"] = capture_path.as_uri()
        return result

    original_commit = OrmSession.commit
    original_refresh = OrmSession.refresh
    commit_succeeded = False
    commit_ack_failure_count = 0
    refresh_failure_count = 0

    def commit_then_mark(db):
        nonlocal commit_succeeded, commit_ack_failure_count
        result = original_commit(db)
        commit_succeeded = True
        if failure_stage == "commit_ack" and commit_ack_failure_count == 0:
            commit_ack_failure_count += 1
            raise RuntimeError("R194 forced workflow commit acknowledgement loss")
        return result

    def fail_first_post_commit_workflow_refresh(db, instance, *args, **kwargs):
        nonlocal refresh_failure_count
        if failure_stage == "refresh" and commit_succeeded and refresh_failure_count == 0 and isinstance(instance, ComputerWorkflow):
            refresh_failure_count += 1
            raise RuntimeError("R194 forced workflow post-commit refresh failure")
        return original_refresh(db, instance, *args, **kwargs)

    monkeypatch.setattr(runtime_module.ComputerRuntime, "execute_action", staticmethod(execute_with_capture))
    monkeypatch.setattr(OrmSession, "commit", commit_then_mark)
    monkeypatch.setattr(OrmSession, "refresh", fail_first_post_commit_workflow_refresh)
    started = client.post(f"/api/v2/computer/workflows/{workflow_id}/start", headers=admin_headers)
    assert started.status_code == 200, started.text
    assert started.json()["commit_status"] == "committed_requery_recovered"
    assert refresh_failure_count == (1 if failure_stage == "refresh" else 0)
    assert commit_ack_failure_count == (1 if failure_stage == "commit_ack" else 0)
    assert execute_count == 1
    assert capture_path.is_file()
    capture_sha = __import__("hashlib").sha256(capture_path.read_bytes()).hexdigest()

    retried = client.post(f"/api/v2/computer/workflows/{workflow_id}/start", headers=admin_headers)
    assert retried.status_code == 409
    assert execute_count == 1
    assert __import__("hashlib").sha256(capture_path.read_bytes()).hexdigest() == capture_sha
    with test_db() as db:
        workflow = db.get(ComputerWorkflow, workflow_id)
        assert workflow.status == "已暂停"
        assert workflow.current_step == 1
        step = (
            db.query(ComputerWorkflowStep)
            .filter(ComputerWorkflowStep.workflow_id == workflow_id)
            .order_by(ComputerWorkflowStep.sequence_number.asc())
            .first()
        )
        assert step.status == "已完成"
        assert step.action_id is not None
        assert db.query(ComputerAction).filter(ComputerAction.action_id == step.action_id).count() == 1
        assert db.query(ComputerEvidence).filter(ComputerEvidence.action_id == step.action_id).count() == 1


def test_two_step_workflow_uses_stable_distinct_plan_traces_and_resumes_once(
    postgres_alpha_runtime,
    monkeypatch,
):
    client, admin_headers, test_db = postgres_alpha_runtime
    settings_type = _enable_workflow_flags(monkeypatch)
    monkeypatch.setattr(
        "backend.agent_runtime.executors.computer.runtime.get_settings",
        lambda: settings_type(),
    )

    class CaptureAuthorization:
        def clear(self):
            return None

    executed_action_types = []
    from backend.agent_runtime.executors.computer.mock_executor import MockComputerExecutor

    original_execute = MockComputerExecutor.execute_action

    def track_execute(executor, context):
        executed_action_types.append(context.action_type)
        return original_execute(executor, context)

    monkeypatch.setattr(
        "backend.agent_runtime.workflows.computer.runner.create_capture_authorization",
        lambda **_kwargs: CaptureAuthorization(),
    )
    monkeypatch.setattr(MockComputerExecutor, "execute_action", track_execute)

    task_id = _create_owned_task(client, admin_headers, "R195 two-step trace identity")
    created = client.post(
        "/api/v2/computer/workflows",
        headers=admin_headers,
        json={
            "task_id": task_id,
            "goal": "R195真实两步PostgreSQL回归",
            "risk_level": "低风险",
            "max_steps": 2,
            "trace_id": "r195-two-step-workflow",
            "steps": [
                {
                    "action_type": "截图",
                    "target_url": "http://127.0.0.1:59200/computer-workflow-center.html",
                    "expected_result": "本地页面截图",
                },
                {"action_type": "等待", "expected_result": "安全等待完成"},
            ],
        },
    )
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow"]["workflow_id"]
    approved = client.post(f"/api/v2/computer/workflows/{workflow_id}/approve", headers=admin_headers)
    assert approved.status_code == 200, approved.text

    started = client.post(f"/api/v2/computer/workflows/{workflow_id}/start", headers=admin_headers)
    assert started.status_code == 200, started.text
    assert started.json()["workflow"]["status"] == "已暂停"
    assert started.json()["workflow"]["current_step"] == 1

    with test_db() as db:
        workflow = db.get(ComputerWorkflow, workflow_id)
        first_step = db.query(ComputerWorkflowStep).filter(
            ComputerWorkflowStep.workflow_id == workflow_id,
            ComputerWorkflowStep.sequence_number == 1,
        ).one()
        first_plan = db.query(ComputerActionPlan).filter(
            ComputerActionPlan.session_id == workflow.session_id,
        ).one()
        assert first_step.action_id is not None
        first_action = db.get(ComputerAction, first_step.action_id)
        first_evidence = db.query(ComputerEvidence).filter(
            ComputerEvidence.session_id == workflow.session_id,
        ).one()
        first_verification = db.query(ComputerWorkflowVerification).filter(
            ComputerWorkflowVerification.workflow_id == workflow_id,
            ComputerWorkflowVerification.step_id == first_step.step_id,
        ).one()
        assert first_action is not None
        assert first_evidence.action_id == first_step.action_id
        first_trace = first_plan.trace_id
        assert first_verification.trace_id == first_trace
        first_screenshot = first_action.screenshot_after
        first_evidence_id = first_evidence.evidence_id
        assert first_step.status == "已完成"
        assert first_screenshot

    resumed = client.post(f"/api/v2/computer/workflows/{workflow_id}/resume", headers=admin_headers)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["workflow"]["status"] == "已完成"
    assert resumed.json()["workflow"]["current_step"] == 2

    with test_db() as db:
        workflow = db.get(ComputerWorkflow, workflow_id)
        plans = db.query(ComputerActionPlan).filter(
            ComputerActionPlan.session_id == workflow.session_id,
        ).order_by(ComputerActionPlan.created_at.asc()).all()
        actions = db.query(ComputerAction).filter(ComputerAction.session_id == workflow.session_id).all()
        events = db.query(ComputerPolicyEvent).filter(ComputerPolicyEvent.session_id == workflow.session_id).all()
        evidence = db.query(ComputerEvidence).filter(ComputerEvidence.session_id == workflow.session_id).all()
        verifications = db.query(ComputerWorkflowVerification).filter(
            ComputerWorkflowVerification.workflow_id == workflow_id,
        ).order_by(ComputerWorkflowVerification.created_at.asc()).all()
        assert len(plans) == 2
        assert len({plan.trace_id for plan in plans}) == 2
        assert len(verifications) == 2
        assert {row.trace_id for row in verifications} == {plan.trace_id for plan in plans}
        assert plans[0].trace_id == first_trace
        assert db.get(ComputerAction, first_step.action_id).screenshot_after == first_screenshot
        assert db.get(ComputerEvidence, first_evidence_id).evidence_id == first_evidence_id
        before_retry_counts = (len(plans), len(actions), len(events), len(evidence))

    repeated = client.post(f"/api/v2/computer/workflows/{workflow_id}/resume", headers=admin_headers)
    assert repeated.status_code == 409
    with test_db() as db:
        workflow = db.get(ComputerWorkflow, workflow_id)
        after_retry_counts = (
            db.query(ComputerActionPlan).filter(ComputerActionPlan.session_id == workflow.session_id).count(),
            db.query(ComputerAction).filter(ComputerAction.session_id == workflow.session_id).count(),
            db.query(ComputerPolicyEvent).filter(ComputerPolicyEvent.session_id == workflow.session_id).count(),
            db.query(ComputerEvidence).filter(ComputerEvidence.session_id == workflow.session_id).count(),
        )
        assert after_retry_counts == before_retry_counts
    assert executed_action_types == ["截图", "等待"]


def test_step_verification_is_idempotent_for_the_same_attempt(
    postgres_alpha_runtime,
    monkeypatch,
):
    client, admin_headers, test_db = postgres_alpha_runtime
    _enable_workflow_flags(monkeypatch)
    task_id = _create_owned_task(client, admin_headers, "R196 verification idempotency")
    created = client.post(
        "/api/v2/computer/workflows",
        headers=admin_headers,
        json=_create_workflow_payload(task_id),
    )
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow"]["workflow_id"]

    def add_attempt_graph(db, workflow, step, trace_id, sequence_number):
        action_id = uuid.uuid4().hex
        plan_id = uuid.uuid4().hex
        db.add_all(
            [
                ComputerAction(
                    action_id=action_id,
                    session_id=workflow.session_id,
                    sequence_number=sequence_number,
                    action_type=step.action_type,
                    risk_level=step.risk_level,
                    approval_required=True,
                    approval_status="已批准",
                    trace_id=trace_id,
                ),
                ComputerActionPlan(
                    plan_id=plan_id,
                    session_id=workflow.session_id,
                    task_id=workflow.task_id,
                    goal=workflow.goal,
                    proposed_actions_json=json.dumps([{"action_id": action_id, "action_type": step.action_type}]),
                    current_action_index=0,
                    max_actions=1,
                    risk_level=step.risk_level,
                    approval_mode="逐步审批",
                    status="已批准",
                    trace_id=trace_id,
                ),
                ComputerActionTarget(
                    target_id=uuid.uuid4().hex,
                    plan_id=plan_id,
                    action_id=action_id,
                    action_type=step.action_type,
                    status="已执行",
                ),
            ]
        )
        step.action_id = action_id
        db.flush()
        return {"plan_id": plan_id, "action_id": action_id}

    values = {
        "before_screenshot_reference": "evidence://r196/before",
        "after_screenshot_reference": "evidence://r196/after",
        "state_summary": "R196 stable state",
        "result_summary": "R196 verified",
        "verification_status": "结果符合预期",
        "trace_id": "r196-stable-attempt",
    }
    with test_db() as db:
        owner = db.query(User).filter(User.username == "boss").one()
        bind_session_task_ownership(db, user=owner)
        workflow = db.get(ComputerWorkflow, workflow_id)
        step = db.query(ComputerWorkflowStep).filter(
            ComputerWorkflowStep.workflow_id == workflow_id,
            ComputerWorkflowStep.sequence_number == 1,
        ).one()
        workflow.session_id = uuid.uuid4().hex
        db.add(
            ComputerSession(
                session_id=workflow.session_id,
                task_id=workflow.task_id,
                executor_type="mock",
                environment_type="test",
                status="已创建",
                risk_level="低风险",
                approval_status="已批准",
                trace_id="r196-workflow-session",
            )
        )
        db.flush()
        values.update(add_attempt_graph(db, workflow, step, values["trace_id"], 1))
        first = verify_step_result(db, workflow, step, **values)
        first_id = first.verification_id
        db.commit()

    with test_db() as db:
        owner = db.query(User).filter(User.username == "boss").one()
        bind_session_task_ownership(db, user=owner)
        workflow = db.get(ComputerWorkflow, workflow_id)
        step = db.query(ComputerWorkflowStep).filter(
            ComputerWorkflowStep.workflow_id == workflow_id,
            ComputerWorkflowStep.sequence_number == 1,
        ).one()
        repeated = verify_step_result(db, workflow, step, **values)
        db.commit()
        assert repeated.verification_id == first_id
        assert db.query(ComputerWorkflowVerification).filter(
            ComputerWorkflowVerification.workflow_id == workflow_id,
            ComputerWorkflowVerification.step_id == step.step_id,
        ).count() == 1

    with test_db() as db:
        owner = db.query(User).filter(User.username == "boss").one()
        bind_session_task_ownership(db, user=owner)
        workflow = db.get(ComputerWorkflow, workflow_id)
        step = db.query(ComputerWorkflowStep).filter(
            ComputerWorkflowStep.workflow_id == workflow_id,
            ComputerWorkflowStep.sequence_number == 1,
        ).one()
        step.action_id = uuid.uuid4().hex
        with pytest.raises(HTTPException) as action_conflict:
            verify_step_result(db, workflow, step, **values)
        assert (action_conflict.value.status_code, action_conflict.value.detail) == (409, "工作流步骤验证身份冲突")
        db.rollback()

    conflicting_values = dict(values, trace_id="r196-foreign-attempt", result_summary="must not overwrite")
    with test_db() as db:
        owner = db.query(User).filter(User.username == "boss").one()
        bind_session_task_ownership(db, user=owner)
        workflow = db.get(ComputerWorkflow, workflow_id)
        step = db.query(ComputerWorkflowStep).filter(
            ComputerWorkflowStep.workflow_id == workflow_id,
            ComputerWorkflowStep.sequence_number == 1,
        ).one()
        with pytest.raises(HTTPException) as conflict:
            verify_step_result(db, workflow, step, **conflicting_values)
        assert (conflict.value.status_code, conflict.value.detail) == (409, "工作流步骤验证身份冲突")
        db.rollback()
    with test_db() as db:
        preserved = db.get(ComputerWorkflowVerification, first_id)
        assert preserved is not None
        assert preserved.result_summary == values["result_summary"]
        assert preserved.trace_id == values["trace_id"]
        assert db.query(ComputerWorkflowVerification).filter(
            ComputerWorkflowVerification.workflow_id == workflow_id,
        ).count() == 1

    _foreign_headers, foreign_scope = _create_scoped_owner(client, test_db, "r196-verification-foreign")
    with test_db() as db:
        bind_session_task_ownership(db, user=db.get(User, foreign_scope[0]))
        workflow = db.get(ComputerWorkflow, workflow_id)
        step = db.query(ComputerWorkflowStep).filter(
            ComputerWorkflowStep.workflow_id == workflow_id,
            ComputerWorkflowStep.sequence_number == 1,
        ).one()
        before_count = db.query(ComputerWorkflowVerification).filter(
            ComputerWorkflowVerification.workflow_id == workflow_id,
        ).count()
        with pytest.raises(HTTPException) as foreign_conflict:
            verify_step_result(db, workflow, step, **values)
        assert (foreign_conflict.value.status_code, foreign_conflict.value.detail) == (404, "工作流步骤验证不存在")
        assert db.query(ComputerWorkflowVerification).filter(
            ComputerWorkflowVerification.workflow_id == workflow_id,
        ).count() == before_count
        db.rollback()

    reset_values = dict(values, trace_id="r196-audited-reset-attempt", result_summary="verified after audited reset")
    with test_db() as db:
        owner = db.query(User).filter(User.username == "boss").one()
        bind_session_task_ownership(db, user=owner)
        workflow = db.get(ComputerWorkflow, workflow_id)
        step = db.query(ComputerWorkflowStep).filter(
            ComputerWorkflowStep.workflow_id == workflow_id,
            ComputerWorkflowStep.sequence_number == 1,
        ).one()
        stale = db.get(ComputerWorkflowVerification, first_id)
        record_recovery(
            db,
            workflow,
            step_id=step.step_id,
            recovery_type="Verification受审计重置",
            reason="R196 regression invalidates the exact prior attempt",
            result_summary=json.dumps({"invalidated_verification_id": first_id}, sort_keys=True),
            trace_id="r196-audited-reset",
        )
        db.delete(stale)
        db.flush()
        step.verification_id = None
        step.status = "待执行"
        step.finished_at = None
        reset_values.update(add_attempt_graph(db, workflow, step, reset_values["trace_id"], 2))
        replacement = verify_step_result(db, workflow, step, **reset_values)
        replacement_id = replacement.verification_id
        db.commit()
    assert replacement_id != first_id
    with test_db() as db:
        rows = db.query(ComputerWorkflowVerification).filter(
            ComputerWorkflowVerification.workflow_id == workflow_id,
        ).all()
        assert len(rows) == 1
        assert rows[0].verification_id == replacement_id
        assert rows[0].trace_id == reset_values["trace_id"]
        assert db.query(ComputerWorkflowRecovery).filter(
            ComputerWorkflowRecovery.workflow_id == workflow_id,
            ComputerWorkflowRecovery.recovery_type == "Verification受审计重置",
        ).count() == 1
