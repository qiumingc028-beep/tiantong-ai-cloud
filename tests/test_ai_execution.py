from backend import queue, worker
from backend.models import TaskCenterResult, TaskCenterTask, User
from backend.task_center_ownership import bind_task_ownership, owned_task_or_none, task_ownership_context


def patch_worker_session(monkeypatch, test_db):
    monkeypatch.setattr(worker, "SessionLocal", test_db)
    monkeypatch.setattr(worker, "get_redis", queue.get_redis)


def test_create_assign_execute_and_list_results(client, owner_headers, test_db, monkeypatch):
    patch_worker_session(monkeypatch, test_db)

    create_response = client.post(
        "/api/tasks",
        headers=owner_headers,
        json={"type": "mock_research", "input": {"topic": "Sprint 17"}, "assigned_to": "tiantong"},
    )
    assert create_response.status_code == 200
    task = create_response.json()["task"]
    assert task["type"] == "mock_research"
    assert task["assigned_to"] == "tiantong"
    assert task["status"] == "assigned"

    assert worker.process_next_task() is True

    list_response = client.get("/api/tasks", headers=owner_headers)
    assert list_response.status_code == 200
    rows = list_response.json()["tasks"]
    completed = next(row for row in rows if row["id"] == task["id"])
    assert completed["status"] == "completed"
    assert completed["result"]["assigned_to"] == "tiantong"
    assert completed["result"]["mode"] == "business_mock"

    results_response = client.get("/api/results", headers=owner_headers)
    assert results_response.status_code == 200
    results = results_response.json()["results"]
    assert any(row["task_id"] == task["id"] and row["assigned_to"] == "tiantong" for row in results)


def test_api_key_cannot_create_or_read_without_authenticated_scope(client, monkeypatch):
    monkeypatch.setenv("AUTOMATION_API_KEY", "test-api-key")
    headers = {"X-API-Key": "test-api-key"}

    create_response = client.post(
        "/api/tasks",
        headers=headers,
        json={"type": "external_business_task", "input": {"source": "partner"}, "assigned_to": "tiancai_data"},
    )
    assert create_response.status_code == 401

    list_response = client.get("/api/tasks", headers=headers)
    assert list_response.status_code == 401


def test_api_key_cannot_trigger_flow_or_read_results_without_authenticated_scope(client, monkeypatch):
    monkeypatch.setenv("AUTOMATION_API_KEY", "test-api-key")
    headers = {"X-API-Key": "test-api-key"}

    flow_response = client.post(
        "/api/flows/tiancai-tianshu-tiance-tianbo",
        headers=headers,
        json={"input": {"seed": "api-key-flow"}},
    )
    assert flow_response.status_code == 401

    results_response = client.get("/api/results", headers=headers)
    assert results_response.status_code == 401


def test_internal_bypass_cannot_read_results_without_authenticated_scope(client, monkeypatch):
    response = client.get("/api/results", headers={"X-Internal-Bypass": "true"})
    assert response.status_code == 401


def test_webhook_secret_cannot_trigger_task_without_authenticated_scope(client, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "webhook-secret")
    response = client.post(
        "/api/webhooks/tasks",
        headers={"X-Webhook-Secret": "webhook-secret"},
        json={"type": "webhook_external_task", "input": {"sku": "A1"}, "assigned_to": "tiancai_data"},
    )
    assert response.status_code == 401


def test_webhook_requires_auth_when_secret_mismatch(client, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "webhook-secret")
    response = client.post(
        "/api/webhooks/tasks",
        headers={"X-Webhook-Secret": "wrong"},
        json={"type": "webhook_external_task", "input": {"sku": "A1"}, "assigned_to": "tiancai_data"},
    )
    assert response.status_code == 401


def test_assign_existing_task_enqueues_and_completes(client, owner_headers, test_db, monkeypatch):
    patch_worker_session(monkeypatch, test_db)

    create_response = client.post(
        "/api/tasks",
        headers=owner_headers,
        json={"type": "mock_copywriting", "input": "brief"},
    )
    assert create_response.status_code == 200
    task_id = create_response.json()["task"]["id"]

    assign_response = client.post(
        f"/api/tasks/{task_id}/assign",
        headers=owner_headers,
        json={"assigned_to": "tianyu"},
    )
    assert assign_response.status_code == 200
    assert assign_response.json()["task"]["assigned_to"] == "tianyu"

    assert worker.process_next_task() is True

    results_response = client.get("/api/results", headers=owner_headers)
    assert results_response.status_code == 200
    assert any(row["task_id"] == task_id and row["assigned_to"] == "tianyu" for row in results_response.json()["results"])


