from __future__ import annotations

from pathlib import Path


PAGE = Path("frontend/brain-orchestrator.html")


def test_brain_orchestrator_page_exists_and_loads(client):
    assert PAGE.is_file()
    response = client.get("/brain-orchestrator.html")
    assert response.status_code == 200
    assert "Brain Center × Orchestrator" in response.text
    assert "任务输入区" in response.text
    assert "Task Graph 可视化" in response.text
    assert "AI员工推荐区域" in response.text
    assert "Tool Router 展示" in response.text
    assert "审批中心" in response.text


def test_brain_orchestrator_page_uses_only_dry_run_orchestrator_apis():
    source = PAGE.read_text()
    assert "/api/orchestrator/analyze" in source
    assert "/api/orchestrator/plan" in source
    assert "/api/orchestrator/tasks/" in source
    assert "/api/orchestrator/logs" in source
    assert "/api/tools/call" not in source
    assert "/api/tool-router/route" not in source
    assert "PATCH" not in source
    assert "PUT" not in source
    assert "DELETE" not in source


def test_brain_orchestrator_page_has_graph_nodes_and_risk_states():
    source = PAGE.read_text()
    for text in ["pending", "running", "approved", "blocked", "completed", "dry-run"]:
        assert text in source
    for text in ["任务节点", "AI员工", "工具节点", "审批节点", "执行状态"]:
        assert text in source
    for text in ["低风险", "中风险", "高风险"]:
        assert text in source


def test_brain_orchestrator_page_has_no_sensitive_terms_or_external_automation():
    source = PAGE.read_text()
    for word in ["password_hash", "token", "secret", "API Key", "Bearer", "Authorization", "private_key"]:
        assert word not in source
    forbidden = [
        "window.open",
        "<iframe",
        "WebSocket",
        "EventSource",
        "sendBeacon",
        "Playwright",
        "Puppeteer",
        "Selenium",
        "fetch('http://",
        'fetch("http://',
        "fetch('https://",
        'fetch("https://',
    ]
    for needle in forbidden:
        assert needle not in source


def test_index_menu_contains_brain_orchestrator_entry():
    source = Path("frontend/rbac-navigation.js").read_text()
    assert "Brain Orchestrator" in source
    assert "/brain-orchestrator.html" in source
