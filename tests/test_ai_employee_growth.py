from pathlib import Path


PAGE = Path("frontend/ai-employee-growth.html")


def read_page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_ai_employee_growth_page_file_exists():
    assert PAGE.exists()


def test_ai_employee_growth_page_contains_required_sections():
    html = read_page()

    for text in [
        "AI Employee Growth Center",
        "AI员工成长中心",
        "成长总览",
        "成长等级",
        "技能成长趋势",
        "能力变化",
        "最近成长记录",
        "成长记录",
        "SkillProgress",
        "PerformanceRecord",
        "GrowthEvent",
        "PromotionSuggestion",
        "AI员工成长排名",
        "安全边界",
        "readonly安全模式",
        "暂无成长数据",
    ]:
        assert text in html


def test_ai_employee_growth_page_uses_existing_readonly_apis():
    html = read_page()

    for text in [
        "/api/employee-evolution/growth",
        "/api/employee-evolution/risk-events",
        "/api/ai-workforce/overview",
    ]:
        assert text in html

    forbidden_api = [
        "/api/employee-evolution/analyze",
        "method:'POST'",
        'method:"POST"',
    ]
    for text in forbidden_api:
        assert text not in html


def test_ai_employee_growth_page_has_safe_empty_state():
    html = read_page()

    for text in [
        "当前成长数据暂不可用",
        "renderSafeEmpty",
        "暂无成长数据",
    ]:
        assert text in html


def test_ai_employee_growth_page_has_no_dangerous_entries():
    html = read_page()

    forbidden = [
        "Execution Engine",
        "OpenClaw",
        "n8n",
        "自动升级员工",
        "自动修改技能",
        "自动调整权限",
        "自动执行任务",
        "升级员工按钮",
        "修改技能按钮",
        "调整权限按钮",
        "执行任务按钮",
        "开始任务",
        "立即执行",
        "修改权限",
        "/api/execution",
        "/api/brain/start",
        "/ai-execution.html",
    ]
    for text in forbidden:
        assert text not in html
