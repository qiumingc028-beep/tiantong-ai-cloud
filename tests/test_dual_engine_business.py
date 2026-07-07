def test_dual_engine_requires_auth(client):
    response = client.post(
        "/api/business/ecommerce/orders",
        json={"data": {"order_id": "O-1", "sku": "SKU-1", "amount": 99}},
    )
    assert response.status_code == 401


def test_ecommerce_order_engine_writes_result_with_api_key(client, monkeypatch):
    monkeypatch.setenv("AUTOMATION_API_KEY", "dual-key")
    headers = {"X-API-Key": "dual-key"}

    response = client.post(
        "/api/business/ecommerce/orders",
        headers=headers,
        json={"data": {"order_id": "O-18", "sku": "SKU-18", "quantity": 2, "amount": 200}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "ecommerce"
    assert body["result"]["pricing"]["auto_apply"] is False
    assert body["result"]["product_strategy"]["auto_modify_inventory"] is False

    lake = client.get("/api/business/data-lake", headers=headers)
    assert lake.status_code == 200
    assert any(row["event_type"] == "ecommerce_order" for row in lake.json()["orders"])


def test_ecommerce_metrics_decision_contains_pricing_and_inventory(client, owner_headers):
    response = client.post(
        "/api/business/ecommerce/metrics",
        headers=owner_headers,
        json={
            "data": {
                "sku": "SKU-M",
                "sales": 140,
                "stock": 12,
                "profit_margin": 0.31,
                "conversion_rate": 0.09,
                "current_price": 88,
            }
        },
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["product_strategy"]["strategy_tier"] == "hero_product"
    assert result["product_strategy"]["inventory_strategy"]["status"] == "low_stock"
    assert result["pricing"]["requires_human_review"] is True


def test_content_video_and_xiaohongshu_generation_are_internal_only(client, owner_headers):
    video = client.post(
        "/api/content/generate/video",
        headers=owner_headers,
        json={"data": {"topic": "夏季爆品", "product_name": "防晒衣", "views": 5000, "likes": 260}},
    )
    note = client.post(
        "/api/content/generate/xiaohongshu",
        headers=owner_headers,
        json={"data": {"topic": "通勤穿搭", "product_name": "轻薄外套"}},
    )

    assert video.status_code == 200
    assert video.json()["result"]["script"]["auto_publish"] is False
    assert note.status_code == 200
    assert note.json()["result"]["note"]["auto_publish"] is False


def test_content_trend_and_decision_center(client, owner_headers):
    trend = client.post(
        "/api/content/analyze/trend",
        headers=owner_headers,
        json={"data": {"keyword": "AI选品", "views": 1000, "likes": 80, "comments": 20, "shares": 10}},
    )
    decision = client.post(
        "/api/business/decision-center",
        headers=owner_headers,
        json={"data": {"topic": "AI选品", "content_type": "video"}},
    )

    assert trend.status_code == 200
    assert trend.json()["result"]["heat_level"] == "high"
    assert decision.status_code == 200
    assert decision.json()["result"]["engine"] == "content"
    assert decision.json()["result"]["external_execution"] is False


def test_dual_engine_decision_combines_ecommerce_and_content(client, owner_headers):
    response = client.post(
        "/api/business/ecommerce/decision",
        headers=owner_headers,
        json={
            "data": {
                "ecommerce": {"sku": "SKU-D", "sales": 20, "stock": 180, "current_price": 69},
                "content": {"topic": "库存清理", "content_type": "xiaohongshu", "views": 900, "likes": 40},
            }
        },
    )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["mode"] == "dual_engine"
    assert result["ecommerce"]["engine"] == "ecommerce"
    assert result["content"]["engine"] == "content"
    assert result["closed_loop"]["execution"] == "internal_task_result_writeback"
