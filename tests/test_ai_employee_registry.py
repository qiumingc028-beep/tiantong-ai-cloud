import subprocess
import sys


def test_ai_employee_list_returns_real_employees(client, owner_headers):
    response = client.get("/api/ai-employees", headers=owner_headers)

    assert response.status_code == 200
    employees = response.json()
    codes = [employee["employee_code"] for employee in employees]
    assert "tiantong" in codes
    assert "tianwang" in codes
    assert "legacy_operator" not in codes


def test_ai_employee_list_filters_by_task_type(client, owner_headers):
    response = client.get("/api/ai-employees?task_type=backend", headers=owner_headers)

    assert response.status_code == 200
    assert [employee["employee_code"] for employee in response.json()] == ["tianwang"]


def test_can_get_single_ai_employee(client, owner_headers):
    response = client.get("/api/ai-employees/tianwang", headers=owner_headers)

    assert response.status_code == 200
    assert response.json()["employee_name"] == "天王：后端开发中心"
    assert response.json()["task_types"] == ["backend"]


def test_can_create_update_enable_and_disable_ai_employee(client, owner_headers):
    created = client.post(
        "/api/ai-employees",
        headers=owner_headers,
        json={
            "employee_code": "test_registry_employee",
            "employee_name": "Test Registry Employee",
            "legion": "Test Legion",
            "duty": "Initial duty",
            "task_types": ["backend"],
            "default_permissions": ["task_center.execute"],
        },
    )
    assert created.status_code == 200
    assert created.json()["employee"]["status"] == "active"

    updated = client.patch(
        "/api/ai-employees/test_registry_employee",
        headers=owner_headers,
        json={"employee_name": "Updated Employee", "task_types": ["test"], "sort_order": 999},
    )
    assert updated.status_code == 200
    assert updated.json()["employee"]["employee_name"] == "Updated Employee"
    assert updated.json()["employee"]["task_types"] == ["test"]

    disabled = client.post("/api/ai-employees/test_registry_employee/disable", headers=owner_headers)
    assert disabled.status_code == 200
    assert disabled.json()["employee"]["status"] == "inactive"

    enabled = client.post("/api/ai-employees/test_registry_employee/enable", headers=owner_headers)
    assert enabled.status_code == 200
    assert enabled.json()["employee"]["status"] == "active"


def test_operator_cannot_manage_ai_employee_registry(client, operator_headers):
    response = client.get("/api/ai-employees", headers=operator_headers)

    assert response.status_code == 403


def test_inactive_employee_cannot_be_assigned_to_task_center(client, owner_headers):
    task_id = create_task(client, owner_headers)
    disabled = client.post("/api/ai-employees/tianwang/disable", headers=owner_headers)
    assert disabled.status_code == 200

    assigned = client.post(
        f"/api/task-center/tasks/{task_id}/assign",
        headers=owner_headers,
        json={"ai_employee_code": "tianwang"},
    )

    assert assigned.status_code == 400


def test_active_employee_can_be_assigned_to_task_center(client, owner_headers):
    task_id = create_task(client, owner_headers)
    enabled = client.post("/api/ai-employees/tianwang/enable", headers=owner_headers)
    assert enabled.status_code == 200

    assigned = client.post(
        f"/api/task-center/tasks/{task_id}/assign",
        headers=owner_headers,
        json={"ai_employee_code": "tianwang"},
    )

    assert assigned.status_code == 200
    assert assigned.json()["task"]["assigned_ai_employee_code"] == "tianwang"
    assert assigned.json()["task"]["assigned_ai_employee_name"] == "天王：后端开发中心"


def test_legacy_employee_cannot_be_assigned_by_default(client, owner_headers):
    task_id = create_task(client, owner_headers)

    assigned = client.post(
        f"/api/task-center/tasks/{task_id}/assign",
        headers=owner_headers,
        json={"ai_employee_code": "legacy_operator"},
    )

    assert assigned.status_code == 400


def test_legacy_ai_tasks_api_still_accessible(client, owner_headers):
    response = client.get("/api/ai/tasks", headers=owner_headers)

    assert response.status_code == 200
    assert response.json()[0]["ai_employee_code"] == "ai_operator"


def test_alembic_heads_has_single_head():
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        capture_output=True,
        text=True,
        check=True,
    )

    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert heads == ["0026_sprint26_ai_employee_execution_mvp (head)"]


def create_task(client, headers):
    response = client.post(
        "/api/task-center/tasks",
        headers=headers,
        json={"title": "Registry assignment task", "split_plan": "Assign to a registry employee."},
    )
    assert response.status_code == 200
    return response.json()["task"]["id"]
