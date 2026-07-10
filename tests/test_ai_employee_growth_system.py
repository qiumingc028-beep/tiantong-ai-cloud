from pathlib import Path

from backend.models import TaskCenterAuditLog, TaskCenterTask, User


BASE = "/api/ai-employee-growth-system"
ROUTER_FILE = Path("backend/routers/ai_employee_growth_system.py")
SERVICE_FILE = Path("backend/services/ai_employee_growth_system.py")


def test_growth_system_requires_login(client):
    response = client.get(f"{BASE}/overview")

    assert response.status_code == 401


def test_growth_system_permissions(client, owner_headers, admin_headers, boss_headers, viewer_headers, operator_headers):
    for headers in [owner_headers, admin_headers, boss_headers]:
        client.cookies.clear()
        response = client.get(f"{BASE}/overview", headers=headers)
        assert response.status_code == 200

    for headers in [viewer_headers, operator_headers]:
        client.cookies.clear()
        response = client.get(f"{BASE}/overview", headers=headers)
        assert response.status_code == 403


def test_growth_system_overview_returns_readonly_structure(client, owner_headers):
    response = client.get(f"{BASE}/overview", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "readonly"
    assert {"total", "evaluated", "pending_review"} <= set(data["employees"])
    assert {"average_score", "available", "top_growth_employees"} <= set(data["growth"])
    assert {"success_cases", "failure_cases", "pending_candidates"} <= set(data["memory"])
    assert {"events", "high_risk", "waiting_boss_confirm"} <= set(data["audit"])
    assert data["security"]["readonly"] is True
    assert data["security"]["execution_engine_called"] is False
    assert data["security"]["openclaw_connected"] is False
    assert data["security"]["n8n_connected"] is False
    assert data["security"]["auto_learning"] is False
    assert data["security"]["auto_skill_upgrade"] is False
    assert data["security"]["auto_task_execution"] is False


def test_employee_growth_profile_empty_state(client, owner_headers):
    response = client.get(f"{BASE}/employees/tianwang/profile", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "readonly"
    assert data["employee"]["employee_id"] == "tianwang"
    assert data["growth"]["available"] is False
    assert data["growth"]["growth_score"] is None
    assert data["empty_state"]["message"] == "暂无成长数据"


def test_employee_growth_profile_scores_completed_and_rejected_tasks(client, owner_headers):
    completed_id = create_full_task_flow(client, owner_headers)
    rejected_id = create_rejected_task(client, owner_headers)

    response = client.get(f"{BASE}/employees/tianwang/profile", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["growth"]["available"] is True
    assert data["growth"]["growth_score"] is not None
    assert data["tasks"]["total"] >= 2
    assert data["tasks"]["success"] >= 1
    assert data["tasks"]["failure"] >= 1
    assert data["memory"]["success_case_candidates"] >= 1
    assert data["memory"]["failure_case_candidates"] >= 1
    assert data["audit"]["high_risk_count"] >= 1
    assert data["manual_confirm"]["security_audited_required"] is True

    impact_completed = client.get(f"{BASE}/tasks/{completed_id}/impact", headers=owner_headers)
    assert impact_completed.status_code == 200
    assert impact_completed.json()["impact"]["included_in_growth_score"] is True
    assert impact_completed.json()["impact"]["score_delta"] > 0

    impact_rejected = client.get(f"{BASE}/tasks/{rejected_id}/impact", headers=owner_headers)
    assert impact_rejected.status_code == 200
    assert impact_rejected.json()["impact"]["included_in_growth_score"] is True
    assert impact_rejected.json()["impact"]["score_delta"] < 0
    assert impact_rejected.json()["manual_confirm"]["security_audited_required"] is True


def test_waiting_confirm_is_pending_and_not_included_in_growth(client, owner_headers):
    task_id = create_waiting_confirm_task(client, owner_headers)

    waiting = client.get(f"{BASE}/waiting-confirm", headers=owner_headers)

    assert waiting.status_code == 200
    waiting_data = waiting.json()
    assert waiting_data["mode"] == "readonly"
    assert waiting_data["total"] >= 1
    assert waiting_data["manual_confirm"]["boss_confirm_required"] is True
    assert waiting_data["manual_confirm"]["action_available"] is False

    impact = client.get(f"{BASE}/tasks/{task_id}/impact", headers=owner_headers)

    assert impact.status_code == 200
    data = impact.json()
    assert data["impact"]["lifecycle_status"] == "waiting_confirm"
    assert data["impact"]["included_in_growth_score"] is False
    assert data["impact"]["score_delta"] == 0.0
    assert data["manual_confirm"]["boss_confirm_required"] is True


def test_skill_suggestions_are_readonly(client, owner_headers):
    create_rejected_task(client, owner_headers)

    response = client.get(f"{BASE}/employees/tianwang/skill-suggestions", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "readonly"
    assert data["summary"]["total"] >= 1
    assert data["suggestions"]
    assert all(item["action_available"] is False for item in data["suggestions"])
    assert data["security"]["auto_skill_upgrade"] is False


def test_growth_system_task_impact_404(client, owner_headers):
    response = client.get(f"{BASE}/tasks/999999/impact", headers=owner_headers)

    assert response.status_code == 404


def test_growth_system_get_requests_do_not_mutate_task_center(test_db, client, owner_headers):
    task_id = create_waiting_confirm_task(client, owner_headers)
    before = task_center_counts(test_db)

    assert client.get(f"{BASE}/overview", headers=owner_headers).status_code == 200
    assert client.get(f"{BASE}/employees/tianwang/profile", headers=owner_headers).status_code == 200
    assert client.get(f"{BASE}/tasks/{task_id}/impact", headers=owner_headers).status_code == 200
    assert client.get(f"{BASE}/waiting-confirm", headers=owner_headers).status_code == 200
    assert client.get(f"{BASE}/employees/tianwang/skill-suggestions", headers=owner_headers).status_code == 200

    after = task_center_counts(test_db)
    assert after == before


def test_growth_system_static_safety_boundaries():
    combined = ROUTER_FILE.read_text(encoding="utf-8") + SERVICE_FILE.read_text(encoding="utf-8")
    forbidden = [
        "OpenClaw",
        "/api/execution",
        "/api/brain/start",
        "ExecutionEngine",
        "TaskCenterTask(",
        ".add(",
        ".delete(",
        ".commit(",
        "auto_execute",
    ]
    for text in forbidden:
        assert text not in combined


def create_full_task_flow(client, headers):
    task_id = create_waiting_confirm_task(client, headers)
    review = client.post(
        f"/api/task-center/tasks/{task_id}/reviews",
        headers=headers,
        json={"review_status": "accepted", "comment": "Accepted by Boss."},
    )
    assert review.status_code == 200
    audit = client.post(
        f"/api/task-center/tasks/{task_id}/audits",
        headers=headers,
        json={"review_status": "audited", "comment": "Security audit completed."},
    )
    assert audit.status_code == 200
    summary = client.post(
        f"/api/task-center/tasks/{task_id}/summary",
        headers=headers,
        json={"summary": "Task closed after Boss confirmation."},
    )
    assert summary.status_code == 200
    return task_id


def create_rejected_task(client, headers):
    task_id = create_task(client, headers)
    assigned = client.post(
        f"/api/task-center/tasks/{task_id}/assign",
        headers=headers,
        json={"ai_employee_code": "tianwang"},
    )
    assert assigned.status_code == 200
    review = client.post(
        f"/api/task-center/tasks/{task_id}/reviews",
        headers=headers,
        json={"review_status": "rejected", "comment": "Rejected by Boss."},
    )
    assert review.status_code == 200
    return task_id


def create_waiting_confirm_task(client, headers):
    task_id = create_task(client, headers)
    assigned = client.post(
        f"/api/task-center/tasks/{task_id}/assign",
        headers=headers,
        json={"ai_employee_code": "tianwang"},
    )
    assert assigned.status_code == 200
    started = client.post(f"/api/task-center/tasks/{task_id}/start", headers=headers)
    assert started.status_code == 200
    result = client.post(
        f"/api/task-center/tasks/{task_id}/results",
        headers=headers,
        json={"result_content": "AI employee result waiting for Boss confirmation."},
    )
    assert result.status_code == 200
    return task_id


def create_task(client, headers):
    response = client.post(
        "/api/task-center/tasks",
        headers=headers,
        json={"title": "Sprint62.44 growth system test task"},
    )
    assert response.status_code == 200
    return response.json()["task"]["id"]


def task_center_counts(session_factory):
    db = session_factory()
    try:
        return {
            "tasks": db.query(TaskCenterTask).count(),
            "audit_logs": db.query(TaskCenterAuditLog).count(),
            "users": db.query(User).count(),
        }
    finally:
        db.close()
