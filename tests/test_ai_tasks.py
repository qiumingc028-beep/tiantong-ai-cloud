def test_ai_tasks_requires_login(client):
    response = client.get("/api/ai/tasks")

    assert response.status_code == 401


def test_owner_can_list_ai_tasks(client, owner_headers):
    response = client.get("/api/ai/tasks", headers=owner_headers)

    assert response.status_code == 200
    tasks = response.json()
    assert isinstance(tasks, list)
    assert tasks[0]["ai_employee_code"] == "ai_operator"


def test_low_privilege_user_cannot_list_ai_tasks(client, viewer_headers):
    response = client.get("/api/ai/tasks", headers=viewer_headers)

    assert response.status_code == 403
