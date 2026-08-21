from __future__ import annotations

import json
import uuid

from backend.agent_runtime.workflows.computer.constants import WORKFLOW_ACTION_TYPES
from backend.agent_runtime.executors.computer.models import ComputerSession
from backend.agent_runtime.workflows.computer.models import (
    ComputerWorkflow,
    ComputerWorkflowApproval,
    ComputerWorkflowCheckpoint,
    ComputerWorkflowRecovery,
    ComputerWorkflowStep,
    ComputerWorkflowVerification,
)
from backend.models import User, UserStoreMembership
from tests.test_v2_alpha_postgresql_migration_regression import _create_scoped_owner


def _enable_workflow_flags(monkeypatch):
    class _Settings:
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


def test_computer_workflow_public_routes_enforce_task_ownership(client, admin_headers, test_db, monkeypatch):
    _enable_workflow_flags(monkeypatch)
    owner_task_id = _create_owned_task(client, admin_headers, "ComputerWorkflow private sentinel")
    owner_create = client.post(
        "/api/v2/computer/workflows",
        headers=admin_headers,
        json=_create_workflow_payload(owner_task_id),
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
            json=_create_workflow_payload(foreign_task_id),
        )
        client.cookies.clear()
        missing_create = client.post(
            "/api/v2/computer/workflows",
            headers=admin_headers,
            json=_create_workflow_payload(2_147_483_647),
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
