from pathlib import Path


CENTER_PAGE = Path("frontend/skill-center.html")
DETAIL_PAGE = Path("frontend/skill-detail.html")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_skill_center_pages_exist():
    assert CENTER_PAGE.exists()
    assert DETAIL_PAGE.exists()


def test_skill_center_pages_are_served(client):
    center = client.get("/skill-center.html")
    detail = client.get("/skill-detail.html")

    assert center.status_code == 200
    assert detail.status_code == 200
    assert "Skill Center V1" in center.text
    assert "技能详情" in detail.text


def test_skill_center_home_contains_required_readonly_sections():
    html = read(CENTER_PAGE)

    for text in [
        "技能总数量",
        "技能分类",
        "技能状态",
        "风险等级",
        "使用员工数量",
        "审核状态",
        "技能列表",
        "查看详情",
        "暂无数据",
        "readonly安全模式",
        "boss_confirm=true",
        "security_audited=true",
        "/api/sop-skill-center/skills",
        "/api/skill-plugin-center/skills",
        "/api/sop-skill-center/overview",
        "/api/sop-skill-center/employees",
    ]:
        assert text in html


def test_skill_detail_contains_required_readonly_sections():
    html = read(DETAIL_PAGE)

    for text in [
        "技能名称",
        "版本",
        "描述",
        "输入输出",
        "输入要求",
        "输出格式",
        "适用员工",
        "风险等级",
        "审核记录",
        "使用记录",
        "暂无数据",
        "readonly安全模式",
        "boss_confirm=true",
        "security_audited=true",
        "/api/sop-skill-center/skills/",
        "/api/skill-plugin-center/skills/",
    ]:
        assert text in html


def test_skill_center_pages_have_no_dangerous_entries():
    html = read(CENTER_PAGE) + read(DETAIL_PAGE)
    forbidden = [
        "Execution Engine",
        "OpenClaw",
        "n8n",
        "自动安装技能",
        "自动升级技能",
        "自动执行技能",
        "安装技能",
        "升级技能",
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


def test_skill_center_pages_use_safe_empty_state():
    html = read(CENTER_PAGE) + read(DETAIL_PAGE)

    assert "当前数据暂不可用" in html
    assert "renderEmpty" in html
    assert "safe_empty" in html
