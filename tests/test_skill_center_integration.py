from pathlib import Path


SKILL_PAGE = Path("frontend/skill-center.html")
WORKFORCE_PAGE = Path("frontend/ai-workforce-center.html")
SKILL_API = "/api/v2/skills"
WORKFORCE_API = "/api/ai-workforce/overview"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_skill_center_integration_pages_exist_and_are_served(client):
    assert SKILL_PAGE.exists()
    assert WORKFORCE_PAGE.exists()

    skill_page = client.get("/skill-center.html")
    workforce_page = client.get("/ai-workforce-center.html")

    assert skill_page.status_code == 200
    assert workforce_page.status_code == 200
    assert "技能中心" in skill_page.text
    assert "AI Workforce Center MVP" in workforce_page.text


def test_skill_center_integration_page_links_workforce_and_skill_api():
    skill_html = read(SKILL_PAGE)
    workforce_html = read(WORKFORCE_PAGE)

    assert "/api/v2/skills" in skill_html
    assert "/api/v2/skills/invocations" in skill_html
    assert "/api/ai-workforce/overview" in workforce_html
    assert "/skill-center.html" in workforce_html or "技能中心" in workforce_html


def test_skill_center_integration_basic_statistics_visible():
    html = read(SKILL_PAGE)

    for text in [
        "技能总数",
        "已安装数量",
        "已启用数量",
        "待审核数量",
        "高风险数量",
        "正在加载技能中心",
        "技能中心已加载，当前为只读管理视图。",
        "暂无数据",
    ]:
        assert text in html


def test_skill_center_integration_api_and_workforce_are_readonly(client, owner_headers, monkeypatch):
    monkeypatch.setattr("backend.skills_engine.permissions.get_flag", lambda name: True)
    skill_response = client.get(SKILL_API, headers=owner_headers)
    workforce_response = client.get(WORKFORCE_API, headers=owner_headers)

    assert skill_response.status_code == 200
    assert workforce_response.status_code == 200

    skill_data = skill_response.json()
    workforce_data = workforce_response.json()

    assert skill_data["readonly"] is True
    assert workforce_data["mode"] == "readonly"
    assert skill_data["summary"]["total"] >= 2
    assert workforce_data["security"]["execution_engine_called"] is False
    assert workforce_data["security"]["openclaw_connected"] is False
    assert workforce_data["security"]["n8n_connected"] is False


def test_skill_center_integration_skill_detail_api(client, owner_headers, monkeypatch):
    monkeypatch.setattr("backend.skills_engine.permissions.get_flag", lambda name: True)
    list_response = client.get(SKILL_API, headers=owner_headers)
    assert list_response.status_code == 200
    skills = list_response.json()["skills"]
    assert skills

    skill_id = skills[0]["skill_id"]
    detail = client.get(f"{SKILL_API}/{skill_id}", headers=owner_headers)

    assert detail.status_code == 200
    data = detail.json()
    assert data["readonly"] is True
    assert data["skill"]["skill_id"] == skill_id
    assert data["versions"]


def test_skill_center_integration_no_dangerous_entries():
    combined = read(SKILL_PAGE) + read(WORKFORCE_PAGE)
    forbidden = [
        "Execution Engine",
        "OpenClaw",
        "n8n",
        "自动安装技能",
        "自动升级技能",
        "立即执行",
        "/api/execution",
        "/ai-execution.html",
    ]

    for text in forbidden:
        assert text not in combined
