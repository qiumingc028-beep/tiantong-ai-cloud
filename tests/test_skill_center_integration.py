from pathlib import Path


SKILL_PAGE = Path("frontend/skill-center.html")
WORKFORCE_PAGE = Path("frontend/ai-workforce-center.html")
SKILL_API = "/api/ai-employee-skills/skills"
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
    assert "Skill Center V1" in skill_page.text
    assert "AI Workforce Center MVP" in workforce_page.text


def test_skill_center_integration_page_links_workforce_and_skill_api():
    skill_html = read(SKILL_PAGE)
    workforce_html = read(WORKFORCE_PAGE)

    assert "/api/ai-employee-skills/skills" in skill_html
    assert "/api/ai-employee-skills/skills/" in skill_html
    assert "/api/ai-workforce/overview" in workforce_html
    assert "/skill-center.html" in workforce_html or "Skill Center" in workforce_html


def test_skill_center_integration_basic_statistics_visible():
    html = read(SKILL_PAGE)

    for text in [
        "技能总数量",
        "员工技能数量",
        "平均成功率",
        "高风险技能数量",
        "正在加载 Skill Center",
        "当前数据暂不可用",
        "暂无数据",
    ]:
        assert text in html


def test_skill_center_integration_api_and_workforce_are_readonly(client, owner_headers):
    skill_response = client.get(SKILL_API, headers=owner_headers)
    workforce_response = client.get(WORKFORCE_API, headers=owner_headers)

    assert skill_response.status_code == 200
    assert workforce_response.status_code == 200

    skill_data = skill_response.json()
    workforce_data = workforce_response.json()

    assert skill_data["mode"] == "readonly"
    assert workforce_data["mode"] == "readonly"
    assert skill_data["security"]["readonly"] is True
    assert skill_data["security"]["auto_skill_call_enabled"] is False
    assert skill_data["security"]["execution_engine_called"] is False
    assert skill_data["security"]["openclaw_connected"] is False
    assert skill_data["security"]["n8n_connected"] is False
    assert workforce_data["security"]["execution_engine_called"] is False
    assert workforce_data["security"]["openclaw_connected"] is False
    assert workforce_data["security"]["n8n_connected"] is False


def test_skill_center_integration_skill_detail_api(client, owner_headers):
    list_response = client.get(SKILL_API, headers=owner_headers)
    assert list_response.status_code == 200
    skills = list_response.json()["skills"]
    assert skills

    skill_id = skills[0]["skill_id"]
    detail = client.get(f"{SKILL_API}/{skill_id}", headers=owner_headers)

    assert detail.status_code == 200
    data = detail.json()
    assert data["mode"] == "readonly"
    assert data["skill"]["skill_id"] == skill_id
    assert data["security"]["auto_skill_call_enabled"] is False


def test_skill_center_integration_no_dangerous_entries():
    combined = read(SKILL_PAGE) + read(WORKFORCE_PAGE)
    forbidden = [
        "Execution Engine",
        "OpenClaw",
        "n8n",
        "自动调用技能",
        "自动安装技能",
        "自动升级技能",
        "立即执行",
        "/api/execution",
        "/ai-execution.html",
    ]

    for text in forbidden:
        assert text not in combined
