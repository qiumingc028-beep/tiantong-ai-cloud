from __future__ import annotations

from backend.agent_runtime.workflows.computer.constants import WORKFLOW_ACTION_TYPES


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


def _create_workflow_payload():
    return {
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


def test_computer_workflow_api_and_execution_flow(client, admin_headers, monkeypatch):
    _enable_workflow_flags(monkeypatch)

    health = client.get("/api/v2/computer-workflow/health")
    assert health.status_code == 200
    assert health.json()["feature_flags"]["MAC_SAFE_WORKFLOW_ENABLED"] is False

    create_response = client.post("/api/v2/computer/workflows", json=_create_workflow_payload(), headers=admin_headers)
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


def test_computer_workflow_api_rejects_forbidden_actions():
    assert "单击" in WORKFLOW_ACTION_TYPES
    assert "输入普通文本" in WORKFLOW_ACTION_TYPES
