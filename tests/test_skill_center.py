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
    assert "技能中心" in center.text
    assert "技能详情" in detail.text


def test_skill_center_home_contains_required_readonly_sections():
    html = read(CENTER_PAGE)

    for text in [
        "技能总数",
        "已安装数量",
        "已启用数量",
        "待审核数量",
        "高风险数量",
        "技能列表",
        "查看详情",
        "暂无数据",
        "默认只读展示",
        "/api/v2/skills",
        "/api/v2/skills/invocations",
    ]:
        assert text in html


def test_skill_detail_contains_required_readonly_sections():
    html = read(DETAIL_PAGE)

    for text in [
        "基础信息",
        "当前版本",
        "授权记录",
        "安装记录",
        "调用记录",
        "审计记录",
        "暂无数据",
        "只读查看",
        "技能不能绕过 Agent Runtime",
        "/api/v2/skills/code/",
        "/api/v2/skills/invocations",
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

    assert "技能中心已加载，当前为只读管理视图。" in html
    assert "renderSkills" in html
    assert "renderInvocations" in html
