from pathlib import Path


PAGE = Path("frontend/ai-employee-capability.html")


def read_page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_ai_employee_capability_page_file_exists():
    assert PAGE.exists()


def test_ai_employee_capability_page_is_served(client):
    response = client.get("/ai-employee-capability.html")

    assert response.status_code == 200
    assert "AI员工能力中心" in response.text


def test_ai_employee_capability_page_contains_readonly_sections():
    html = read_page()

    for text in [
        "AI员工能力中心 Skill + Knowledge",
        "技能数量",
        "已启用技能",
        "审核状态",
        "风险等级",
        "技能展示",
        "Skill名称",
        "版本",
        "状态",
        "描述",
        "使用范围",
        "风险等级",
        "审核状态",
        "Knowledge关联",
        "Skill关联",
        "SOP",
        "Prompt",
        "知识库",
        "SOP数量",
        "Prompt数量",
        "案例数量",
        "知识更新时间",
        "能力关系展示",
        "AI员工",
        "Skill Center",
        "Knowledge OS",
        "Memory",
        "Growth",
        "Audit",
        "使用记录",
        "能力评分",
        "安全边界",
        "暂无数据",
        "readonly安全模式",
        "boss_confirm=true",
        "security_audited=true",
    ]:
        assert text in html


def test_ai_employee_capability_page_uses_existing_readonly_apis():
    html = read_page()

    for text in [
        "/api/employee-capabilities/overview",
        "/api/sop-skill-center/skills",
        "/api/sop-skill-center/overview",
        "/api/sop-skill-center/sops",
        "/api/sop-skill-center/prompts",
        "/api/tiancang/bugs",
        "/api/tiancang/articles/search",
    ]:
        assert text in html


def test_ai_employee_capability_page_has_no_dangerous_entries():
    html = read_page()

    forbidden = [
        "Execution Engine",
        "OpenClaw",
        "n8n",
        "自动安装技能",
        "自动升级技能",
        "自动调用技能",
        "安装技能",
        "升级技能",
        "调用技能",
        "执行技能",
        "修改权限",
        "权限修改",
        "立即执行",
        "开始任务",
        "/api/execution",
        "/api/brain/start",
        "/ai-execution.html",
    ]
    for text in forbidden:
        assert text not in html


def test_ai_employee_capability_page_empty_state_is_safe():
    html = read_page()

    assert "当前数据暂不可用" in html
    assert "安全空状态" in html
    assert "renderSafeEmpty" in html
