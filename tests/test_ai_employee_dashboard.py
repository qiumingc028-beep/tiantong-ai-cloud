from pathlib import Path


PAGE = Path("frontend/ai-employee-dashboard.html")


def read_page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_ai_employee_dashboard_page_exists():
    assert PAGE.exists()


def test_ai_employee_dashboard_page_is_served(client):
    response = client.get("/ai-employee-dashboard.html")

    assert response.status_code == 200
    assert "AI Employee Dashboard V1" in response.text


def test_ai_employee_dashboard_contains_required_sections():
    html = read_page()

    for text in [
        "AI员工生态驾驶舱",
        "AI员工数量统计",
        "八大生态状态卡",
        "生态健康摘要",
        "最近状态",
        "安全边界",
        "AI员工总数",
        "能力中心",
        "Skill Center",
        "Memory Center",
        "Growth Center",
        "Task Center",
        "readonly安全模式",
    ]:
        assert text in html


def test_ai_employee_dashboard_calls_overview_api_and_handles_states():
    html = read_page()

    for text in [
        "/api/ai-employee-ecosystem/overview",
        "正在加载 AI员工生态 Overview",
        "暂无数据",
        "当前数据不可用",
        "renderError",
        "safeData",
        "execution_engine_called=false",
        "openclaw_connected=false",
        "n8n_connected=false",
    ]:
        assert text in html


def test_ai_employee_dashboard_has_no_dangerous_entries():
    html = read_page()

    forbidden = [
        "Execution Engine",
        "OpenClaw",
        "n8n入口",
        "n8n调用",
        "自动执行",
        "执行任务",
        "立即执行",
        "开始任务",
        "升级员工",
        "授权",
        "修改权限",
        "/api/execution",
        "/api/brain/start",
        "/api/employee-evolution/analyze",
        "method:'POST'",
        'method:"POST"',
    ]
    for text in forbidden:
        assert text not in html
