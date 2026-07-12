from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from backend.models import AiEmployee


CENTER_PAGE = Path("frontend/computer-execution-center.html")
DETAIL_PAGE = Path("frontend/computer-execution-detail.html")


def enable_computer_flags(monkeypatch, *, take_over: bool = True):
    settings = SimpleNamespace(
        IS_PRODUCTION=False,
        COMPUTER_EXECUTOR_ENABLED=True,
        OPENCLAW_ADAPTER_ENABLED=False,
        ISOLATED_DESKTOP_ENABLED=False,
        SCREEN_CAPTURE_ENABLED=True,
        HUMAN_TAKEOVER_ENABLED=take_over,
        COMPUTER_TEXT_INPUT_ENABLED=True,
        COMPUTER_MOUSE_INPUT_ENABLED=True,
        COMPUTER_CONTROL_ENABLED=False,
        SHELL_EXECUTION_ENABLED=False,
        CLIPBOARD_READ_ENABLED=False,
        CLIPBOARD_WRITE_ENABLED=False,
        FILE_UPLOAD_ENABLED=False,
        FILE_DOWNLOAD_ENABLED=False,
        MAC_SAFE_ACTION_ENABLED=False,
        MAC_SAFE_MOUSE_MOVE_ENABLED=False,
        MAC_SAFE_CLICK_ENABLED=False,
        MAC_SAFE_TEXT_INPUT_ENABLED=False,
        PER_ACTION_APPROVAL_ENABLED=False,
        POST_ACTION_VERIFICATION_ENABLED=False,
        COMPUTER_ALLOWED_APPLICATIONS=["隔离测试浏览器", "隔离文本编辑器", "隔离演示窗口"],
        COMPUTER_BLOCKED_APPLICATIONS=[],
        COMPUTER_ALLOWED_WINDOW_PATTERNS=[".*隔离.*", ".*测试.*", ".*演示.*"],
        COMPUTER_BLOCKED_WINDOW_PATTERNS=["Terminal", "iTerm", "系统设置"],
    )
    monkeypatch.setattr("backend.config.get_settings", lambda: settings)
    monkeypatch.setattr("backend.routers.computer_executor_v2.get_settings", lambda: settings)
    monkeypatch.setattr("backend.agent_runtime.executors.computer.runtime.get_settings", lambda: settings)
    monkeypatch.setattr("backend.agent_runtime.executors.computer.policy.get_settings", lambda: settings)
    monkeypatch.setattr("backend.skills_engine.permissions.get_flag", lambda name: True)
    return settings


def test_computer_executor_pages_exist_and_are_served(client):
    assert CENTER_PAGE.exists()
    assert DETAIL_PAGE.exists()

    center = client.get("/computer-execution-center.html")
    detail = client.get("/computer-execution-detail.html")

    assert center.status_code == 200
    assert detail.status_code == 200
    assert "电脑执行中心" in center.text
    assert "电脑执行详情" in detail.text


def test_computer_executor_pages_contain_safe_readonly_copy():
    html = CENTER_PAGE.read_text(encoding="utf-8") + DETAIL_PAGE.read_text(encoding="utf-8")

    for text in [
        "OpenClaw 安全适配层",
        "隔离桌面",
        "只读管理视图",
        "最近截图时间",
        "Terminal 阻断：通过",
        "HUMAN_TAKEOVER_ENABLED=false",
        "/api/v2/computer/sessions",
            "/api/v2/computer/action-policy/health",
    ]:
        assert text in html

    forbidden = [
        "输入密码",
        "打开 Terminal",
    ]
    for text in forbidden:
        assert text not in html


