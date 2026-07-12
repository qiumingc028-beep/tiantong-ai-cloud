from pathlib import Path


PAGE = Path("frontend/skill-center.html")


def read_page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_skill_center_frontend_page_exists():
    assert PAGE.exists()


def test_skill_center_frontend_contains_employee_skill_fields():
    html = read_page()

    for text in [
        "统一 Skills Engine",
        "技能总数",
        "已安装数量",
        "已启用数量",
        "待审核数量",
        "高风险数量",
        "技能列表",
        "执行记录",
        "查看详情",
        "默认只读展示",
        "暂无数据",
        "技能中心已加载，当前为只读管理视图。",
    ]:
        assert text in html


def test_skill_center_frontend_uses_ai_employee_skill_apis():
    html = read_page()

    assert "/api/v2/skills" in html
    assert "/api/v2/skills/invocations" in html
    assert "renderSkills" in html
    assert "renderInvocations" in html


def test_skill_center_frontend_does_not_expose_dangerous_entries():
    html = read_page()
    forbidden = [
        "Execution Engine",
        "OpenClaw",
        "n8n",
        "自动安装技能",
        "自动升级技能",
        "修改权限",
        "立即执行",
        "/api/execution",
        "/ai-execution.html",
        "shell_execute",
    ]

    for text in forbidden:
        assert text not in html


def test_skill_center_frontend_page_is_served(client):
    response = client.get("/skill-center.html")

    assert response.status_code == 200
    assert "技能中心" in response.text
