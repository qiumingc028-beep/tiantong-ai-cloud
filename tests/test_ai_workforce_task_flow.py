from pathlib import Path

from backend.models import TaskCenterAuditLog, TaskCenterTask


BASE = "/api/ai-workforce"


def test_task_flow_requires_login(client):
    response = client.get(f"{BASE}/employees/tianwang/task-flow")

    assert response.status_code == 401


def test_task_flow_rejects_viewer(client, viewer_headers):
    response = client.get(f"{BASE}/employees/tianwang/task-flow", headers=viewer_headers)

    assert response.status_code == 403


def test_task_flow_allows_boss_owner_admin(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        response = client.get(f"{BASE}/employees/tianwang/task-flow", headers=headers)

        assert response.status_code == 200
        assert response.json()["mode"] == "readonly"


def test_task_flow_maps_task_center_lifecycle_statuses(client, owner_headers):
    task_id = create_full_task_flow(client, owner_headers)

    lifecycle = client.get(f"{BASE}/tasks/{task_id}/lifecycle", headers=owner_headers)

    assert lifecycle.status_code == 200
    payload = lifecycle.json()
    assert payload["mode"] == "readonly"
    assert payload["task"]["current_status"] == "completed"
    assert payload["task"]["task_center_status"] == "summarized"
    assert payload["security"]["readonly"] is True
    assert payload["security"]["execution_engine_called"] is False
    assert payload["security"]["openclaw_connected"] is False
    assert payload["security"]["n8n_connected"] is False

    statuses = [row["status"] for row in payload["lifecycle"]]
    assert statuses == [
        "created",
        "processing",
        "processing",
        "waiting_confirm",
        "approved",
        "approved",
        "completed",
    ]

    employee_flow = client.get(f"{BASE}/employees/tianwang/task-flow", headers=owner_headers)

    assert employee_flow.status_code == 200
    summary = employee_flow.json()["summary"]
    assert summary["total"] >= 1
    assert summary["completed"] >= 1
    task_items = employee_flow.json()["tasks"]
    assert any(item["task_id"] == task_id and item["lifecycle_status"] == "completed" for item in task_items)


def test_waiting_confirm_requires_boss_confirmation(client, owner_headers):
    task_id = create_waiting_confirm_task(client, owner_headers)

    response = client.get(f"{BASE}/tasks/waiting-confirm", headers=owner_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "readonly"
    assert payload["total"] >= 1
    assert payload["manual_confirm"]["boss_confirm_required"] is True
    assert payload["security"]["auto_execute"] is False

    item = next(task for task in payload["tasks"] if task["task_id"] == task_id)
    assert item["lifecycle_status"] == "waiting_confirm"
    assert item["boss_confirm_required"] is True
    assert item["manual_confirm_required"] is True
    assert item["action_available"] is False


def test_rejected_task_requires_security_audit(client, owner_headers):
    task_id = create_task(client, owner_headers)
    review = client.post(
        f"/api/task-center/tasks/{task_id}/reviews",
        headers=owner_headers,
        json={"review_status": "rejected", "comment": "Boss rejected the result."},
    )
    assert review.status_code == 200

    response = client.get(f"{BASE}/tasks/{task_id}/lifecycle", headers=owner_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["task"]["current_status"] == "rejected"
    assert payload["manual_confirm"]["boss_confirm_required"] is True
    assert payload["manual_confirm"]["security_audited_required"] is True


def test_task_flow_returns_task_center_audit_records(client, owner_headers):
    task_id = create_waiting_confirm_task(client, owner_headers)

    response = client.get(f"{BASE}/tasks/{task_id}/lifecycle", headers=owner_headers)

    assert response.status_code == 200
    actions = [row["action"] for row in response.json()["audit"]]
    assert actions == [
        "task_created",
        "ai_employee_assigned",
        "task_started",
        "result_submitted",
    ]


def test_task_flow_get_requests_do_not_mutate_task_center(test_db, client, owner_headers):
    task_id = create_waiting_confirm_task(client, owner_headers)
    before = task_center_counts(test_db)

    assert client.get(f"{BASE}/employees/tianwang/task-flow", headers=owner_headers).status_code == 200
    assert client.get(f"{BASE}/tasks/{task_id}/lifecycle", headers=owner_headers).status_code == 200
    assert client.get(f"{BASE}/tasks/waiting-confirm", headers=owner_headers).status_code == 200

    after = task_center_counts(test_db)
    assert after == before


def test_task_flow_404_for_missing_task(client, owner_headers):
    response = client.get(f"{BASE}/tasks/999999/lifecycle", headers=owner_headers)

    assert response.status_code == 404


def test_task_flow_implementation_keeps_execution_integrations_out():
    paths = [
        Path("backend/services/ai_workforce_task_flow.py"),
        Path("backend/routers/ai_workforce.py"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    forbidden = [
        "openclaw import",
        "n8n import",
        "execution_engine import",
        "/api/execution",
        "/api/brain/start",
        "TaskCenterTask(",
        ".commit(",
        ".delete(",
    ]
    for marker in forbidden:
        assert marker not in combined


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
        json={"result_content": "AI employee analysis result waiting for Boss confirmation."},
    )
    assert result.status_code == 200
    return task_id


def create_task(client, headers):
    response = client.post(
        "/api/task-center/tasks",
        headers=headers,
        json={"title": "Sprint62.39 AI employee task flow test"},
    )
    assert response.status_code == 200
    return response.json()["task"]["id"]


def task_center_counts(session_factory):
    db = session_factory()
    try:
        return {
            "tasks": db.query(TaskCenterTask).count(),
            "audit_logs": db.query(TaskCenterAuditLog).count(),
        }
    finally:
        db.close()
