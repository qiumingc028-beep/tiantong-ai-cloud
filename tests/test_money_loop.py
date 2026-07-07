def test_money_loop_requires_auth(client):
    response = client.post("/api/money/loop/start", json={"seed": {"topic": "AI赚钱"}, "cycles": 1})
    assert response.status_code == 401


def test_money_loop_start_runs_bounded_cycles_and_writes_results(client, owner_headers):
    response = client.post(
        "/api/money/loop/start",
        headers=owner_headers,
        json={
            "seed": {
                "topic": "夏季爆品",
                "keyword": "防晒衣",
                "sku": "SKU-MONEY",
                "stock": 80,
                "current_price": 99,
                "views": 2000,
                "likes": 160,
                "comments": 20,
                "shares": 10,
            },
            "cycles": 2,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert len(body["status"]["results"]) == 2
    assert len(body["task_ids"]) == 2
    first = body["status"]["results"][0]
    assert first["trend"]["heat_level"] == "high"
    assert first["content"]["engine"] == "content"
    assert first["publish_result"]["external_publish"] is False
    assert first["product_binding"]["auto_bind"] is True
    assert first["metrics"]["external_collection"] is False
    assert first["feedback"]["reusable_as_input"] is True
    assert first["external_actions"] == []


def test_money_loop_status_and_stop(client, owner_headers):
    start = client.post("/api/money/loop/start", headers=owner_headers, json={"seed": {"topic": "状态测试"}, "cycles": 1})
    assert start.status_code == 200

    status_response = client.get("/api/money/loop/status", headers=owner_headers)
    assert status_response.status_code == 200
    assert status_response.json()["status"]["running"] is True
    assert status_response.json()["status"]["external_execution"] is False

    stop_response = client.post("/api/money/loop/stop", headers=owner_headers)
    assert stop_response.status_code == 200
    assert stop_response.json()["status"]["running"] is False


def test_money_optimize_updates_strategy_and_writes_result(client, owner_headers):
    response = client.post(
        "/api/money/optimize",
        headers=owner_headers,
        json={"feedback": {"direction": "improve_hook_and_offer", "metrics": {"revenue": 80}}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["external_execution"] is False
    assert body["result"]["strategy"]["content_type"] == "xiaohongshu"
    assert body["task_id"]


def test_money_loop_accepts_api_key(client, monkeypatch):
    monkeypatch.setenv("AUTOMATION_API_KEY", "money-key")
    response = client.post(
        "/api/money/loop/start",
        headers={"X-API-Key": "money-key"},
        json={"seed": {"topic": "API Key 闭环", "views": 1000, "likes": 60}, "cycles": 1},
    )

    assert response.status_code == 200
    assert response.json()["status"]["results"][0]["publish_result"]["status"] == "published_mock"
