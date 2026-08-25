from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.agent_runtime.executor_types import ExecutorContext
from backend.agent_runtime.executors.browser.executor import ReadonlyHttpBrowserExecutor, fetch_document
from backend.agent_runtime.executors.browser.exceptions import BrowserPolicyError
from backend.agent_runtime.executors.browser.policy import normalize_url
from backend.agent_runtime.executors.browser.schemas import FetchedDocument
from backend.config import get_settings
from backend.models import AiEmployee, TaskCenterTask
from tests.task_center_ownership_helpers import (
    bind_pending_tasks as _bind_pending_tasks,
    owner_db as _owner_db,
)


def enable_browser_readonly(monkeypatch):
    monkeypatch.setenv("BROWSER_READONLY_ENABLED", "true")
    monkeypatch.setenv("BROWSER_ALLOWED_DOMAINS", "example.com")
    monkeypatch.setenv("BROWSER_ALLOW_HTTP", "false")
    monkeypatch.setenv("BROWSER_BLOCK_PRIVATE_NETWORKS", "true")
    monkeypatch.setenv("BROWSER_MAX_REDIRECTS", "3")
    monkeypatch.setenv("BROWSER_DEFAULT_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("BROWSER_MAX_RESPONSE_BYTES", "2000000")
    get_settings.cache_clear()


def teardown_browser_settings(monkeypatch):
    for name in [
        "BROWSER_READONLY_ENABLED",
        "BROWSER_ALLOWED_DOMAINS",
        "BROWSER_ALLOW_HTTP",
        "BROWSER_BLOCK_PRIVATE_NETWORKS",
        "BROWSER_MAX_REDIRECTS",
        "BROWSER_DEFAULT_TIMEOUT_SECONDS",
        "BROWSER_MAX_RESPONSE_BYTES",
    ]:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


def test_browser_capability_seed_and_default_feature_flags(client, owner_headers, test_db, monkeypatch, alpha_enabled):
    from backend.agent_runtime.constants import DEFAULT_CAPABILITIES
    from backend.agent_runtime.executors.browser import executor as browser_executor
    from backend.agent_runtime.models import AgentCapability, AgentExecution, AgentExecutionAudit

    def business_state():
        db = test_db()
        try:
            return (
                db.query(AgentExecution).count(),
                db.query(AgentExecutionAudit).count(),
                db.query(TaskCenterTask).count(),
            )
        finally:
            db.close()

    def registry_state():
        db = test_db()
        try:
            rows = db.query(AgentCapability).all()
            return (
                {
                    row.capability_id: (
                        row.capability_name,
                        row.capability_type,
                        row.executor_type,
                        row.risk_level,
                        row.enabled,
                        row.readonly,
                        row.requires_boss_approval,
                        row.requires_security_audit,
                        row.timeout_seconds,
                        row.max_retries,
                        row.version,
                    )
                    for row in rows
                },
                db.query(AgentCapability)
                .filter(AgentCapability.capability_id == "browser.public.read")
                .count(),
            )
        finally:
            db.close()

    external_actions = []

    def reject_external_action(**kwargs):
        external_actions.append(kwargs)
        raise AssertionError("capability listing must not execute the browser")

    monkeypatch.setattr(browser_executor, "fetch_document", reject_external_action)
    settings = get_settings()
    assert settings.AGENT_RUNTIME_ENABLED is True
    assert settings.REAL_EXECUTOR_ENABLED is False
    assert settings.BROWSER_READONLY_ENABLED is False
    assert settings.BROWSER_CONTROL_ENABLED is False
    before_business = business_state()
    before_registry, before_browser_count = registry_state()
    before_ids = set(before_registry)

    client.cookies.clear()
    health = client.get("/api/v2/agent-runtime/health", headers=owner_headers)
    assert health.status_code == 200
    payload = health.json()
    assert payload["feature_flags"]["BROWSER_READONLY_ENABLED"] is False
    assert payload["feature_flags"]["BROWSER_CONTROL_ENABLED"] is False

    listing = client.get("/api/v2/capabilities", headers=owner_headers)
    assert listing.status_code == 200
    items = listing.json()["items"]
    browser = next(row for row in items if row["capability_id"] == "browser.public.read")
    assert browser["executor_type"] == "browser"
    assert browser["capability_type"] == "浏览器操作"
    assert browser["risk_level"] == "low"
    assert browser["readonly"] is True
    assert browser["enabled"] is False
    assert browser["requires_boss_approval"] is False
    assert browser["requires_security_audit"] is True
    assert browser["allowed_employee_codes"] == ["tiancai_data"]
    assert browser["executor_status"] in {"停用", "已关闭"}
    assert external_actions == []
    after_first_registry, after_first_browser_count = registry_state()
    after_first_ids = set(after_first_registry)
    builtin_ids = {str(row["capability_id"]) for row in DEFAULT_CAPABILITIES}
    expected_missing_ids = builtin_ids - before_ids
    actual_new_ids = after_first_ids - before_ids
    assert builtin_ids <= after_first_ids
    assert actual_new_ids == expected_missing_ids
    assert len(after_first_registry) - len(before_registry) == len(expected_missing_ids)
    preserved_registry = {
        capability_id: after_first_registry[capability_id]
        for capability_id in before_ids
    }
    assert preserved_registry == before_registry
    assert after_first_browser_count == 1
    assert after_first_registry["browser.public.read"] == (
        "公开网页读取",
        "浏览器操作",
        "browser",
        "low",
        False,
        True,
        False,
        True,
        20,
        1,
        "1.0.0",
    )
    assert business_state() == before_business

    second_listing = client.get("/api/v2/capabilities", headers=owner_headers)
    assert second_listing.status_code == 200
    assert second_listing.json() == listing.json()
    after_second_registry, after_second_browser_count = registry_state()
    assert len(after_second_registry) - len(after_first_registry) == 0
    assert set(after_second_registry) == after_first_ids
    assert after_second_registry == after_first_registry
    assert after_second_browser_count == 1
    assert business_state() == before_business
    assert external_actions == []

    monkeypatch.setenv("AGENT_RUNTIME_ENABLED", "false")
    get_settings.cache_clear()
    restored = get_settings()
    assert restored.AGENT_RUNTIME_ENABLED is False
    assert restored.BROWSER_READONLY_ENABLED is False
    assert restored.BROWSER_CONTROL_ENABLED is False


def test_browser_url_policy_blocks_private_network_and_bad_schemes(monkeypatch):
    enable_browser_readonly(monkeypatch)
    try:
        from backend.agent_runtime.executors.browser import policy as browser_policy
        monkeypatch.setattr(browser_policy, "resolve_host_ips", lambda host: ["93.184.216.34"])
        assert normalize_url("https://news.example.com/article?q=1") == "https://news.example.com/article?q=1"

        with pytest.raises(BrowserPolicyError) as excinfo:
            normalize_url("http://news.example.com/article")
        assert excinfo.value.code == "URL_NOT_ALLOWED"

        with pytest.raises(BrowserPolicyError) as excinfo:
            normalize_url("file:///etc/passwd")
        assert excinfo.value.code == "URL_NOT_ALLOWED"

        with pytest.raises(BrowserPolicyError) as excinfo:
            normalize_url("https://127.0.0.1/")
        assert excinfo.value.code == "DOMAIN_NOT_ALLOWED"
    finally:
        teardown_browser_settings(monkeypatch)


def test_browser_policy_rejects_private_dns_resolution(monkeypatch):
    enable_browser_readonly(monkeypatch)
    from backend.agent_runtime.executors.browser import policy as browser_policy

    monkeypatch.setattr(browser_policy, "resolve_host_ips", lambda host: ["10.0.0.1"])
    try:
        with pytest.raises(BrowserPolicyError) as excinfo:
            normalize_url("https://news.example.com/article")
        assert excinfo.value.code == "PRIVATE_NETWORK_BLOCKED"
    finally:
        teardown_browser_settings(monkeypatch)


def test_readonly_browser_executor_extracts_public_page_and_writes_back(
    client, owner_headers, test_db, monkeypatch, alpha_enabled
):
    enable_browser_readonly(monkeypatch)
    client.cookies.clear()
    db = _owner_db(test_db)
    try:
        employee = AiEmployee(
            employee_code="tiancai_data",
            employee_name="天采：数据采集平台",
            legion="研发交付军团",
            duty="公开网页数据采集",
            status="active",
            task_types='["browser"]',
            default_permissions='["task_center.execute"]',
            is_legacy=False,
            sort_order=20,
        )
        task = TaskCenterTask(title="浏览器只读采集任务", status="created", priority="normal", source="boss")
        db.add_all([employee, task])
        _bind_pending_tasks(db)
        db.commit()
        db.refresh(employee)
        db.refresh(task)
        employee_id = employee.id
        task_id = task.id
    finally:
        db.close()

    html = """
    <html>
      <head>
        <title>天采公开信息</title>
        <meta name="description" content="公开网页采集测试">
      </head>
      <body>
        <h1>公开信息标题</h1>
        <p class="summary">这里是公开内容。</p>
        <table><tr><td>字段A</td><td>字段B</td></tr></table>
      </body>
    </html>
    """.strip()

    def fake_fetch_document(**kwargs):
        return FetchedDocument(
            requested_url=kwargs["request_url"],
            final_url="https://news.example.com/article?q=1&token=secret",
            status_code=200,
            content_type="text/html; charset=utf-8",
            body=html.encode("utf-8"),
            headers={"Content-Type": "text/html; charset=utf-8"},
            redirect_chain=[],
            fetched_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
        )

    monkeypatch.setattr("backend.agent_runtime.executors.browser.executor.fetch_document", fake_fetch_document)
    from backend.agent_runtime.executors.browser import policy as browser_policy
    monkeypatch.setattr(browser_policy, "resolve_host_ips", lambda host: ["93.184.216.34"])

    response = client.post(
        "/api/v2/capabilities/browser.public.read/enable",
        headers=owner_headers,
    )
    assert response.status_code == 200

    execution = client.post(
        "/api/v2/executions",
        json={
            "employee_id": employee_id,
            "task_id": task_id,
            "capability_id": "browser.public.read",
            "input_payload": {
                "url": "https://news.example.com/article?q=1&token=secret",
                "allow_redirects": True,
                "method": "GET",
                "timeout_seconds": 10,
                "max_response_bytes": 100000,
                "extract_fields": [
                    {"name": "title", "kind": "title"},
                    {"name": "headline", "selector": "h1"},
                    {"name": "summary", "selector": "meta[name=description]", "attribute": "content"},
                    {"name": "table_cells", "selector": "table td", "multiple": True},
                ],
                "link_task_result": True,
            },
        },
        headers=owner_headers,
    )
    assert execution.status_code == 200, execution.text
    data = execution.json()["execution"]
    assert data["status"] == "success"
    assert data["capability_id"] == "browser.public.read"
    assert data["output_payload"]["page_title"] == "天采公开信息"
    assert data["output_payload"]["structured_fields"]["title"] == "天采公开信息"
    assert data["output_payload"]["structured_fields"]["headline"] == "公开信息标题"
    assert data["output_payload"]["structured_fields"]["summary"] == "公开网页采集测试"
    assert data["output_payload"]["structured_fields"]["table_cells"] == ["字段A", "字段B"]
    assert data["output_payload"]["final_url"] == "https://news.example.com/article?q=1&token=[已脱敏]"
    assert data["output_payload"]["content_hash"]
    assert data["output_payload"]["sources"][0]["url"] == "https://news.example.com/article?q=1&token=[已脱敏]"

    db = _owner_db(test_db)
    try:
        stored_task = db.get(TaskCenterTask, task_id)
        assert stored_task.summary
        assert "公开网页读取" in stored_task.summary
        assert "news.example.com" in stored_task.summary
    finally:
        db.close()

    audit = client.get(f"/api/v2/executions/{data['execution_id']}/audit", headers=owner_headers)
    assert audit.status_code == 200
    audit_items = audit.json()["items"]
    assert any(item["event_type"] == "execution_succeeded" for item in audit_items)
    assert all("secret" not in str(item).lower() for item in audit_items)

    teardown_browser_settings(monkeypatch)


def test_browser_executor_rejects_unwhitelisted_employee(
    client, owner_headers, test_db, monkeypatch, alpha_enabled
):
    from backend.agent_runtime.executors.browser import executor as browser_executor
    from backend.agent_runtime.models import AgentCapability, AgentExecution, AgentExecutionAudit
    from backend.agent_runtime.registry import capability_allowed_employee_codes
    from backend.models import TaskCenterResult

    def rejected_state():
        db = test_db()
        try:
            return (
                db.query(AgentExecution).count(),
                db.query(AgentExecutionAudit).count(),
                db.query(TaskCenterTask).count(),
                db.query(TaskCenterResult).count(),
            )
        finally:
            db.close()

    external_actions = []

    def reject_external_action(**kwargs):
        external_actions.append(kwargs)
        raise AssertionError("employee allowlist denial must precede browser execution")

    monkeypatch.setattr(browser_executor, "fetch_document", reject_external_action)
    enable_browser_readonly(monkeypatch)
    settings = get_settings()
    assert settings.AGENT_RUNTIME_ENABLED is True
    assert settings.BROWSER_READONLY_ENABLED is True
    assert settings.BROWSER_CONTROL_ENABLED is False
    client.cookies.clear()
    db = _owner_db(test_db)
    try:
        employee = AiEmployee(
            employee_code="other_employee",
            employee_name="其他员工",
            legion="研发交付军团",
            duty="无权限测试",
            status="active",
            task_types='["browser"]',
            default_permissions='[]',
            is_legacy=False,
            sort_order=99,
        )
        db.add(employee)
        _bind_pending_tasks(db)
        db.commit()
        db.refresh(employee)
        employee_id = employee.id
        assert db.get(AiEmployee, employee_id) is not None
    finally:
        db.close()

    response = client.post(
        "/api/v2/capabilities/browser.public.read/enable",
        headers=owner_headers,
    )
    assert response.status_code == 200

    db = test_db()
    try:
        capability = db.get(AgentCapability, "browser.public.read")
        assert capability is not None
        assert "other_employee" not in capability_allowed_employee_codes(capability)
    finally:
        db.close()
    before = rejected_state()

    denied = client.post(
        "/api/v2/executions",
        json={
            "employee_id": employee_id,
            "capability_id": "browser.public.read",
            "input_payload": {"url": "https://news.example.com/article"},
        },
        headers=owner_headers,
    )
    assert denied.status_code == 403
    assert denied.json() == {"detail": "当前 AI 员工无权使用该能力"}
    assert rejected_state() == before
    assert external_actions == []
    teardown_browser_settings(monkeypatch)
    restored = get_settings()
    assert restored.AGENT_RUNTIME_ENABLED is True
    assert restored.BROWSER_READONLY_ENABLED is False
    assert restored.BROWSER_CONTROL_ENABLED is False
