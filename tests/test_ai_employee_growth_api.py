from pathlib import Path

from backend.models import AiEmployee, TaskCenterAuditLog, TaskCenterResult, TaskCenterReview, TaskCenterTask, User


BASE = "/api/ai-employee-growth"
ROUTER_FILE = Path("backend/routers/ai_employee_growth.py")
SERVICE_FILE = Path("backend/services/ai_employee_growth.py")


def test_ai_employee_growth_requires_login(client):
    response = client.get(f"{BASE}/overview")

    assert response.status_code == 401


def test_ai_employee_growth_permissions(client, owner_headers, admin_headers, boss_headers, viewer_headers, operator_headers):
    for headers in [owner_headers, admin_headers, boss_headers]:
        client.cookies.clear()
        response = client.get(f"{BASE}/overview", headers=headers)
        assert response.status_code == 200

    for headers in [viewer_headers, operator_headers]:
        client.cookies.clear()
        response = client.get(f"{BASE}/overview", headers=headers)
        assert response.status_code == 403


def test_ai_employee_growth_overview_returns_required_structure(client, owner_headers):
    response = client.get(f"{BASE}/overview", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "readonly"
    assert {"total", "active", "evaluated", "pending_review"} <= set(data["employees"])
    assert {"score", "status", "available"} <= set(data["average_growth"])
    assert {"total", "completed", "failed", "waiting_confirm", "completion_rate"} <= set(data["tasks"])
    assert {"total", "employee_skill_count", "high_risk", "average_success_rate"} <= set(data["skills"])
    assert {"high", "medium", "waiting_boss_confirm", "boss_confirm", "security_audited"} <= set(data["risk"])
    assert_security(data["security"])


def test_ai_employee_growth_overview_empty_data(test_db, client, owner_headers):
    db = test_db()
    try:
        db.query(TaskCenterAuditLog).delete()
        db.query(TaskCenterReview).delete()
        db.query(TaskCenterResult).delete()
        db.query(TaskCenterTask).delete()
        db.query(AiEmployee).delete()
        db.commit()
    finally:
        db.close()

    response = client.get(f"{BASE}/overview", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "readonly"
    assert data["employees"]["total"] == 0
    assert data["employees"]["active"] == 0
    assert data["average_growth"]["available"] is False
    assert data["average_growth"]["status"] == "no_data"
    assert data["tasks"]["total"] == 0
    assert data["skills"]["total"] >= 0
    assert data["risk"]["waiting_boss_confirm"] == 0
    assert data["empty_state"]["message"] == "暂无成长数据"
    assert_security(data["security"])


def test_ai_employee_growth_employee_empty_state(client, owner_headers):
    response = client.get(f"{BASE}/employees/tianwang", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "readonly"
    assert data["employee"]["employee_id"] == "tianwang"
    assert data["growth_summary"]["available"] is False
    assert data["empty_state"]["message"] == "暂无成长数据"
    assert data["recent_timeline"] == []
    assert_security(data["security"])


def test_ai_employee_growth_employee_not_found_returns_empty_state(client, owner_headers):
    response = client.get(f"{BASE}/employees/missing_employee", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "readonly"
    assert data["employee"]["employee_id"] == "missing_employee"
    assert data["employee"]["status"] == "unknown"
    assert data["task_summary"]["total"] == 0
    assert data["audit_summary"]["audit_events"] == 0
    assert data["growth_summary"]["available"] is False
    assert data["memory_summary"]["success_case_candidates"] == 0
    assert data["memory_summary"]["failure_case_candidates"] == 0
    assert data["recent_timeline"] == []
    assert data["empty_state"]["message"] == "暂无成长数据"
    assert_security(data["security"])


def test_ai_employee_growth_employee_detail_aggregates_existing_data(client, owner_headers):
    completed_id = create_full_task_flow(client, owner_headers)
    rejected_id = create_rejected_task(client, owner_headers)

    response = client.get(f"{BASE}/employees/tianwang", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["growth_summary"]["available"] is True
    assert data["task_summary"]["total"] >= 2
    assert data["task_summary"]["success"] >= 1
    assert data["task_summary"]["failure"] >= 1
    assert data["skill_summary"]["total"] >= 1
    assert data["audit_summary"]["audit_events"] >= 2
    assert data["audit_summary"]["boss_confirm_events"] >= 1
    assert data["memory_summary"]["success_case_candidates"] >= 1
    assert data["memory_summary"]["failure_case_candidates"] >= 1
    timeline_task_ids = {item["task_id"] for item in data["recent_timeline"] if item.get("task_id")}
    assert completed_id in timeline_task_ids
    assert rejected_id in timeline_task_ids


def test_ai_employee_growth_timeline_contains_task_audit_memory_growth(client, owner_headers):
    task_id = create_full_task_flow(client, owner_headers)

    response = client.get(f"{BASE}/employees/tianwang/timeline", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "readonly"
    event_types = [item["event_type"] for item in data["timeline"]]
    assert "task" in event_types
    assert "audit" in event_types
    assert "memory" in event_types
    assert "growth" in event_types
    assert any(item["task_id"] == task_id and item["event_type"] == "growth" for item in data["timeline"])
    assert data["summary"]["growth_events"] >= 1
    assert_security(data["security"])


def test_ai_employee_growth_timeline_is_reverse_chronological(client, owner_headers):
    create_full_task_flow(client, owner_headers)
    create_rejected_task(client, owner_headers)

    response = client.get(f"{BASE}/employees/tianwang/timeline", headers=owner_headers)

    assert response.status_code == 200
    timeline = response.json()["timeline"]
    times = [item["time"] for item in timeline if item.get("time")]
    assert len(times) >= 2
    assert times == sorted(times, reverse=True)


def test_ai_employee_growth_timeline_empty_state(client, owner_headers):
    response = client.get(f"{BASE}/employees/no_such_employee/timeline", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["timeline"] == []
    assert data["empty_state"]["message"] == "暂无成长时间线数据"
    assert_security(data["security"])


def test_ai_employee_growth_get_requests_do_not_mutate_task_center(test_db, client, owner_headers):
    create_waiting_confirm_task(client, owner_headers)
    before = task_center_counts(test_db)

    assert client.get(f"{BASE}/overview", headers=owner_headers).status_code == 200
    assert client.get(f"{BASE}/employees/tianwang", headers=owner_headers).status_code == 200
    assert client.get(f"{BASE}/employees/tianwang/timeline", headers=owner_headers).status_code == 200

    after = task_center_counts(test_db)
    assert after == before


def test_ai_employee_growth_readonly_security_on_all_endpoints(client, owner_headers):
    create_waiting_confirm_task(client, owner_headers)

    endpoints = [
        f"{BASE}/overview",
        f"{BASE}/employees/tianwang",
        f"{BASE}/employees/tianwang/timeline",
    ]
    for endpoint in endpoints:
        response = client.get(endpoint, headers=owner_headers)
        assert response.status_code == 200
        security = response.json()["security"]
        assert_security(security)
        assert security["boss_confirm_required"] is True
        assert security["security_audited_required"] is True
        assert security["auto_permission_change"] is False


def test_ai_employee_growth_static_safety_boundaries():
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
        "method='POST'",
        'method="POST"',
    ]
    for text in forbidden:
        assert text not in combined


def assert_security(security):
    assert security["readonly"] is True
    assert security["boss_confirm"] is True
    assert security["security_audited"] is True
    assert security["execution_engine_called"] is False
    assert security["openclaw_connected"] is False
    assert security["n8n_connected"] is False
    assert security["auto_learning"] is False
    assert security["auto_skill_upgrade"] is False
    assert security["auto_task_execution"] is False


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
        json={"result_content": "AI employee growth API test result."},
    )
    assert result.status_code == 200
    return task_id


def create_task(client, headers):
    response = client.post(
        "/api/task-center/tasks",
        headers=headers,
        json={"title": "Sprint62.48 AI employee growth API test task"},
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
