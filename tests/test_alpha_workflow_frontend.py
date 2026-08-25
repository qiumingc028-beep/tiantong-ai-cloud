from pathlib import Path


PAGE = Path("frontend/alpha-workflow.html")


def read_page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_alpha_workflow_frontend_page_exists():
    assert PAGE.exists()


def test_alpha_workflow_frontend_contains_required_copy():
    html = read_page()

    for text in [
        "Alpha Workflow",
        "研究 Apple 最新 AI 战略",
        "Task → Research → Knowledge → Skills → Workflow → Dashboard",
        "全链路状态追踪",
        "全链路审计",
        "全链路失败恢复",
        "全链路质量评分",
        "老板驾驶舱展示结果",
        "查看详情",
        "只读展示",
    ]:
        assert text in html


def test_alpha_workflow_frontend_uses_alpha_workflow_apis():
    html = read_page()

    assert "/api/v2/alpha-workflows/health" in html
    assert "/api/v2/alpha-workflows/scenarios" in html
    assert "/api/v2/alpha-workflows/demo" in html
    assert "/api/v2/alpha-workflows/runs/" in html
    assert "renderScenarios" in html
    assert "renderRuns" in html


def test_alpha_workflow_frontend_does_not_expose_dangerous_entries():
    html = read_page()
    forbidden = [
        "OpenClaw",
        "n8n",
        "shell_execute",
        "自动执行全部步骤",
        "生产环境",
        "/api/execution",
        "Command",
        "Terminal",
        "clipboard",
    ]

    for text in forbidden:
        assert text not in html


def test_alpha_workflow_frontend_page_is_served(client):
    response = client.get("/alpha-workflow.html")

    assert response.status_code == 200
    assert "Alpha Workflow" in response.text