def test_manual_complete_task_writes_result(client, owner_headers):
    create_response = client.post(
        "/api/tasks",
        headers=owner_headers,
        json={"type": "manual_review", "input": {"item": 1}, "assigned_to": "tianjian_test"},
    )
    assert create_response.status_code == 200
    task_id = create_response.json()["task"]["id"]

    complete_response = client.post(
        f"/api/tasks/{task_id}/complete",
        headers=owner_headers,
        json={"result": {"accepted": True}},
    )
    assert complete_response.status_code == 200
    body = complete_response.json()
    assert body["task"]["status"] == "completed"
    assert body["task"]["result"] == {"accepted": True}


def test_tiancai_tianshu_tiance_tianbo_flow(client, owner_headers, test_db, monkeypatch):
    patch_worker_session(monkeypatch, test_db)

    response = client.post(
        "/api/flows/tiancai-tianshu-tiance-tianbo",
        headers=owner_headers,
        json={"input": {"seed": "market data"}},
    )
    assert response.status_code == 200
    flow_id = response.json()["flow_id"]
    assert response.json()["chain"] == ["tiancai_data", "tianshu", "tiance_strategy", "tianbo"]

    for _ in range(4):
        assert worker.process_next_task() is True

    tasks_response = client.get("/api/tasks", headers=owner_headers)
    assert tasks_response.status_code == 200
    flow_tasks = [row for row in tasks_response.json()["tasks"] if row["flow_id"] == flow_id]
    assert len(flow_tasks) == 4
    assert {row["assigned_to"] for row in flow_tasks} == {"tiancai_data", "tianshu", "tiance_strategy", "tianbo"}
    assert all(row["status"] == "completed" for row in flow_tasks)

    ordered = sorted(flow_tasks, key=lambda row: row["flow_index"])
    assert ordered[1]["input"]["assigned_to"] == "tiancai_data"
    assert ordered[2]["input"]["assigned_to"] == "tianshu"
    assert ordered[3]["input"]["assigned_to"] == "tiance_strategy"


def test_webhook_can_trigger_business_flow(client, owner_headers, test_db, monkeypatch):
    patch_worker_session(monkeypatch, test_db)
    monkeypatch.setenv("AUTOMATION_API_KEY", "test-api-key")

    response = client.post(
        "/api/webhooks/tasks",
        headers={**owner_headers, "X-API-Key": "test-api-key"},
        json={"flow": "tiancai-tianshu-tiance-tianbo", "input": {"trigger": "webhook"}},
    )
    assert response.status_code == 200
    assert response.json()["chain"] == ["tiancai_data", "tianshu", "tiance_strategy", "tianbo"]

    for _ in range(4):
        assert worker.process_next_task() is True

    results_response = client.get("/api/results", headers=login_owner(client))
    assert results_response.status_code == 200
    results = results_response.json()["results"]
    assert any(row["assigned_to"] == "tianbo" and row["result"]["payload"]["content"]["title"] for row in results)


def test_feedback_loop_reuses_result_as_next_input(client, owner_headers, test_db, monkeypatch):
    patch_worker_session(monkeypatch, test_db)

    create_response = client.post(
        "/api/tasks",
        headers=owner_headers,
        json={"type": "data_collection", "input": {"source": "ecommerce"}, "assigned_to": "tiancai_data"},
    )
    task_id = create_response.json()["task"]["id"]
    assert worker.process_next_task() is True

    feedback_response = client.post(
        f"/api/tasks/{task_id}/feedback-loop",
        headers=owner_headers,
        json={"feedback": {"improve": "focus content"}, "assigned_to": "tiance_strategy"},
    )
    assert feedback_response.status_code == 200
    loop_task = feedback_response.json()["task"]
    assert loop_task["input"]["source_task_id"] == task_id
    assert loop_task["input"]["source_result"]["reusable_as_input"] is True

    assert worker.process_next_task() is True
    tasks_response = client.get("/api/tasks", headers=owner_headers)
    completed = next(row for row in tasks_response.json()["tasks"] if row["id"] == loop_task["id"])
    assert completed["status"] == "completed"
    assert "strategy" in completed["result"]["payload"]


