from pathlib import Path


PAGE = Path("frontend/ai-employee-health.html")


def read_page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_ai_employee_health_page_exists():
    assert PAGE.exists()


def test_ai_employee_health_page_is_served(client):
    response = client.get("/ai-employee-health.html")

    assert response.status_code == 200
    assert "AI Employee Health Center" in response.text


def test_ai_employee_health_page_contains_required_sections():
    html = read_page()

    for text in [
        "AI Employee Health Center",
        "AI员工生态健康监控",
        "健康总评分",
        "AI员工数量状态",
        "模块健康地图",
        "API健康状态",
        "数据更新时间",
        "异常记录",
        "风险等级展示",
        "AI Workforce",
        "Skill Center",
        "Memory Center",
        "Growth Center",
        "Audit Center",
        "Task Center",
        "readonly安全模式",
    ]:
        assert text in html


def test_ai_employee_health_page_calls_health_api_and_handles_states():
    html = read_page()

    for text in [
        "/api/ai-employee-health/overview",
        "正在读取 AI Employee Health Overview",
        "暂无数据",
        "当前数据暂不可用",
        "暂无模块健康数据",
        "暂无 API 健康数据",
        "暂无更新时间数据",
        "暂无异常记录",
        "renderError",
        "safeData",
        "execution_engine_called=false",
        "openclaw_connected=false",
        "n8n_connected=false",
        "auto_repair_enabled=false",
        "auto_execute_enabled=false",
    ]:
        assert text in html


def test_ai_employee_health_page_has_no_dangerous_entries():
    html = read_page()

    forbidden = [
        "Execution Engine",
        "OpenClaw",
        "n8n入口",
        "n8n调用",
        "自动修复",
        "自动重启",
        "自动执行",
        "执行任务",
        "立即执行",
        "开始任务",
        "修改权限",
        "授权",
        "/api/execution",
        "/api/brain/start",
        "/api/employee-evolution/analyze",
        "method:'POST'",
        'method:"POST"',
        "<button",
    ]
    for text in forbidden:
        assert text not in html
