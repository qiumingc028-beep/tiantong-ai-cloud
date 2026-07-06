from backend.routers.metrics import MAX_IMPORT_FILE_SIZE


def test_metrics_import_requires_login(client):
    response = client.post(
        "/api/metrics/import",
        files={"file": ("metrics.csv", b"store_code,sales_amount\nJD01,100\n", "text/csv")},
    )

    assert response.status_code == 401


def test_metrics_import_rejects_unsupported_file_type(client, owner_headers):
    response = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        files={"file": ("metrics.txt", b"store_code,sales_amount\nJD01,100\n", "text/plain")},
    )

    assert response.status_code == 400


def test_owner_can_import_metrics_csv(client, owner_headers):
    csv_data = (
        "store_code,metric_date,sales_amount,profit_amount,ad_spend,roi,"
        "orders_count,visitors_count,refunds_count,after_sales_count\n"
        "JD01,2026-06-30,500,120,50,10,5,80,0,1\n"
    ).encode("utf-8")

    response = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        files={"file": ("metrics.csv", csv_data, "text/csv")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["imported"] == 1
    assert data["errors"] == []


def test_metrics_import_rejects_oversized_file(client, owner_headers):
    oversized = b"store_code,sales_amount\n" + (b"JD01,1\n" * ((MAX_IMPORT_FILE_SIZE // 7) + 1))

    response = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        files={"file": ("large.csv", oversized, "text/csv")},
    )

    assert response.status_code == 413