def test_computer_executor_api_flow_and_whitelist(client, owner_headers, monkeypatch):
    enable_computer_flags(monkeypatch)

    create = client.post("/api/v2/computer/sessions", headers=owner_headers, json={
        "execution_id": 1,
        "task_id": 1,
        "employee_id": 1,
        "skill_id": 1,
        "executor_type": "mock",
        "environment_type": "test",
        "risk_level": "低风险",
        "approval_status": "无需审批",
        "allowed_applications": ["隔离测试浏览器", "隔离文本编辑器", "隔离演示窗口"],
        "allowed_windows": [".*隔离.*"],
        "trace_id": "trace-computer-1",
    })
    assert create.status_code == 200
    session_id = create.json()["session"]["session_id"]

    window_state = client.get(f"/api/v2/computer/sessions/{session_id}/window-state", headers=owner_headers)
    assert window_state.status_code == 200
    assert window_state.json()["window_state"]["active_application"] == "隔离测试浏览器"

    action = client.post(
        f"/api/v2/computer/sessions/{session_id}/actions",
        headers=owner_headers,
        json={
            "action_type": "查看屏幕",
            "target_application": "隔离测试浏览器",
            "target_window": "隔离测试窗口",
            "target_description": "检查隔离桌面",
            "timeout": 20,
            "trace_id": "trace-computer-2",
        },
    )
    assert action.status_code == 200
    payload = action.json()
    assert payload["session"]["session_id"] == session_id
    assert payload["action"]["action_type"] == "查看屏幕"
    assert payload["evidence"]["reference"].startswith("evidence://")

    evidence = client.get(f"/api/v2/computer/sessions/{session_id}/evidence", headers=owner_headers)
    assert evidence.status_code == 200
    assert evidence.json()["items"]

    pause = client.post(f"/api/v2/computer/sessions/{session_id}/pause", headers=owner_headers)
    resume = client.post(f"/api/v2/computer/sessions/{session_id}/resume", headers=owner_headers)
    assert pause.status_code == 200
    assert resume.status_code == 200


def test_computer_executor_rejects_terminal_and_sensitive_input(client, owner_headers, monkeypatch):
    enable_computer_flags(monkeypatch)
    create = client.post("/api/v2/computer/sessions", headers=owner_headers, json={
        "executor_type": "mock",
        "environment_type": "test",
        "risk_level": "低风险",
        "approval_status": "无需审批",
        "allowed_applications": ["隔离测试浏览器"],
        "allowed_windows": [".*隔离.*"],
    })
    session_id = create.json()["session"]["session_id"]

    terminal = client.post(
        f"/api/v2/computer/sessions/{session_id}/actions",
        headers=owner_headers,
        json={"action_type": "单击", "target_application": "Terminal", "target_window": "Terminal", "coordinates": {"x": 10, "y": 10}},
    )
    assert terminal.status_code == 403

    sensitive = client.post(
        f"/api/v2/computer/sessions/{session_id}/actions",
        headers=owner_headers,
        json={"action_type": "输入普通文本", "target_application": "隔离文本编辑器", "target_window": "隔离测试窗口", "text_input": "password=123456"},
    )
    assert sensitive.status_code == 403


def test_computer_executor_handoff_requires_feature_flag(client, owner_headers, monkeypatch):
    enable_computer_flags(monkeypatch, take_over=False)
    create = client.post("/api/v2/computer/sessions", headers=owner_headers, json={
        "executor_type": "mock",
        "environment_type": "test",
        "risk_level": "低风险",
        "approval_status": "无需审批",
        "allowed_applications": ["隔离测试浏览器"],
        "allowed_windows": [".*隔离.*"],
    })
    session_id = create.json()["session"]["session_id"]

    takeover = client.post(f"/api/v2/computer/sessions/{session_id}/handoff", headers=owner_headers)
    assert takeover.status_code == 403


