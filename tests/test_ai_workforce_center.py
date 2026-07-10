from pathlib import Path


PAGE = Path("frontend/ai-workforce-center.html")


def read_page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_ai_workforce_center_page_exists():
    assert PAGE.exists()


def test_ai_workforce_center_page_contains_mvp_sections():
    html = read_page()

    for text in [
        "AI Workforce Center MVP",
        "AI员工工作台第一版页面",
        "员工数量",
        "员工状态",
        "当前任务",
        "健康状态",
        "风险状态",
        "AI员工列表",
        "员工名称",
        "员工介绍",
        "部门",
        "技能数量",
        "技能列表",
        "状态",
        "健康评分",
        "Memory状态",
        "Growth状态",
        "成长状态",
        "审计记录",
        "查看员工详情",
        "搜索AI员工名称",
        "全部部门",
        "全部状态",
        "全部风险",
        "readonly安全模式",
        "ai-employee-detail.html",
        "/api/ai-workforce/overview",
        "/api/ai-employee-health/overview",
    ]:
        assert text in html


def test_ai_workforce_center_page_has_empty_and_error_states():
    html = read_page()

    assert "暂无数据" in html
    assert "当前数据不可用" in html
    assert "emptyWorkforce" in html
    assert "buildEmployeeRows" in html
    assert "employeeHealthScore" in html
    assert "growthStatusFromRisk" in html
    assert "renderDepartmentFilter" in html
    assert "auditRecord" in html


def test_ai_workforce_center_page_does_not_expose_dangerous_entries():
    html = read_page()
    forbidden = [
        "Execution Engine",
        "OpenClaw",
        "n8n",
        "立即执行",
        "自动运行",
        "自动升级",
        "修改权限",
        "安装技能",
        "/api/execution",
        "/ai-execution.html",
    ]

    for text in forbidden:
        assert text not in html


def test_ai_workforce_center_page_is_served(client):
    response = client.get("/ai-workforce-center.html")

    assert response.status_code == 200
    assert "AI Workforce Center MVP" in response.text
