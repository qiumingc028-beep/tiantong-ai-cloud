from __future__ import annotations

from pathlib import Path


PAGE = Path("frontend/brain-center.html")


def test_brain_center_page_exists_and_loads(client):
    assert PAGE.is_file()
    response = client.get("/brain-center.html")
    assert response.status_code == 200
    assert "天统AI Brain Center" in response.text
    assert "任务输入区" in response.text
    assert "执行计划展示" in response.text
    assert "审批区域" in response.text
    assert "日志区域" in response.text


def test_brain_center_page_uses_only_brain_tool_router_simulation_apis():
    source = PAGE.read_text()
    assert "/api/brain-tool-router/analyze" in source
    assert "/api/brain-tool-router/plan" in source
    assert "/api/brain-tool-router/approval-check" in source
    assert "/api/brain-tool-router/logs" in source
    assert "/api/tools/call" not in source
    assert "/api/tool-router/route" not in source
    assert "PATCH" not in source
    assert "PUT" not in source
    assert "DELETE" not in source


def test_brain_center_page_has_no_sensitive_terms_or_external_automation():
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


def test_index_menu_contains_brain_center_entry():
    source = Path("frontend/index.html").read_text()
    assert "天统AI Brain Center" in source
    assert "/brain-center.html" in source

