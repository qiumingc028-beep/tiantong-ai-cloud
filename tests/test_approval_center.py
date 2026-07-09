from backend.models import TaskCenterTask


def test_approval_center_pending_requires_login(client):
    response = client.get("/api/approval-center/pending")

    assert response.status_code == 401


def test_approval_center_pending_rejects_viewer(client, viewer_headers):
    response = client.get("/api/approval-center/pending", headers=viewer_headers)

    assert response.status_code == 403


def test_approval_center_pending_allows_owner_and_admin(client, owner_headers, admin_headers):
    for headers in (owner_headers, admin_headers):
        response = client.get("/api/approval-center/pending", headers=headers)

        assert response.status_code == 200
        assert response.json()["readonly"] is True


def test_approval_center_pending_response_shape_and_recommendations(client, owner_headers, test_db):
    db = test_db()
    try:
        db.add(
            TaskCenterTask(
                title="High risk rejected task",
                description="Needs boss rework decision",
                status="rejected",
                priority="high",
                assigned_ai_employee_code="tianwang",
                assigned_ai_employee_name="天王：后端开发中心",
            )
        )
        db.add(
            TaskCenterTask(
                title="Submitted task",
                status="result_submitted",
                assigned_ai_employee_code="tiantong",
                assigned_ai_employee_name="天统：AI总指挥",
            )
        )
        db.add(TaskCenterTask(title="Completed task", status="summarized"))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/approval-center/pending", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["pending_count"] == 2
    first = data["items"][0]
    assert {
        "id",
        "source_ai_employee",
        "title",
        "description",
        "risk_level",
        "recommendation",
        "created_at",
        "status",
    } <= set(first)
    assert first["title"] == "Submitted task"
    assert first["risk_level"] == "medium"
    high_risk = next(item for item in data["items"] if item["title"] == "High risk rejected task")
    assert high_risk["risk_level"] == "high"
    assert "返工" in high_risk["recommendation"]


def test_approval_center_pending_is_readonly(client, owner_headers, test_db):
    db = test_db()
    try:
        before_tasks = db.query(TaskCenterTask).count()
    finally:
        db.close()

    response = client.get("/api/approval-center/pending", headers=owner_headers)
    assert response.status_code == 200

    db = test_db()
    try:
        assert db.query(TaskCenterTask).count() == before_tasks
    finally:
        db.close()
