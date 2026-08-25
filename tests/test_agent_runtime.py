from __future__ import annotations

import json

import pytest

from backend.agent_runtime.constants import DEFAULT_CAPABILITIES
from backend.brain_orchestrator.planner import resolve_graph_ownership
from backend.models import AiEmployee, TaskCenterTask, User
from backend.config import Settings, get_settings
from backend.task_center_ownership import TASK_OWNERSHIP_FIELDS, bind_task_ownership, owned_task_or_none


@pytest.fixture(autouse=True)
def enable_agent_runtime(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_agent_runtime_defaults_to_disabled_when_unset(monkeypatch):
    monkeypatch.delenv("AGENT_RUNTIME_ENABLED", raising=False)
    assert Settings().AGENT_RUNTIME_ENABLED is False


def test_agent_runtime_can_be_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_ENABLED", "true")
    assert Settings().AGENT_RUNTIME_ENABLED is True


def get_employee_id(test_db, employee_code: str) -> int:
    db = test_db()
    try:
        employee = db.query(AiEmployee).filter_by(employee_code=employee_code).one()
        return employee.id
    finally:
        db.close()


def create_capability(client, owner_headers, **overrides):
    client.cookies.clear()
    payload = {
        "capability_id": overrides.pop("capability_id", "custom.mock"),
        "capability_name": overrides.pop("capability_name", "自定义模拟能力"),
        "capability_type": overrides.pop("capability_type", "文件处理"),
        "description": overrides.pop("description", "自定义能力用于测试"),
        "executor_type": overrides.pop("executor_type", "mock"),
        "risk_level": overrides.pop("risk_level", "low"),
        "enabled": overrides.pop("enabled", True),
        "readonly": overrides.pop("readonly", True),
        "requires_boss_approval": overrides.pop("requires_boss_approval", False),
        "requires_security_audit": overrides.pop("requires_security_audit", False),
        "timeout_seconds": overrides.pop("timeout_seconds", 30),
        "max_retries": overrides.pop("max_retries", 0),
        "input_schema_json": overrides.pop("input_schema_json", '{"type":"object","additionalProperties":true}'),
        "output_schema_json": overrides.pop("output_schema_json", '{"type":"object","additionalProperties":true}'),
        "allowed_employee_codes": overrides.pop("allowed_employee_codes", []),
        "version": overrides.pop("version", "1.0.0"),
    }
    payload.update(overrides)
    response = client.post("/api/v2/capabilities", json=payload, headers=owner_headers)
    assert response.status_code == 200, response.text
    return response.json()["capability"]


def create_execution(client, headers, **payload):
    client.cookies.clear()
    response = client.post("/api/v2/executions", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["execution"]


def test_agent_runtime_health_and_builtin_capabilities(client, owner_headers):
    client.cookies.clear()
    health = client.get("/api/v2/agent-runtime/health", headers=owner_headers)
    assert health.status_code == 200
    payload = health.json()
    assert payload["ok"] is True
    assert payload["runtime_enabled"] is True
    assert payload["real_executor_enabled"] is False
    assert payload["feature_flags"]["AGENT_RUNTIME_ENABLED"] is True
    assert payload["feature_flags"]["REAL_EXECUTOR_ENABLED"] is False
    assert payload["feature_flags"]["BROWSER_READONLY_ENABLED"] is False
    assert payload["feature_flags"]["BROWSER_CONTROL_ENABLED"] is False
    assert payload["feature_flags"]["PUBLIC_RESEARCH_ENABLED"] is False
    assert payload["feature_flags"]["PUBLIC_SEARCH_ENABLED"] is False
    assert payload["capabilities"] >= len(DEFAULT_CAPABILITIES)

    listing = client.get("/api/v2/capabilities", headers=owner_headers)
    assert listing.status_code == 200
    items = listing.json()["items"]
    ids = {row["capability_id"] for row in items}
    assert "mock.echo" in ids
    assert "mock.failure" in ids
    assert "mock.timeout" in ids
    assert "mock.retry" in ids
    assert "browser.public.read" in ids
    assert "research.public.multi_source" in ids


def test_agent_runtime_requires_permission_and_supports_registration(client, viewer_headers, owner_headers):
    client.cookies.clear()
    denied = client.get("/api/v2/capabilities", headers=viewer_headers)
    assert denied.status_code == 403

    created = create_capability(
        client,
        owner_headers,
        capability_id="custom.registered",
        capability_name="自定义注册能力",
        capability_type="API 调用",
        executor_type="mock",
        risk_level="medium",
    )
    assert created["capability_id"] == "custom.registered"
    assert created["capability_type"] == "API 调用"

    detail = client.get("/api/v2/capabilities/custom.registered", headers=owner_headers)
    assert detail.status_code == 200
    assert detail.json()["capability"]["capability_id"] == "custom.registered"


def test_agent_runtime_execution_modes_and_audit(client, owner_headers, boss_headers, test_db):
    from backend.agent_runtime.models import AgentExecution, AgentExecutionAudit

    client.cookies.clear()
    db = test_db()
    try:
        owner = db.query(User).filter(User.username == "owner").one()
        foreign_user = db.query(User).filter(User.username == "admin").one()
        task = TaskCenterTask(title="V2 runtime linkage task", status="created", priority="normal", source="boss")
        db.add(task)
        bind_task_ownership(db, task, user=owner)
        db.commit()
        db.refresh(task)
        expected_scope = resolve_graph_ownership(db, owner)
        assert all(getattr(task, field) not in (None, "") for field in TASK_OWNERSHIP_FIELDS)
        assert task.requester_id == owner.id
        assert task.tenant_id == owner.tenant_id == expected_scope.tenant_id
        assert task.company_id == owner.company_id == expected_scope.company_id
        assert task.store_scope_key == expected_scope.store_scope_key
        assert task.ownership_scope_key == expected_scope.ownership_scope_key
        assert owned_task_or_none(db, task_id=task.id, user=owner) is task
        assert owned_task_or_none(db, task_id=task.id, user=foreign_user) is None
        task_id = task.id
    finally:
        db.close()

    employee_id = get_employee_id(test_db, "tianwang")

    success = create_execution(
        client,
        owner_headers,
        employee_id=employee_id,
        capability_id="mock.echo",
        input_payload={"message": "你好", "simulate_mode": "success", "link_task_result": True},
        task_id=task_id,
    )
    assert success["status"] == "success"
    assert success["approval_status"] == "not_required"
    assert success["output_payload"]["mode"] == "success"
    assert success["input_payload"]["message"] == "你好"

    failure = create_execution(
        client,
        owner_headers,
        employee_id=employee_id,
        capability_id="mock.failure",
        input_payload={"message": "fail", "simulate_mode": "failure"},
    )
    assert failure["status"] == "failed"
    assert failure["error_code"] == "MOCK_FAILURE"

    timeout = create_execution(
        client,
        owner_headers,
        employee_id=employee_id,
        capability_id="mock.timeout",
        input_payload={"message": "slow", "simulate_mode": "timeout"},
    )
    assert timeout["status"] == "timeout"
    assert timeout["error_code"] == "MOCK_TIMEOUT"

    retry = create_execution(
        client,
        owner_headers,
        employee_id=employee_id,
        capability_id="mock.retry",
        input_payload={"message": "retry", "simulate_mode": "retry"},
    )
    assert retry["status"] == "success"
    assert retry["retry_count"] >= 1

    high_risk_capability = create_capability(
        client,
        owner_headers,
        capability_id="shell.dangerous.mock",
        capability_name="高风险模拟能力",
        capability_type="Shell 操作",
        executor_type="mock",
        risk_level="high",
        requires_boss_approval=True,
        requires_security_audit=True,
        allowed_employee_codes=["tianwang"],
    )
    assert high_risk_capability["requires_boss_approval"] is True

    waiting = create_execution(
        client,
        owner_headers,
        employee_id=employee_id,
        capability_id="shell.dangerous.mock",
        input_payload={"message": "await approval"},
    )
    assert waiting["status"] == "waiting_approval"
    assert waiting["approval_status"] == "pending"

    missing_execution_id = "00000000-0000-0000-0000-000000000000"
    db = test_db()
    try:
        owner = db.query(User).filter(User.username == "owner").one()
        waiting_row = db.get(AgentExecution, waiting["execution_id"])
        assert waiting_row is not None
        owner_scope = resolve_graph_ownership(db, owner)
        ownership_before = (
            waiting_row.created_by_id,
            owner.id,
            owner.tenant_id,
            owner.company_id,
            owner_scope.store_scope_key,
            owner_scope.ownership_scope_key,
        )
        foreign_write_before = (
            db.query(AgentExecution).count(),
            db.query(AgentExecutionAudit).count(),
            waiting_row.status,
            waiting_row.approval_status,
            waiting_row.output_payload,
            waiting_row.error_code,
        )
    finally:
        db.close()

    foreign_detail = client.get(f"/api/v2/executions/{waiting['execution_id']}", headers=boss_headers)
    missing_detail = client.get(f"/api/v2/executions/{missing_execution_id}", headers=boss_headers)
    assert foreign_detail.status_code == missing_detail.status_code == 404
    assert foreign_detail.json() == missing_detail.json() == {"detail": "执行记录不存在"}

    foreign_approval = client.post(
        f"/api/v2/executions/{waiting['execution_id']}/approve",
        json={"boss_confirmed": True, "security_audited": True},
        headers=boss_headers,
    )
    missing_approval = client.post(
        f"/api/v2/executions/{missing_execution_id}/approve",
        json={"boss_confirmed": True, "security_audited": True},
        headers=boss_headers,
    )
    assert foreign_approval.status_code == missing_approval.status_code == 404
    assert foreign_approval.json() == missing_approval.json() == {"detail": "执行记录不存在"}

    db = test_db()
    try:
        waiting_row = db.get(AgentExecution, waiting["execution_id"])
        assert waiting_row is not None
        assert (
            db.query(AgentExecution).count(),
            db.query(AgentExecutionAudit).count(),
            waiting_row.status,
            waiting_row.approval_status,
            waiting_row.output_payload,
            waiting_row.error_code,
        ) == foreign_write_before
    finally:
        db.close()

    approved = client.post(
        f"/api/v2/executions/{waiting['execution_id']}/approve",
        json={"boss_confirmed": True, "security_audited": True},
        headers=owner_headers,
    )
    assert approved.status_code == 200, approved.text
    approved_data = approved.json()["execution"]
    assert approved_data["execution_id"] == waiting["execution_id"]
    assert approved_data["status"] == "success"
    assert approved_data["approval_status"] == "approved"

    db = test_db()
    try:
        owner = db.query(User).filter(User.username == "owner").one()
        approved_row = db.get(AgentExecution, waiting["execution_id"])
        assert approved_row is not None
        owner_scope = resolve_graph_ownership(db, owner)
        assert (
            approved_row.created_by_id,
            owner.id,
            owner.tenant_id,
            owner.company_id,
            owner_scope.store_scope_key,
            owner_scope.ownership_scope_key,
        ) == ownership_before
        assert db.query(AgentExecution).count() == foreign_write_before[0]
        approval_audits = (
            db.query(AgentExecutionAudit)
            .filter(
                AgentExecutionAudit.execution_id == waiting["execution_id"],
                AgentExecutionAudit.event_type == "execution_approved",
            )
            .all()
        )
        assert len(approval_audits) == 1
        assert approval_audits[0].actor_id == "user:owner"
        assert approval_audits[0].approval_status == "approved"
        assert approval_audits[0].approval_decision == "approved"
    finally:
        db.close()

    denied = create_execution(
        client,
        owner_headers,
        employee_id=employee_id,
        capability_id="shell.dangerous.mock",
        input_payload={"message": "reject me"},
    )
    reject_response = client.post(
        f"/api/v2/executions/{denied['execution_id']}/reject",
        json={"reason": "不执行"},
        headers=owner_headers,
    )
    assert reject_response.status_code == 200
    rejected = reject_response.json()["execution"]
    assert rejected["status"] == "rejected"
    assert rejected["approval_status"] == "rejected"

    cancellable = create_execution(
        client,
        owner_headers,
        employee_id=employee_id,
        capability_id="shell.dangerous.mock",
        input_payload={"message": "cancel me"},
    )
    cancel_response = client.post(
        f"/api/v2/executions/{cancellable['execution_id']}/cancel",
        json={"reason": "人工取消"},
        headers=owner_headers,
    )
    assert cancel_response.status_code == 200
    cancelled = cancel_response.json()["execution"]
    assert cancelled["status"] == "cancelled"

    audit = client.get(f"/api/v2/executions/{success['execution_id']}/audit", headers=owner_headers)
    assert audit.status_code == 200
    audit_items = audit.json()["items"]
    event_types = [row["event_type"] for row in audit_items]
    assert "execution_created" in event_types
    assert "execution_started" in event_types
    assert "execution_succeeded" in event_types
    assert all("password" not in json.dumps(row, ensure_ascii=False).lower() for row in audit_items)

    db = test_db()
    try:
        task_row = db.get(TaskCenterTask, task_id)
        assert task_row.summary and "[V2 Agent Runtime]" in task_row.summary
    finally:
        db.close()


def test_agent_runtime_feature_flag_off_blocks_execution(client, owner_headers, monkeypatch, test_db):
    client.cookies.clear()
    monkeypatch.setenv("AGENT_RUNTIME_ENABLED", "false")
    get_settings.cache_clear()
    try:
        employee_id = get_employee_id(test_db, "tianwang")
        response = client.post(
            "/api/v2/executions",
            json={
                "employee_id": employee_id,
                "capability_id": "mock.echo",
                "input_payload": {"message": "disabled"},
            },
            headers=owner_headers,
        )
        assert response.status_code == 400
        assert "Agent Runtime 已关闭" in response.text
    finally:
        monkeypatch.delenv("AGENT_RUNTIME_ENABLED", raising=False)
        get_settings.cache_clear()


def test_agent_runtime_sanitizes_sensitive_fields(client, owner_headers, test_db):
    client.cookies.clear()
    employee_id = get_employee_id(test_db, "tianwang")
    execution = create_execution(
        client,
        owner_headers,
        employee_id=employee_id,
        capability_id="mock.echo",
        input_payload={"password": "secret", "token": "abc", "message": "hello"},
    )
    assert "[已脱敏]" in execution["input_payload"]
    assert "password" not in execution["input_payload"]
    assert "token" not in execution["input_payload"]
    detail = client.get(f"/api/v2/executions/{execution['execution_id']}", headers=owner_headers)
    assert detail.status_code == 200
    text = detail.text.lower()
    assert "secret" not in text
    assert "token" not in text
    assert "password" not in text


def test_v1_regression_and_agent_runtime_pages(client, owner_headers):
    client.cookies.clear()
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/task-center/tasks", headers=owner_headers).status_code == 200

    for path, text in [
        ("/agent-runtime.html", "Agent Runtime"),
        ("/capability-center.html", "能力中心"),
        ("/execution-records.html", "执行记录"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert text in response.text
