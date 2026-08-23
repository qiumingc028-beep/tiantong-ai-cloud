from __future__ import annotations

import uuid
from types import SimpleNamespace
from pathlib import Path

import pytest

from backend.agent_runtime.executors.computer.actions.models import (
    ComputerActionApproval,
    ComputerActionPlan,
    ComputerActionTarget,
)
from backend.agent_runtime.executors.computer.models import ComputerAction, ComputerEvidence, ComputerPolicyEvent
from backend.agent_runtime.executors.computer.session import add_evidence_row, add_policy_event
from backend.models import AiEmployee


CENTER_PAGE = Path("frontend/computer-execution-center.html")
DETAIL_PAGE = Path("frontend/computer-execution-detail.html")


def test_computer_policy_event_id_is_deterministic_uuid_without_truncation(test_db):
    assert ComputerPolicyEvent.__table__.c.event_id.type.length == 36
    db = test_db()
    try:
        def stored_event_id(session_id, action_id, event_code):
            row = add_policy_event(
                db,
                session_id=session_id,
                action_id=action_id,
                event_code=event_code,
                event_message="policy event id regression",
                risk_level="低风险",
            )
            event_id = row.event_id
            assert db.get(ComputerPolicyEvent, event_id) is row
            db.rollback()
            return event_id

        long_components = ("s" * 36, "a" * 36, "EVENT_" + "x" * 74)
        first_id = stored_event_id(*long_components)
        assert len(first_id) == 36
        assert uuid.UUID(first_id).version == 5
        assert stored_event_id(*long_components) == first_id
        assert stored_event_id("scope-a", "b", "c") != stored_event_id("scope", "a-b", "c")
        assert stored_event_id(None, None, "x" * 79 + "a") != stored_event_id(None, None, "x" * 79 + "b")
    finally:
        db.rollback()
        db.close()


def test_computer_evidence_id_is_deterministic_uuid_without_truncation(test_db):
    assert ComputerEvidence.__table__.c.evidence_id.type.length == 36
    db = test_db()
    try:
        def stored_evidence_id(session_id, action_id, evidence_type, reference):
            row = add_evidence_row(
                db,
                session_id=session_id,
                action_id=action_id,
                evidence_type=evidence_type,
                reference=reference,
                metadata={"kind": "evidence id regression"},
            )
            evidence_id = row.evidence_id
            assert db.get(ComputerEvidence, evidence_id) is row
            db.rollback()
            return evidence_id

        long_components = (
            "s" * 36,
            "a" * 36,
            "screenshot-" + "x" * 40,
            "file:///private/tmp/" + "r" * 120 + ".png",
        )
        first_id = stored_evidence_id(*long_components)
        assert len(first_id) == 36
        assert uuid.UUID(first_id).version == 5
        assert stored_evidence_id(*long_components) == first_id
        assert stored_evidence_id("scope-a", None, "b", "c") != stored_evidence_id("scope", None, "a-b", "c")
        assert stored_evidence_id("scope", None, "type", "x" * 119 + "a") != stored_evidence_id("scope", None, "type", "x" * 119 + "b")
    finally:
        db.rollback()
        db.close()


def test_computer_evidence_uuid5_persists_with_action_foreign_key(postgres_alpha_runtime, monkeypatch):
    client, owner_headers, session_factory = postgres_alpha_runtime
    enable_computer_flags(monkeypatch)
    created = client.post(
        "/api/v2/computer/sessions",
        headers=owner_headers,
        json={"executor_type": "mock", "environment_type": "test"},
    )
    assert created.status_code == 200
    session_id = created.json()["session"]["session_id"]
    action_id = uuid.uuid4().hex
    db = session_factory()
    try:
        db.add(
            ComputerAction(
                action_id=action_id,
                session_id=session_id,
                sequence_number=1,
                action_type="截图",
                risk_level="低风险",
                approval_required=False,
                approval_status="无需审批",
            )
        )
        db.flush()
        evidence = add_evidence_row(
            db,
            session_id=session_id,
            action_id=action_id,
            evidence_type="screenshot",
            reference="file:///private/tmp/" + "r" * 120 + ".png",
            metadata={"provider": "chrome_cdp_page_capture"},
        )
        evidence_id = evidence.evidence_id
        db.commit()
        stored = db.get(ComputerEvidence, evidence_id)
        assert stored is not None
        assert stored.action_id == action_id
        assert len(stored.evidence_id) == 36
        assert uuid.UUID(stored.evidence_id).version == 5
        assert "Bearer " not in (stored.metadata_json or "")
    finally:
        db.rollback()
        db.close()