def test_computer_executor_skill_invocation_flow(client, owner_headers, monkeypatch, test_db):
    enable_computer_flags(monkeypatch)
    db = test_db()
    try:
        if not db.query(AiEmployee).filter(AiEmployee.employee_code == "tiancai_data").one_or_none():
            db.add(
                AiEmployee(
                    employee_code="tiancai_data",
                    employee_name="天采：数据采集平台",
                    legion="数据资产军团",
                    duty="公开网页读取与研究整理",
                    status="active",
                    task_types='["data_collection"]',
                    default_permissions='["skills.read"]',
                    is_legacy=False,
                    sort_order=50,
                )
            )
            db.commit()
    finally:
        db.close()

    list_response = client.get("/api/v2/skills", headers=owner_headers)
    assert list_response.status_code == 200
    skills = list_response.json()["skills"]
    skill = next(item for item in skills if item["skill_code"] == "computer.sandbox.status_check")

    install = client.post(f"/api/v2/skills/{skill['skill_id']}/install", headers=owner_headers, json={"employee_code": "tiancai_data"})
    assert install.status_code == 200
    installation_id = install.json()["installation"]["installation_id"]

    invoke = client.post(
        f"/api/v2/skills/{skill['skill_id']}/invoke",
        headers=owner_headers,
        json={
            "employee_code": "tiancai_data",
            "installation_id": installation_id,
            "input_payload": {"trace_id": "skill-computer-1"},
            "trace_id": "skill-computer-1",
        },
    )
    assert invoke.status_code == 200
    data = invoke.json()["invocation"]
    assert data["status"] == "执行成功"
    assert data["output_summary"]


def test_computer_executor_health_and_feature_flags(client, owner_headers, monkeypatch):
    enable_computer_flags(monkeypatch)
    health = client.get("/api/v2/computer-executor/health", headers=owner_headers)
    assert health.status_code == 200
    payload = health.json()
    assert payload["status"] == "healthy"
    assert payload["feature_flags"]["COMPUTER_EXECUTOR_ENABLED"] is True
    assert payload["feature_flags"]["OPENCLAW_ADAPTER_ENABLED"] is False
    assert payload["feature_flags"]["COMPUTER_CONTROL_ENABLED"] is False


def enable_safe_action_flags(monkeypatch):
    settings = SimpleNamespace(
        IS_PRODUCTION=False,
        COMPUTER_EXECUTOR_ENABLED=True,
        OPENCLAW_ADAPTER_ENABLED=False,
        ISOLATED_DESKTOP_ENABLED=True,
        SCREEN_CAPTURE_ENABLED=True,
        HUMAN_TAKEOVER_ENABLED=True,
        COMPUTER_TEXT_INPUT_ENABLED=True,
        COMPUTER_MOUSE_INPUT_ENABLED=True,
        COMPUTER_CONTROL_ENABLED=False,
        SHELL_EXECUTION_ENABLED=False,
        CLIPBOARD_READ_ENABLED=False,
        CLIPBOARD_WRITE_ENABLED=False,
        FILE_UPLOAD_ENABLED=False,
        FILE_DOWNLOAD_ENABLED=False,
        MAC_SAFE_ACTION_ENABLED=True,
        MAC_SAFE_MOUSE_MOVE_ENABLED=True,
        MAC_SAFE_CLICK_ENABLED=True,
        MAC_SAFE_TEXT_INPUT_ENABLED=True,
        PER_ACTION_APPROVAL_ENABLED=True,
        POST_ACTION_VERIFICATION_ENABLED=True,
        COMPUTER_ALLOWED_APPLICATIONS=["隔离测试浏览器", "隔离文本编辑器", "隔离演示窗口"],
        COMPUTER_BLOCKED_APPLICATIONS=[],
        COMPUTER_ALLOWED_WINDOW_PATTERNS=[".*隔离.*", ".*测试.*", ".*演示.*"],
        COMPUTER_BLOCKED_WINDOW_PATTERNS=["Terminal", "iTerm", "系统设置", "密码"],
    )
    monkeypatch.setattr("backend.config.get_settings", lambda: settings)
    monkeypatch.setattr("backend.routers.computer_executor_v2.get_settings", lambda: settings)
    monkeypatch.setattr("backend.agent_runtime.executors.computer.policy.get_settings", lambda: settings)
    monkeypatch.setattr("backend.agent_runtime.executors.computer.actions.policy.get_settings", lambda: settings)
    monkeypatch.setattr("backend.agent_runtime.registry.get_settings", lambda: settings)
    monkeypatch.setattr("backend.skills_engine.permissions.get_flag", lambda name: True)
    return settings


