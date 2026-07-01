from datetime import date

from backend.models import JdDailyMetric, MetricDaily


def test_jd_metrics_summary_requires_login(client):
    response = client.get("/api/jd/metrics/summary")

    assert response.status_code == 401


def test_owner_can_view_jd_metrics_summary(client, owner_headers):
    response = client.get("/api/jd/metrics/summary", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert {"today_gmv", "today_profit", "ad_spend", "roi", "stores"}.issubset(data)


def test_metrics_today_returns_store_rows(client, owner_headers):
    response = client.get("/api/metrics/today", headers=owner_headers)

    assert response.status_code == 200
    rows = response.json()
    assert isinstance(rows, list)
    assert rows[0]["store_code"] == "JD01"


def test_manual_metrics_requires_write_permission(client, viewer_headers):
    response = client.post(
        "/api/metrics/manual",
        headers=viewer_headers,
        json={"store_id": 1, "metric_date": date.today().isoformat(), "sales_amount": 100},
    )

    assert response.status_code == 403


def test_owner_can_write_manual_metrics_and_jd_daily_metrics(client, owner_headers, test_db):
    payload = {
        "store_id": 1,
        "metric_date": date.today().isoformat(),
        "sales_amount": 1000,
        "profit_amount": 200,
        "ad_spend": 100,
        "roi": 10,
        "orders_count": 20,
        "visitors_count": 300,
        "refunds_count": 1,
        "after_sales_count": 2,
        "favorites_count": 3,
        "cart_add_count": 4,
        "conversion_rate": 0.12,
    }

    response = client.post("/api/metrics/manual", headers=owner_headers, json=payload)

    assert response.status_code == 200
    db = test_db()
    try:
        assert db.query(MetricDaily).count() == 1
        jd_metric = db.query(JdDailyMetric).one()
        assert float(jd_metric.gmv) == 1000
        assert jd_metric.paid_orders_count == 20
    finally:
        db.close()


def test_low_privilege_authenticated_user_can_read_summary_current_policy(client, viewer_headers):
    response = client.get("/api/jd/metrics/summary", headers=viewer_headers)

    assert response.status_code == 200