def test_action_plan_persists_action_before_policy_event_and_rolls_back_atomically(postgres_alpha_runtime, monkeypatch):
    client, owner_headers, session_factory = postgres_alpha_runtime
    enable_safe_action_flags(monkeypatch)
    task = client.post(
        "/api/task-center/tasks",
        headers=owner_headers,
        json={"title": "R190 action policy transaction", "description": "owner-bound action plan"},
    )
    assert task.status_code == 200, task.text
    created_session = client.post(
        "/api/v2/computer/sessions",
        headers=owner_headers,
        json={
            "task_id": task.json()["task"]["id"],
            "executor_type": "mock",
            "environment_type": "test",
            "risk_level": "中低",
            "approval_status": "等待审批",
            "allowed_applications": ["隔离测试浏览器"],
            "allowed_windows": [".*测试.*"],
        },
    )
    assert created_session.status_code == 200
    session_id = created_session.json()["session"]["session_id"]

    def plan_payload(trace_id):
        return {
            "session_id": session_id,
            "target_application": "隔离测试浏览器",
            "target_window": "天统 AI 单步操作测试窗口",
            "goal": "验证动作与策略事件原子持久化",
            "action_type": "单击",
            "control_type": "普通按钮",
            "control_label": "测试按钮",
            "control_identifier": "btn-r190",
            "target_description": "点击安全测试按钮",
            "coordinates": {"x": 12, "y": 18},
            "approval_mode": "逐步审批",
            "risk_level": "中低",
            "max_actions": 1,
            "trace_id": trace_id,
            "allow_coordinate_fallback": False,
        }

    created = client.post(
        "/api/v2/computer/action-plans",
        headers=owner_headers,
        json=plan_payload("trace-r190-commit"),
    )
    assert created.status_code == 200
    action_id = created.json()["target"]["action_id"]
    db = session_factory()
    try:
        action = db.get(ComputerAction, action_id)
        event = db.query(ComputerPolicyEvent).filter(
            ComputerPolicyEvent.action_id == action_id,
            ComputerPolicyEvent.event_code == "ACTION_PREVIEW_CREATED",
        ).one()
        assert action is not None
        assert event.action_id == action.action_id
        assert len(event.event_id) == 36
    finally:
        db.close()


    approved = client.post(
        f"/api/v2/computer/actions/{action_id}/approve?trace_id=trace-r190-cross-session-approve",
        headers=owner_headers,
    )
    assert approved.status_code == 200
    other_session = client.post(
        "/api/v2/computer/sessions",
        headers=owner_headers,
        json={
            "executor_type": "mock",
            "environment_type": "test",
            "risk_level": "中低",
            "approval_status": "等待审批",
            "allowed_applications": ["隔离测试浏览器"],
            "allowed_windows": [".*测试.*"],
        },
    )
    assert other_session.status_code == 200
    other_session_id = other_session.json()["session"]["session_id"]
    db = session_factory()
    try:
        action_before = db.get(ComputerAction, action_id)
        action_state_before = (
            action_before.session_id,
            action_before.trace_id,
            action_before.result,
            action_before.finished_at,
        )
        evidence_count_before = db.query(ComputerEvidence).count()
        event_count_before = db.query(ComputerPolicyEvent).count()
    finally:
        db.close()

    cross_session = client.post(
        f"/api/v2/computer/sessions/{other_session_id}/actions",
        headers=owner_headers,
        json={
            "action_type": "单击",
            "target_application": "隔离测试浏览器",
            "target_window": "天统 AI 单步操作测试窗口",
            "target_description": "跨会话动作必须拒绝",
            "coordinates": {"x": 12, "y": 18},
            "trace_id": "trace-r190-cross-session",
            "approval_context": {
                "plan_id": created.json()["plan"]["plan_id"],
                "action_id": action_id,
            },
        },
    )
    assert cross_session.status_code == 404
    assert cross_session.json()["detail"] == "动作计划不存在"
    db = session_factory()
    try:
        action_after = db.get(ComputerAction, action_id)
        assert (
            action_after.session_id,
            action_after.trace_id,
            action_after.result,
            action_after.finished_at,
        ) == action_state_before
        assert db.query(ComputerEvidence).count() == evidence_count_before
        assert db.query(ComputerPolicyEvent).count() == event_count_before
    finally:
        db.close()

    from backend.agent_runtime.executors.computer.actions import service

    original_add_policy_event = service.add_policy_event
    with monkeypatch.context() as failure_patch:
        def fail_after_policy_event(*args, **kwargs):
            original_add_policy_event(*args, **kwargs)
            raise RuntimeError("R190 forced rollback after policy event flush")

        failure_patch.setattr(service, "add_policy_event", fail_after_policy_event)
        with pytest.raises(RuntimeError, match="R190 forced rollback"):
            client.post(
                "/api/v2/computer/action-plans",
                headers=owner_headers,
                json=plan_payload("trace-r190-rollback"),
            )

    db = session_factory()
    try:
        assert db.query(ComputerAction).filter(ComputerAction.trace_id == "trace-r190-rollback").count() == 0
        assert db.query(ComputerPolicyEvent).filter(ComputerPolicyEvent.trace_id == "trace-r190-rollback").count() == 0
        assert db.query(ComputerActionPlan).filter(ComputerActionPlan.trace_id == "trace-r190-rollback").count() == 0
    finally:
        db.close()

    retried = client.post(
        "/api/v2/computer/action-plans",
        headers=owner_headers,
        json=plan_payload("trace-r190-rollback"),
    )
    assert retried.status_code == 200
    retried_action_id = retried.json()["target"]["action_id"]
    db = session_factory()
    try:
        assert db.query(ComputerAction).filter(ComputerAction.trace_id == "trace-r190-rollback").one().action_id == retried_action_id
        assert db.query(ComputerPolicyEvent).filter(
            ComputerPolicyEvent.action_id == retried_action_id,
            ComputerPolicyEvent.event_code == "ACTION_PREVIEW_CREATED",
        ).count() == 1
    finally:
        db.close()