def test_safe_action_pages_and_health(client):
    assert Path("frontend/computer-action-approval.html").exists()
    assert Path("frontend/computer-action-test.html").exists()
    approval = client.get("/computer-action-approval.html")
    test_page = client.get("/computer-action-test.html")
    assert approval.status_code == 200
    assert test_page.status_code == 200
    assert "操作审批" in approval.text
    assert "天统 AI 单步操作测试环境" in test_page.text


def test_safe_action_plan_approval_execution_and_pause(client, owner_headers, monkeypatch):
    enable_safe_action_flags(monkeypatch)
    session = client.post(
        "/api/v2/computer/sessions",
        headers=owner_headers,
        json={
            "executor_type": "mock",
            "environment_type": "test",
            "risk_level": "中低",
            "approval_status": "等待审批",
            "allowed_applications": ["隔离测试浏览器", "隔离文本编辑器", "隔离演示窗口"],
            "allowed_windows": [".*隔离.*", ".*测试.*"],
            "trace_id": "trace-safe-action-session",
        },
    )
    assert session.status_code == 200
    session_id = session.json()["session"]["session_id"]

    create = client.post(
        "/api/v2/computer/action-plans",
        headers=owner_headers,
        json={
            "session_id": session_id,
            "task_id": 1,
            "employee_id": 1,
            "skill_id": 1,
            "target_application": "隔离测试浏览器",
            "target_bundle_id": "com.example.test",
            "target_window": "天统 AI 单步操作测试窗口",
            "goal": "单步测试按钮",
            "action_type": "单击",
            "control_type": "普通按钮",
            "control_label": "测试按钮",
            "control_identifier": "btn-test",
            "target_description": "点击安全测试按钮",
            "coordinates": {"x": 12, "y": 18},
            "text_input": None,
            "approval_mode": "逐步审批",
            "risk_level": "中低",
            "max_actions": 1,
            "trace_id": "trace-safe-action-plan",
            "allow_coordinate_fallback": False,
        },
    )
    assert create.status_code == 200
    payload = create.json()
    plan = payload["plan"]
    action_id = payload["target"]["action_id"]
    assert plan["status"] == "等待批准"
    assert payload["preview"]["expected_result"] == "执行单个动作后自动暂停"

    approve = client.post(f"/api/v2/computer/actions/{action_id}/approve?trace_id=trace-safe-approve", headers=owner_headers)
    assert approve.status_code == 200
    assert approve.json()["approval"]["approval_status"] == "已批准"

    repeat_approve = client.post(f"/api/v2/computer/actions/{action_id}/approve?trace_id=trace-safe-approve-2", headers=owner_headers)
    assert repeat_approve.status_code == 409

    execute = client.post(
        f"/api/v2/computer/actions/{action_id}/execute?current_application=隔离测试浏览器&current_window=天统 AI 单步操作测试窗口&trace_id=trace-safe-execute",
        headers=owner_headers,
    )
    assert execute.status_code == 200
    result = execute.json()
    assert result["plan"]["status"] == "已暂停"
    assert result["session"]["status"] == "已暂停"
    assert result["verification"]["verification_status"] in {"结果符合预期", "结果部分符合"}


def test_safe_action_blocks_sensitive_text(client, owner_headers, monkeypatch):
    enable_safe_action_flags(monkeypatch)
    create = client.post(
        "/api/v2/computer/sessions",
        headers=owner_headers,
        json={
            "executor_type": "mock",
            "environment_type": "test",
            "risk_level": "中低",
            "approval_status": "等待审批",
            "allowed_applications": ["隔离文本编辑器"],
            "allowed_windows": [".*测试.*"],
        },
    )
    session_id = create.json()["session"]["session_id"]
    blocked = client.post(
        "/api/v2/computer/action-plans",
        headers=owner_headers,
        json={
            "session_id": session_id,
            "target_application": "隔离文本编辑器",
            "target_window": "天统 AI 单步操作测试窗口",
            "goal": "输入敏感文本",
            "action_type": "输入普通文本",
            "control_type": "普通文本框",
            "control_label": "测试输入框",
            "control_identifier": "input-test",
            "target_description": "测试输入",
            "text_input": "password=123456",
            "trace_id": "trace-sensitive-block",
        },
    )
    assert blocked.status_code == 403
