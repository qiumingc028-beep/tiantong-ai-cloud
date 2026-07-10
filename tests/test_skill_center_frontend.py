from pathlib import Path


PAGE = Path("frontend/skill-center.html")


def read_page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_skill_center_frontend_page_exists():
    assert PAGE.exists()


def test_skill_center_frontend_contains_employee_skill_fields():
    html = read_page()

    for text in [
        "AI员工技能资产管理中心",
        "技能名称",
        "所属AI员工",
        "技能版本",
        "使用次数",
        "成功率",
        "风险等级",
        "更新时间",
        "查看详情",
        "技能详情",
        "readonly安全模式",
        "暂无数据",
        "当前数据暂不可用",
    ]:
        assert text in html


def test_skill_center_frontend_uses_ai_employee_skill_apis():
    html = read_page()

    assert "/api/ai-employee-skills/skills" in html
    assert "/api/ai-employee-skills/skills/" in html
    assert "loadSkillDetail" in html
    assert "successRateText" in html


def test_skill_center_frontend_does_not_expose_dangerous_entries():
    html = read_page()
    forbidden = [
        "Execution Engine",
        "OpenClaw",
        "n8n",
        "自动调用技能",
        "自动安装技能",
        "自动升级技能",
        "调用技能",
        "安装技能",
        "升级技能",
        "修改权限",
        "立即执行",
        "/api/execution",
        "/ai-execution.html",
    ]

    for text in forbidden:
        assert text not in html


def test_skill_center_frontend_page_is_served(client):
    response = client.get("/skill-center.html")

    assert response.status_code == 200
    assert "Skill Center V1" in response.text
