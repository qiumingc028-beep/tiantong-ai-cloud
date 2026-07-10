from pathlib import Path


PAGE = Path("frontend/ai-employee-growth-system.html")


def read_page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_ai_employee_growth_system_page_exists():
    assert PAGE.exists()


def test_ai_employee_growth_system_page_is_served(client):
    response = client.get("/ai-employee-growth-system.html")

    assert response.status_code == 200
    assert "AI员工成长系统" in response.text


def test_ai_employee_growth_system_page_contains_required_sections():
    html = read_page()

    for text in [
        "AI员工成长系统",
        "AI员工成长总览",
        "AI员工正常运行",
        "员工卡片",
        "员工详情",
        "做了什么",
        "学会什么",
        "成长哪里",
        "最近成长记录",
        "只读安全模式",
        "Boss人工确认",
        "安全审计保留",
    ]:
        assert text in html


def test_ai_employee_growth_system_page_calls_readonly_apis_and_handles_states():
    html = read_page()

    for text in [
        "/api/ai-employee-growth/overview",
        "/api/ai-employee-growth/employees/",
        "/timeline",
        "正在加载成长数据",
        "暂无成长数据",
        "当前数据暂不可用",
        "暂无成长记录",
        "renderError",
        "safeOverview",
        "safeEmployee",
        "execution_engine_called:false",
        "openclaw_connected:false",
        "n8n_connected:false",
        "auto_task_execution:false",
        "auto_learning:false",
        "auto_skill_upgrade:false",
        "auto_permission_change:false",
    ]:
        assert text in html


def test_ai_employee_growth_system_page_has_no_mutation_or_execution_entries():
    html = read_page()

    forbidden = [
        "<button",
        "method:'POST'",
        'method:"POST"',
        "fetch('/api/task-center",
        'fetch("/api/task-center',
        "/api/execution",
        "/api/brain/start",
        "/api/employee-evolution/analyze",
        "Execution Engine",
        "OpenClaw",
        "n8n入口",
        "n8n调用",
        "立即执行",
        "开始任务",
        "确认并执行",
        "升级技能",
        "修改权限",
        "授权",
    ]
    for text in forbidden:
        assert text not in html
