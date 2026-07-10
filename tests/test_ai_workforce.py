from pathlib import Path

from backend.evolution_models import RiskEvent
from backend.models import AiEmployee, KnowledgeArticle, PromptLibrary, SopLibrary, TaskCenterTask


PAGE = Path("frontend/ai-workforce.html")
API_PATH = "/api/ai-workforce/overview"


def read_page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_ai_workforce_page_file_exists():
    assert PAGE.exists()


def test_ai_workforce_page_contains_required_title():
    html = read_page()

    assert "AI员工中心" in html
    assert "你的AI员工正在帮你工作" in html


def test_ai_workforce_page_contains_required_readonly_sections():
    html = read_page()

    for text in [
        "readonly=true",
        "boss_confirm=true",
        "security_audited=true",
        "AI公司状态",
        "AI员工列表",
        "点卡片看详情",
        "现在看不到数据，请稍后再看。",
        "暂无数据",
        "AI员工",
        "正在工作",
        "负责",
        "看详情",
        "只看不操作",
        "老板确认",
        "/api/ai-workforce/overview",
        "/api/ai-employee-growth/overview",
        "renderCompany",
        "renderEmployees",
    ]:
        assert text in html


def test_ai_workforce_page_does_not_expose_dangerous_entries():
    html = read_page()
    forbidden = [
        "Execution Engine",
        "OpenClaw",
        "n8n",
        "employee_id",
        "数据库字段",
        "API字段",
        "状态码",
        "技术字段",
        "task lifecycle",
        "growth evaluation",
        "<button",
        "<table",
        "method:'POST'",
        'method:"POST"',
        "自动执行按钮",
        "立即执行",
        "自动运行",
        "自动升级按钮",
        "修改权限按钮",
        "/api/execution",
        "/api/brain/start",
        "/ai-execution.html",
    ]

    for text in forbidden:
        assert text not in html


def test_ai_workforce_api_requires_login(client):
    response = client.get(API_PATH)

    assert response.status_code == 401


def test_ai_workforce_api_rejects_viewer(client, viewer_headers):
    response = client.get(API_PATH, headers=viewer_headers)

    assert response.status_code == 403


def test_ai_workforce_api_returns_readonly_structure(client, owner_headers):
    response = client.get(API_PATH, headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "readonly"
    assert {"total", "working", "idle", "frozen"} <= set(data["employees"])
    assert isinstance(data["departments"], list)
    assert "total" in data["skills"]
    assert isinstance(data["employee_cards"], list)
    assert data["employee_cards"]
    assert {
        "employee_name",
        "employee_code",
        "department",
        "department_group",
        "role",
        "status",
        "skill_count",
        "current_task",
        "current_task_count",
        "risk_level",
        "requires_review",
        "detail_url",
    } <= set(data["employee_cards"][0])
    assert {"articles", "sop", "prompt"} <= set(data["knowledge"])
    assert {"total", "running", "pending", "blocked"} <= set(data["tasks"])
    assert "available" in data["growth"]
    assert "risk_count" in data["audit"]
    assert data["security"] == {
        "readonly": True,
        "execution_engine_called": False,
        "openclaw_connected": False,
        "n8n_connected": False,
    }


def test_ai_workforce_api_aggregates_existing_readonly_data(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add_all(
            [
                TaskCenterTask(
                    title="running task",
                    status="running",
                    assigned_ai_employee_code="tianwang",
                    assigned_ai_employee_name="天王：后端开发中心",
                ),
                TaskCenterTask(title="pending task", status="created"),
                TaskCenterTask(title="blocked task", status="failed"),
                KnowledgeArticle(title="Article", content="body"),
                SopLibrary(title="SOP"),
                PromptLibrary(title="Prompt"),
                RiskEvent(employee_code="tianwang", event_type="blocked", risk_level="high"),
                AiEmployee(
                    employee_code="tiance_strategy",
                    employee_name="天策：战略中心",
                    legion="战略部门",
                    duty="战略分析",
                    status="inactive",
                    task_types='["strategy"]',
                    default_permissions="[]",
                    is_legacy=False,
                    sort_order=40,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["employees"]["total"] == 3
    assert data["employees"]["working"] == 1
    assert data["employees"]["idle"] == 1
    assert data["employees"]["frozen"] == 1
    assert data["departments"] == [
        {"name": "战略部门", "employee_count": 1},
        {"name": "研发交付军团", "employee_count": 2},
    ]
    assert data["skills"]["total"] == 4
    assert data["knowledge"]["articles"] == 1
    assert data["knowledge"]["sop"] == 1
    assert data["knowledge"]["prompt"] == 1
    assert data["tasks"]["total"] == 3
    assert data["tasks"]["running"] == 1
    assert data["tasks"]["pending"] == 1
    assert data["tasks"]["blocked"] == 1
    assert data["audit"]["risk_count"] == 2
    cards = {row["employee_code"]: row for row in data["employee_cards"]}
    assert cards["tianwang"]["status"] == "working"
    assert cards["tianwang"]["current_task"] == "running task"
    assert cards["tianwang"]["risk_level"] == "high"
    assert cards["tianwang"]["requires_review"] is True
    assert cards["tianwang"]["detail_url"] == "/ai-employee-detail.html?code=tianwang"
    assert cards["tiantong"]["status"] == "idle"
    assert cards["tiance_strategy"]["status"] == "frozen"
    assert cards["tiance_strategy"]["department_group"] == "战略部门"


def test_ai_workforce_api_handles_empty_employee_fields(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add(
            AiEmployee(
                employee_code="unknown_profile",
                employee_name="",
                legion=None,
                duty=None,
                status="unknown",
                task_types=None,
                default_permissions=None,
                is_legacy=False,
                sort_order=80,
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers)

    assert response.status_code == 200
    cards = {row["employee_code"]: row for row in response.json()["employee_cards"]}
    row = cards["unknown_profile"]
    assert row["employee_name"] == "未命名AI员工"
    assert row["department"] == "未分配部门"
    assert row["status"] == "offline"
    assert row["skill_count"] == 0
    assert row["risk_level"] == "low"


def test_ai_workforce_page_is_served(client):
    response = client.get("/ai-workforce.html")

    assert response.status_code == 200
    assert "AI员工中心" in response.text
