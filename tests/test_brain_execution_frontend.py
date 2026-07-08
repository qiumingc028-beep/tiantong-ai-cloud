from __future__ import annotations

from pathlib import Path


PAGE = Path("frontend/ai-execution.html")


def test_brain_execution_page_exists_and_loads(client):
    assert PAGE.is_file()
    response = client.get("/ai-execution.html")
    assert response.status_code == 200
    assert "天统AI Brain Execution Center" in response.text
    assert "目标输入区" in response.text
    assert "Brain分析结果" in response.text or "Brain 分析结果" in response.text
    assert "Task Graph 可视化" in response.text
    assert "审批中心" in response.text
    assert "Dry-run 执行" in response.text
    assert "执行日志" in response.text


def test_brain_execution_page_uses_only_brain_execution_apis():
    source = PAGE.read_text()
    for path in [
        "/api/brain/analyze",
        "/api/brain/plan",
        "/api/brain/approve",
        "/api/brain/start",
        "/api/brain/logs",
    ]:
        assert path in source
    assert "/api/tasks" not in source
    assert "/api/results" not in source
    assert "/api/tools/call" not in source
    assert "/api/tool-router/route" not in source
    assert "PATCH" not in source
    assert "PUT" not in source
    assert "DELETE" not in source


def test_brain_execution_page_has_required_modules_and_dry_run_language():
    source = PAGE.read_text()
    for text in [
        "任务规划展示中心",
        "审批中心",
        "执行日志查看中心",
        "Task Graph",
        "员工节点",
        "工具节点",
        "风险",
        "simulation",
        "dry-run",
    ]:
        assert text in source


def test_brain_execution_page_has_no_sensitive_terms_or_external_automation():
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


def test_brain_execution_page_has_no_real_execution_buttons():
    source = PAGE.read_text()
    forbidden_buttons = [
        ">Shell执行<",
        ">外部API调用<",
        ">安装Skill<",
        ">修改Prompt<",
        ">修改代码<",
    ]
    for needle in forbidden_buttons:
        assert needle not in source
    assert "启动 dry-run" in source
