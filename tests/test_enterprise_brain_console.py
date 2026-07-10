from pathlib import Path

from backend.deploy_models import DeployRecord
from backend.models import EmployeeLog, TaskCenterAuditLog, TaskCenterTask


API_PATH = "/api/enterprise-brain-console/overview"
PAGE = Path("frontend/enterprise-brain-console.html")


def read_page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_enterprise_brain_console_page_is_served(client):
    response = client.get("/enterprise-brain-console.html")

    assert response.status_code == 200
    assert "天统AI企业大脑" in response.text
    assert "V1只读模式" in response.text


def test_enterprise_brain_console_api_requires_login(client):
    response = client.get(API_PATH)

    assert response.status_code == 401


def test_enterprise_brain_console_api_allows_owner_admin_and_boss(client, owner_headers, admin_headers, boss_headers):
    for headers in [owner_headers, admin_headers, boss_headers]:
        response = client.get(API_PATH, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["readonly"] is True
        assert data["mode"] == "readonly"
        assert data["system"]["current_sprint"] == "Sprint59"
        assert data["system"]["security_mode"] == "readonly"
        assert data["safety"]["auto_execute"] is False
        assert data["safety"]["execution_engine_called"] is False
        assert data["safety"]["openclaw_connected"] is False
        assert data["safety"]["n8n_connected"] is False
        assert "no_real_business_data" in data["empty_state"]


def test_enterprise_brain_console_api_rejects_low_privilege_user(client, viewer_headers):
    response = client.get(API_PATH, headers=viewer_headers)

    assert response.status_code == 403


def test_enterprise_brain_console_api_returns_center_entries(client, owner_headers):
    response = client.get(API_PATH, headers=owner_headers)

    assert response.status_code == 200
    names = {row["name"] for row in response.json()["centers"]}
    assert {
        "AI员工工作台",
        "AI会议室",
        "Task Center",
        "Skill Center",
        "天藏 Knowledge OS",
        "Organization",
        "Audit Center",
        "AI运营驾驶舱",
    } <= names
    for row in response.json()["centers"]:
        assert {"name", "status", "description", "count", "last_updated", "risk_level"} <= set(row)


def test_enterprise_brain_console_api_aggregates_employee_task_health_and_pending_data(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add_all(
            [
                TaskCenterTask(
                    title="Running aggregation task",
                    status="running",
                    priority="high",
                    assigned_ai_employee_code="tianwang",
                    assigned_ai_employee_name="天王：后端开发中心",
                ),
                TaskCenterTask(
                    title="Waiting review task",
                    status="result_submitted",
                    priority="normal",
                    assigned_ai_employee_code="tiantong",
                    assigned_ai_employee_name="天统：AI总指挥",
                ),
                TaskCenterTask(
                    title="Blocked risk task",
                    status="rejected",
                    priority="high",
                    assigned_ai_employee_code="tianwang",
                    assigned_ai_employee_name="天王：后端开发中心",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    employee = data["boss_dashboard"]["employee_summary"]["metrics"]
    task = data["boss_dashboard"]["task_summary"]["metrics"]
    risk = data["boss_dashboard"]["risk_summary"]["metrics"]
    pending = data["boss_dashboard"]["pending_confirmations"]["metrics"]
    health = data["boss_dashboard"]["system_health"]

    assert employee["total_employees"] == 2
    assert employee["working_count"] == 1
    assert employee["risk_employee_count"] == 1
    assert employee["department_distribution"][0]["department"] == "研发交付军团"
    assert task["total_tasks"] == 3
    assert task["running_count"] == 1
    assert task["pending_review_count"] == 1
    assert task["blocked_count"] == 1
    assert risk["blocked_task_count"] == 1
    assert risk["high_risk_requires"] == {"boss_confirm": True, "security_audited": True}
    assert pending["pending_review_tasks"] == 1
    assert pending["risk_items"] == 1
    assert {item["name"] for item in health["items"]} == {"Backend", "Database", "Redis", "Worker", "Deploy"}


def test_enterprise_brain_console_api_returns_dynamic_center_status_and_recent_activities(client, owner_headers, test_db):
    db = test_db()
    try:
        task = TaskCenterTask(title="Audited task", status="created", priority="normal")
        db.add(task)
        db.flush()
        db.add(TaskCenterAuditLog(task_id=task.id, action="task_created", to_status="created", detail="created from test"))
        db.add(EmployeeLog(action="ai_employee_view", detail="employee workspace opened"))
        db.add(DeployRecord(deploy_version="Sprint59", branch="New-Terminal", operator="tiandun", status="running", note="readonly status"))
        db.commit()
    finally:
        db.close()

    response = client.get(API_PATH, headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    centers = {row["name"]: row for row in data["centers"]}
    assert centers["AI员工工作台"]["count"] >= 2
    assert centers["Task Center"]["count"] >= 1
    assert centers["Deploy Center"]["count"] >= 2
    assert centers["Task Center"]["last_updated"]
    sources = {row["source"] for row in data["recent_activities"]}
    assert {"task_audit", "deploy_record", "employee_activity"} <= sources


def test_enterprise_brain_console_page_contains_required_layout():
    html = read_page()

    for text in [
        "顶部状态栏",
        "Boss驾驶舱",
        "八大中心入口",
        "员工概况",
        "任务概况",
        "风险概况",
        "待确认事项",
        "系统健康",
        "Backend / Database / Redis / Worker / Deploy",
        "最近动态",
        "task audit / deploy records / employee activity",
        "V1只读模式",
        "禁止自动执行任务",
        "boss_confirm=true",
        "security_audited=true",
    ]:
        assert text in html


def test_enterprise_brain_console_page_has_required_navigation():
    html = read_page()

    for text in [
        "总控台",
        "AI员工",
        "AI会议室",
        "Task Center",
        "Skill Center",
        "天藏",
        "Organization",
        "Audit Center",
        "AI运营驾驶舱",
        "Deploy Center",
    ]:
        assert text in html


def test_enterprise_brain_console_does_not_expose_execution_or_external_calls():
    html = read_page()
    forbidden = [
        "/api/execution",
        "/api/brain/start",
        "/ai-execution.html",
        "OpenClaw(",
        "n8n.com",
        "立即执行",
        "自动执行按钮",
        "自动调用外部平台",
    ]

    for snippet in forbidden:
        assert snippet not in html


def test_enterprise_brain_console_uses_only_readonly_local_api():
    html = read_page()

    assert "/api/enterprise-brain-console/overview" in html
    assert "fetch('http://" not in html
    assert 'fetch("http://' not in html
    assert "fetch('https://" not in html
    assert 'fetch("https://' not in html
