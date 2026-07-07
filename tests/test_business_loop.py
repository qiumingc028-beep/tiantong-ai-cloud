from backend import queue, worker
from backend.models import TaskCenterTask


def patch_worker_session(monkeypatch, test_db):
    monkeypatch.setattr(worker, "SessionLocal", test_db)
    monkeypatch.setattr(worker, "get_redis", queue.get_redis)


def test_ecommerce_webhook_creates_business_loop_task_with_secret(client, test_db, monkeypatch):
    patch_worker_session(monkeypatch, test_db)
    monkeypatch.setenv("WEBHOOK_SECRET", "business-secret")

    response = client.post(
        "/api/business-webhooks/ecommerce/orders",
        headers={"X-Webhook-Secret": "business-secret"},
        json={
            "platform": "shop",
            "order_id": "O-1001",
            "sku": "SKU-18",
            "product_name": "Sprint 18 商品",
            "quantity": 2,
            "amount": 199.8,
            "customer_tags": ["repeat"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["event_type"] == "ecommerce_order"
    assert body["task"]["status"] == "assigned"
    assert body["task"]["input"]["sku"] == "SKU-18"

    assert worker.process_next_task() is True

    results = client.get("/api/business-loop/results", headers=login_owner(client))
    assert results.status_code == 200
    result = results.json()["results"][0]["result"]
    assert result["analysis"]["signal_type"] == "order_conversion"
    assert result["decision"]["requires_human_approval"] is True
    assert result["execution"]["status"] == "mock_executed"
    assert result["feedback_loop"]["reusable_as_input"] is True


def test_content_metrics_webhook_requires_auth_when_secret_wrong(client, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "business-secret")

    response = client.post(
        "/api/business-webhooks/content/metrics",
        headers={"X-Webhook-Secret": "wrong"},
        json={"content_id": "C-1", "views": 1000, "likes": 30, "comments": 5, "shares": 4},
    )

    assert response.status_code == 401


def test_content_metrics_webhook_uses_api_key_and_worker_writes_decision(client, test_db, monkeypatch):
    patch_worker_session(monkeypatch, test_db)
    monkeypatch.setenv("AUTOMATION_API_KEY", "business-api-key")

    response = client.post(
        "/api/business-webhooks/content/metrics",
        headers={"X-API-Key": "business-api-key"},
        json={"content_id": "C-18", "title": "AI 内容", "views": 1200, "likes": 60, "comments": 8, "shares": 12},
    )

    assert response.status_code == 200
    assert worker.process_next_task() is True

    decisions = client.get("/api/business-loop/decisions", headers={"X-API-Key": "business-api-key"})
    assert decisions.status_code == 200
    task = decisions.json()["tasks"][0]
    assert task["event_type"] == "content_metrics"
    assert task["status"] == "completed"
    assert task["result"]["analysis"]["signal_type"] == "content_performance"
    assert task["result"]["decision"]["optimization_focus"] in {"内容转化", "内容钩子优化"}


def test_file_upload_webhook_creates_file_analysis_task(client, owner_headers, test_db, monkeypatch):
    patch_worker_session(monkeypatch, test_db)

    response = client.post(
        "/api/business-webhooks/files",
        headers=owner_headers,
        json={
            "filename": "orders.csv",
            "file_type": "csv",
            "content_summary": "3 行订单数据",
            "rows": [{"sku": "A"}, {"sku": "B"}, {"sku": "C"}],
        },
    )

    assert response.status_code == 200
    assert worker.process_next_task() is True

    results = client.get("/api/business-loop/results", headers=owner_headers)
    result = results.json()["results"][0]["result"]
    assert result["event_type"] == "file_upload"
    assert result["analysis"]["file"]["row_count"] == 3
    assert result["execution"]["external_actions"] == []


def test_business_result_replay_creates_feedback_loop_task(client, owner_headers, test_db, monkeypatch):
    patch_worker_session(monkeypatch, test_db)

    create_response = client.post(
        "/api/business-webhooks/ecommerce/orders",
        headers=owner_headers,
        json={"order_id": "O-2002", "sku": "SKU-REPLAY", "quantity": 1, "amount": 88.0},
    )
    assert create_response.status_code == 200
    assert worker.process_next_task() is True

    results_response = client.get("/api/business-loop/results", headers=owner_headers)
    result_id = results_response.json()["results"][0]["id"]

    replay_response = client.post(
        f"/api/business-loop/results/{result_id}/replay",
        headers=owner_headers,
        json={"feedback": {"improve": "提高复购内容"}},
    )
    assert replay_response.status_code == 200
    replay_task = replay_response.json()["task"]
    assert replay_task["event_type"] == "feedback_replay"
    assert replay_task["loop_iteration"] == 1

    assert worker.process_next_task() is True
    decisions = client.get("/api/business-loop/decisions", headers=owner_headers).json()["tasks"]
    completed_replay = next(row for row in decisions if row["id"] == replay_task["id"])
    assert completed_replay["status"] == "completed"
    assert completed_replay["result"]["analysis"]["signal_type"] == "feedback_loop"


def test_auto_optimize_creates_one_followup_feedback_task(client, owner_headers, test_db, monkeypatch):
    patch_worker_session(monkeypatch, test_db)

    response = client.post(
        "/api/business-webhooks/ecommerce/orders",
        headers=owner_headers,
        json={"order_id": "O-AUTO", "sku": "SKU-AUTO", "quantity": 1, "amount": 100.0, "auto_optimize": True},
    )
    assert response.status_code == 200

    assert worker.process_next_task() is True

    db = test_db()
    try:
        tasks = (
            db.query(TaskCenterTask)
            .filter(TaskCenterTask.source == "sprint18_business_loop")
            .order_by(TaskCenterTask.id.asc())
            .all()
        )
        assert len(tasks) == 2
        assert tasks[1].parent_task_id == tasks[0].id
        assert tasks[1].status == "assigned"
    finally:
        db.close()


def test_business_loop_read_requires_auth(client):
    response = client.get("/api/business-loop/results")
    assert response.status_code == 401


def login_owner(client):
    response = client.post("/api/login", json={"username": "owner", "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}