def test_daily_scheduler_creates_one_business_flow(test_db, monkeypatch):
    patch_worker_session(monkeypatch, test_db)

    db = test_db()
    try:
        owner = db.query(User).filter(User.username == "owner").one()
        admin = db.query(User).filter(User.username == "admin").one()

        def create_source(user, *, tampered=False):
            source = TaskCenterTask(
                title=f"Daily scheduler ownership source for {user.username}",
                status="completed",
                source=worker.DAILY_SCHEDULER_OWNERSHIP_SOURCE,
            )
            scope = bind_task_ownership(db, source, user=user)
            if tampered:
                source.ownership_scope_key = "0" * 64
            db.add(source)
            db.commit()
            db.refresh(source)
            return source, scope

        def scheduled_tasks():
            return (
                db.query(TaskCenterTask)
                .filter(TaskCenterTask.source == "sprint17_ai_execution")
                .order_by(TaskCenterTask.id.asc())
                .all()
            )

        worker.run_daily_scheduler()
        assert scheduled_tasks() == []
        assert queue.get_redis().lists.get(queue.QUEUE_NAME, []) == []

        create_source(owner, tampered=True)
        worker.run_daily_scheduler()
        assert scheduled_tasks() == []
        assert queue.get_redis().lists.get(queue.QUEUE_NAME, []) == []

        owner_source, owner_scope = create_source(owner)
        assert task_ownership_context(owner_source) == {
            "tenant_id": owner_scope.tenant_id,
            "company_id": owner_scope.company_id,
            "requester_id": owner_scope.requester_id,
            "store_scope_key": owner_scope.store_scope_key,
            "ownership_scope_key": owner_scope.ownership_scope_key,
            "canonical_run_id": None,
        }

        worker.run_daily_scheduler()
        worker.run_daily_scheduler()

        rows = scheduled_tasks()
        assert len(rows) == 1
        task = rows[0]
        assert task.assigned_ai_employee_code == "tiancai_data"
        assert task.parent_task_id == owner_source.id
        assert task_ownership_context(task) == task_ownership_context(owner_source)
        assert owned_task_or_none(db, task_id=task.id, user=owner).id == task.id
        assert owned_task_or_none(db, task_id=task.id, user=admin) is None
        assert len(queue.get_redis().lists[queue.QUEUE_NAME]) == 1

        admin_source, admin_scope = create_source(admin)
        worker.run_daily_scheduler()
        worker.run_daily_scheduler()

        rows = scheduled_tasks()
        assert len(rows) == 2
        tasks_by_scope = {row.ownership_scope_key: row for row in rows}
        assert set(tasks_by_scope) == {owner_scope.ownership_scope_key, admin_scope.ownership_scope_key}
        assert tasks_by_scope[owner_scope.ownership_scope_key].parent_task_id == owner_source.id
        assert tasks_by_scope[admin_scope.ownership_scope_key].parent_task_id == admin_source.id
        assert owned_task_or_none(db, task_id=tasks_by_scope[owner_scope.ownership_scope_key].id, user=admin) is None
        assert owned_task_or_none(db, task_id=tasks_by_scope[admin_scope.ownership_scope_key].id, user=owner) is None
        scheduler_keys = {
            key for key in queue.get_redis().values if key.startswith(worker.DAILY_SCHEDULER_PREFIX)
        }
        assert scheduler_keys == {
            f"{worker.DAILY_SCHEDULER_PREFIX}{worker.date.today().isoformat()}:{owner_scope.ownership_scope_key}",
            f"{worker.DAILY_SCHEDULER_PREFIX}{worker.date.today().isoformat()}:{admin_scope.ownership_scope_key}",
        }
        assert len(queue.get_redis().lists[queue.QUEUE_NAME]) == 2
        assert db.query(TaskCenterResult).count() == 0
    finally:
        db.close()


def login_owner(client):
    response = client.post("/api/login", json={"username": "owner", "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}
