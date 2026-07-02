def test_task_center_requires_login(client):
    response = client.get("/api/task-center/tasks")

    assert response.status_code == 401


def test_viewer_cannot_access_task_center(client, viewer_headers):
    response = client.get("/api/task-center/tasks", headers=viewer_headers)

    assert response.status_code == 403


def test_operator_and_delivery_roles_cannot_access_task_center(client, operator_headers):
    assert client.get("/api/task-center/tasks", headers=operator_headers).status_code == 403

    for username in ["customer_service", "designer", "editor"]:
        headers = login_headers(client, username)
        response = client.get("/api/task-center/tasks", headers=headers)
        assert response.status_code == 403


def test_boss_owner_admin_can_access_task_center(client, boss_headers, owner_headers, admin_headers):
    for headers in [boss_headers, owner_headers, admin_headers]:
        response = client.get("/api/task-center/tasks", headers=headers)
        assert response.status_code == 200


def test_task_center_mvp_flow_writes_audit_logs(client, owner_headers):
    created = client.post(
        "/api/task-center/tasks",
        headers=owner_headers,
        json={
            "title": "Prepare daily store analysis",
            "description": "Boss asks Tiantong to split and coordinate the work.",
            "split_plan": "Split into data analysis and acceptance review.",
        },
    )
    assert created.status_code == 200
    task = created.json()["task"]
    task_id = task["id"]
    assert task["status"] == "split"

    listed = client.get("/api/task-center/tasks", headers=owner_headers)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == task_id

    assigned = client.post(
        f"/api/task-center/tasks/{task_id}/assign",
        headers=owner_headers,
        json={"ai_employee_code": "ai_operator"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["task"]["status"] == "assigned"

    started = client.post(f"/api/task-center/tasks/{task_id}/start", headers=owner_headers)
    assert started.status_code == 200
    assert started.json()["task"]["status"] == "running"

    result = client.post(
        f"/api/task-center/tasks/{task_id}/results",
        headers=owner_headers,
        json={"result_content": "Daily analysis completed.", "attachments": ["report.txt"]},
    )
    assert result.status_code == 200
    assert result.json()["task"]["status"] == "result_submitted"
    assert result.json()["result"]["attachments"] == ["report.txt"]

    review = client.post(
        f"/api/task-center/tasks/{task_id}/reviews",
        headers=owner_headers,
        json={"review_status": "accepted", "comment": "Accepted by Tianjian."},
    )
    assert review.status_code == 200
    assert review.json()["task"]["status"] == "accepted"

    audit = client.post(
        f"/api/task-center/tasks/{task_id}/audits",
        headers=owner_headers,
        json={"review_status": "audited", "comment": "Audit trail is complete."},
    )
    assert audit.status_code == 200
    assert audit.json()["task"]["status"] == "audited"

    summary = client.post(
        f"/api/task-center/tasks/{task_id}/summary",
        headers=owner_headers,
        json={"summary": "Tiantong summary: task completed and accepted."},
    )
    assert summary.status_code == 200
    assert summary.json()["task"]["status"] == "summarized"

    detail = client.get(f"/api/task-center/tasks/{task_id}", headers=owner_headers)
    assert detail.status_code == 200
    assert len(detail.json()["results"]) == 1
    assert [row["review_type"] for row in detail.json()["reviews"]] == ["acceptance", "audit"]

    logs = client.get(f"/api/task-center/tasks/{task_id}/audit-logs", headers=owner_headers)
    assert logs.status_code == 200
    actions = [row["action"] for row in logs.json()]
    assert actions == [
        "task_created",
        "ai_employee_assigned",
        "task_started",
        "result_submitted",
        "acceptance_reviewed",
        "task_audited",
        "task_summarized",
    ]


def test_acceptance_review_rejects_invalid_status(client, owner_headers):
    task_id = create_task(client, owner_headers)

    typo = client.post(
        f"/api/task-center/tasks/{task_id}/reviews",
        headers=owner_headers,
        json={"review_status": "typo", "comment": "Invalid status should fail."},
    )
    assert typo.status_code == 400

    empty = client.post(
        f"/api/task-center/tasks/{task_id}/reviews",
        headers=owner_headers,
        json={"review_status": "", "comment": "Empty status should fail."},
    )
    assert empty.status_code == 400


def test_acceptance_review_accepts_accepted_status(client, owner_headers):
    task_id = create_task(client, owner_headers)

    response = client.post(
        f"/api/task-center/tasks/{task_id}/reviews",
        headers=owner_headers,
        json={"review_status": "accepted", "comment": "Accepted."},
    )

    assert response.status_code == 200
    assert response.json()["review"]["review_status"] == "accepted"
    assert response.json()["task"]["status"] == "accepted"


def test_acceptance_review_accepts_rejected_status(client, owner_headers):
    task_id = create_task(client, owner_headers)

    response = client.post(
        f"/api/task-center/tasks/{task_id}/reviews",
        headers=owner_headers,
        json={"review_status": "rejected", "comment": "Rejected."},
    )

    assert response.status_code == 200
    assert response.json()["review"]["review_status"] == "rejected"
    assert response.json()["task"]["status"] == "rejected"


def create_task(client, headers):
    response = client.post(
        "/api/task-center/tasks",
        headers=headers,
        json={"title": "Acceptance review test task"},
    )
    assert response.status_code == 200
    return response.json()["task"]["id"]


def login_headers(client, username):
    response = client.post("/api/login", json={"username": username, "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}