def test_public_action_plan_is_owner_scoped_and_idempotent(postgres_alpha_runtime, monkeypatch):
    client, owner_headers, session_factory = postgres_alpha_runtime
    enable_safe_action_flags(monkeypatch)
    task = client.post(
        "/api/task-center/tasks",
        headers=owner_headers,
        json={"title": "R195 owner idempotent plan", "description": "server-owned action plan"},
    )
    assert task.status_code == 200, task.text
    task_id = task.json()["task"]["id"]
    session = client.post(
        "/api/v2/computer/sessions",
        headers=owner_headers,
        json={
            "task_id": task_id,
            "executor_type": "mock",
            "environment_type": "test",
            "allowed_applications": ["隔离测试浏览器"],
            "allowed_windows": [".*测试.*"],
            "trace_id": "r195-owner-session",
        },
    )
    assert session.status_code == 200, session.text
    session_id = session.json()["session"]["session_id"]
    taskless_session = client.post(
        "/api/v2/computer/sessions",
        headers=owner_headers,
        json={"executor_type": "mock", "environment_type": "test", "trace_id": "r195-taskless-owner-session"},
    )
    assert taskless_session.status_code == 200, taskless_session.text
    payload = {
        "session_id": session_id,
        "task_id": task_id,
        "target_application": "隔离测试浏览器",
        "target_window": "天统 AI 单步操作测试窗口",
        "goal": "R195 owner idempotency",
        "action_type": "单击",
        "control_type": "普通按钮",
        "control_label": "测试按钮",
        "control_identifier": "r195-owner-button",
        "target_description": "同一步骤安全重试",
        "coordinates": {"x": 12, "y": 18},
        "trace_id": "r195-owner-step-trace",
        "tenant_id": 999999,
        "company_id": 999999,
        "requester_id": 999999,
        "owner_id": 999999,
    }

    first = client.post("/api/v2/computer/action-plans", headers=owner_headers, json=payload)
    assert first.status_code == 200, first.text
    repeated = client.post("/api/v2/computer/action-plans", headers=owner_headers, json=payload)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["plan"]["plan_id"] == first.json()["plan"]["plan_id"]
    assert repeated.json()["target"]["action_id"] == first.json()["target"]["action_id"]

    admin_login = client.post("/api/login", json={"username": "admin", "password": "password"})
    assert admin_login.status_code == 200
    foreign_headers = {"Authorization": f"Bearer {admin_login.json()['token']}"}
    foreign = client.post("/api/v2/computer/action-plans", headers=foreign_headers, json=payload)
    assert foreign.status_code == 404
    assert foreign.json()["detail"] == "动作计划不存在"
    missing = client.post(
        "/api/v2/computer/action-plans",
        headers=foreign_headers,
        json={**payload, "session_id": uuid.uuid4().hex},
    )
    assert missing.status_code == foreign.status_code
    assert missing.json() == foreign.json()
    foreign_task = client.post(
        "/api/task-center/tasks",
        headers=foreign_headers,
        json={"title": "R195 foreign taskless claim", "description": "must not claim another session"},
    )
    assert foreign_task.status_code == 200, foreign_task.text
    foreign_task_claim = client.post(
        "/api/v2/computer/action-plans",
        headers=foreign_headers,
        json={**payload, "task_id": foreign_task.json()["task"]["id"]},
    )
    assert foreign_task_claim.status_code == 404
    assert foreign_task_claim.json()["detail"] == "动作计划不存在"
    taskless_claim = client.post(
        "/api/v2/computer/action-plans",
        headers=foreign_headers,
        json={
            **payload,
            "session_id": taskless_session.json()["session"]["session_id"],
            "task_id": foreign_task.json()["task"]["id"],
            "trace_id": "r195-taskless-foreign-claim",
        },
    )
    assert taskless_claim.status_code == 404
    assert taskless_claim.json()["detail"] == "动作计划不存在"

    client.cookies.clear()
    changed = client.post(
        "/api/v2/computer/action-plans",
        headers=owner_headers,
        json={**payload, "target_description": "不同步骤或payload不得复用"},
    )
    assert changed.status_code == 409
    assert "plan" not in changed.json()
    zero_max_payload = {**payload, "trace_id": "r195-owner-zero-max", "max_actions": 0}
    zero_max_first = client.post("/api/v2/computer/action-plans", headers=owner_headers, json=zero_max_payload)
    zero_max_retry = client.post("/api/v2/computer/action-plans", headers=owner_headers, json=zero_max_payload)
    assert zero_max_first.status_code == zero_max_retry.status_code == 200
    assert zero_max_first.json()["plan"]["plan_id"] == zero_max_retry.json()["plan"]["plan_id"]
    assert zero_max_retry.json()["plan"]["max_actions"] == 1

    with session_factory() as db:
        plan = db.query(ComputerActionPlan).filter(ComputerActionPlan.trace_id == payload["trace_id"]).one()
        target = db.query(ComputerActionTarget).filter(ComputerActionTarget.plan_id == plan.plan_id).one()
        approval = db.query(ComputerActionApproval).filter(ComputerActionApproval.plan_id == plan.plan_id).one()
        action = db.get(ComputerAction, target.action_id)
        assert plan.task_id == task_id
        assert target.action_id == approval.action_id == action.action_id
        assert action.session_id == session_id
        assert db.query(ComputerActionPlan).filter(ComputerActionPlan.trace_id == payload["trace_id"]).count() == 1
        graph_counts = (
            db.query(ComputerActionPlan).count(),
            db.query(ComputerActionTarget).count(),
            db.query(ComputerActionApproval).count(),
            db.query(ComputerAction).count(),
            db.query(ComputerPolicyEvent).count(),
        )
        target.control_label = "持久化图已被篡改"
        db.commit()

    corrupted = client.post("/api/v2/computer/action-plans", headers=owner_headers, json=payload)
    assert corrupted.status_code == 409
    with session_factory() as db:
        assert db.query(ComputerActionPlan).filter(ComputerActionPlan.trace_id == payload["trace_id"]).count() == 1
        assert (
            db.query(ComputerActionPlan).count(),
            db.query(ComputerActionTarget).count(),
            db.query(ComputerActionApproval).count(),
            db.query(ComputerAction).count(),
            db.query(ComputerPolicyEvent).count(),
        ) == graph_counts


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
    monkeypatch.setattr("backend.agent_runtime.executors.computer.runtime.get_settings", lambda: settings)
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
    task = client.post(
        "/api/task-center/tasks",
        headers=owner_headers,
        json={"title": "Safe action owner task", "description": "owner-bound safe action"},
    )
    assert task.status_code == 200, task.text
    session = client.post(
        "/api/v2/computer/sessions",
        headers=owner_headers,
        json={
            "task_id": task.json()["task"]["id"],
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
