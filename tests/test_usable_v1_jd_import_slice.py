from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import openpyxl

from backend.models import EmployeeLog, JdDailyMetric, MetricDaily, Permission, Role, Store, User


def test_rbac_guard_is_served_to_real_browser(client):
    response = client.get("/rbac-navigation.js")

    assert response.status_code == 200
    assert "TiantongRbac" in response.text


def test_owner_menu_returns_all_authorized_uat_pages(client, owner_headers, test_db):
    with test_db() as db:
        owner_role = db.query(Role).filter(Role.code == "owner").one()
        for code, name in (
            ("menu.ai_employees", "AI Employees"),
            ("menu.settings", "Settings"),
            ("menu.computer_executor", "Computer Executor"),
        ):
            permission = db.query(Permission).filter(Permission.code == code).one_or_none()
            if permission is None:
                permission = Permission(code=code, name=name)
                db.add(permission)
            if permission not in owner_role.permissions:
                owner_role.permissions.append(permission)
        db.commit()

    response = client.get("/api/me", headers=owner_headers)

    assert response.status_code == 200
    assert [(item["label"], item["href"]) for item in response.json()["menus"]] == [
        ("老板驾驶舱", "/"),
        ("店铺与数据", "/import.html"),
        ("经营中心", "/jd-dashboard.html"),
        ("AI员工名册", "/ai-employees.html"),
        ("电脑执行中心", "/computer-execution-center.html"),
        ("系统设置", "/settings.html"),
    ]
    permissions = [item["permission"] for item in response.json()["menus"]]
    assert len(permissions) == len(set(permissions))


def test_restricted_user_menu_keeps_unknown_permissions_fail_closed(client, test_db):
    with test_db() as db:
        viewer_role = db.query(Role).filter(Role.code == "viewer").one()
        unknown = Permission(code="menu.r178_unknown", name="R178 Unknown")
        viewer_role.permissions.append(unknown)
        db.add(unknown)
        db.commit()

    login = client.post("/api/login", json={"username": "viewer", "password": "password"})
    assert login.status_code == 200
    response = client.get("/api/me", headers={"Authorization": f"Bearer {login.json()['token']}"})

    assert response.status_code == 200
    assert response.json()["menus"] == []


def test_csv_import_reports_errors_blocks_duplicates_and_persists(client, owner_headers):
    csv_data = (
        "store_code,metric_date,sales_amount,profit_amount,ad_spend,roi,"
        "orders_count,visitors_count,favorites_count,cart_add_count,conversion_rate\n"
        "JD01,2026-08-08,500,120,50,10,5,80,8,6,0.0625\n"
        "JD01,2026-08-09,700,180,70,10,7,100,10,9,0.07\n"
        "JD01,2026-08-10,not-a-number,20,10,2,1,10,1,1,0.1\n"
    ).encode("utf-8")

    first = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        data={"store_id": "1"},
        files={"file": ("internal-test.csv", csv_data, "text/csv")},
    )
    assert first.status_code == 200
    assert {key: first.json()[key] for key in (
        "ok", "status", "total_rows", "success_rows", "failed_rows", "errors", "duplicate"
    )} == {
        "ok": True,
        "status": "partial_success",
        "total_rows": 3,
        "success_rows": 2,
        "failed_rows": 1,
        "errors": [{"row": 4, "reason": "销售额格式错误"}],
        "duplicate": False,
    }

    duplicate = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        data={"store_id": "1"},
        files={"file": ("internal-test.csv", csv_data, "text/csv")},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["success_rows"] == 2

    records = client.get("/api/metrics/import-records", headers=owner_headers)
    assert records.status_code == 200
    assert len(records.json()["records"]) == 1
    assert records.json()["records"][0]["status"] == "partial_success"

    business = client.get(
        "/api/business-center/metrics?store_id=1&date_from=2026-08-08&date_to=2026-08-09",
        headers=owner_headers,
    )
    assert business.status_code == 200
    assert business.json()["total"] == 2
    assert business.json()["summary"] == {
        "sales_amount": 1200.0,
        "orders_count": 12,
        "ad_spend": 120.0,
        "visitors_count": 180,
        "favorites_count": 18,
        "cart_add_count": 15,
    }

    dashboard = client.get(
        "/api/owner/dashboard?store_id=1&date_from=2026-08-08&date_to=2026-08-09",
        headers=owner_headers,
    )
    assert dashboard.status_code == 200
    assert dashboard.json()["today_sales"] == business.json()["summary"]["sales_amount"]
    assert dashboard.json()["orders"] == business.json()["summary"]["orders_count"]
    assert dashboard.json()["ad_spend"] == business.json()["summary"]["ad_spend"]


def test_xlsx_import_uses_selected_store(client, owner_headers):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["日期", "今日成交", "订单数", "广告花费", "访客数", "收藏", "加购", "转化率"])
    sheet.append(["2026-08-09", 880, 8, 88, 120, 12, 9, 0.0667])
    content = BytesIO()
    workbook.save(content)

    response = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        data={"store_id": "1"},
        files={"file": ("internal-test.xlsx", content.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["total_rows"] == response.json()["success_rows"] == 1
    assert response.json()["failed_rows"] == 0


def test_business_center_rejects_users_without_server_permission(client, viewer_headers):
    response = client.get("/api/business-center/metrics", headers=viewer_headers)

    assert response.status_code == 403


def test_import_rejects_unrecognized_schema_without_writing_metrics(client, owner_headers, test_db):
    response = client.post(
        "/api/metrics/import",
        headers=owner_headers,
        data={"store_id": "1"},
        files={"file": ("wrong.csv", b"foo\nbar\n", "text/csv")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "缺少必要字段：日期、销售额、订单量、广告消耗"
    with test_db() as db:
        assert db.query(MetricDaily).count() == 0
        assert db.query(JdDailyMetric).count() == 0


def test_concurrent_duplicate_import_is_claimed_once(client, owner_headers, test_db):
    csv_data = (
        "metric_date,sales_amount,ad_spend,orders_count\n"
        "2026-08-11,100,10,1\n"
    ).encode("utf-8")

    def upload():
        return client.post(
            "/api/metrics/import",
            headers=owner_headers,
            data={"store_id": "1"},
            files={"file": ("same.csv", csv_data, "text/csv")},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: upload(), range(2)))

    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()["duplicate"] for response in responses) == [False, True]
    with test_db() as db:
        assert db.query(MetricDaily).count() == 1
        assert db.query(JdDailyMetric).count() == 1
        assert db.query(EmployeeLog).filter(EmployeeLog.action.like("metrics_import:%")).count() == 1


def test_blank_required_values_do_not_overwrite_existing_metric(client, owner_headers):
    valid = b"metric_date,sales_amount,ad_spend,orders_count\n2026-08-12,321,32,3\n"
    blank = b"metric_date,sales_amount,ad_spend,orders_count\n2026-08-12,,,\n"
    for content in (valid, blank):
        response = client.post(
            "/api/metrics/import",
            headers=owner_headers,
            data={"store_id": "1"},
            files={"file": ("metrics.csv", content, "text/csv")},
        )
        assert response.status_code == 200

    assert response.json()["status"] == "failed"
    assert response.json()["errors"] == [{"row": 2, "reason": "销售额不能为空"}]
    business = client.get(
        "/api/business-center/metrics?store_id=1&date_from=2026-08-12&date_to=2026-08-12",
        headers=owner_headers,
    ).json()
    assert business["summary"]["sales_amount"] == 321.0
    assert business["summary"]["orders_count"] == 3
    assert business["summary"]["ad_spend"] == 32.0


def test_owner_cannot_write_store_without_explicit_membership(client, owner_headers, test_db):
    with test_db() as db:
        owner = db.query(User).filter(User.username == "owner").one()
        store = Store(platform="jd", store_code="UNAUTHORIZED", store_name="Unauthorized", tenant_id=owner.tenant_id, company_id=owner.company_id, active=True)
        db.add(store)
        db.commit()
        store_id = store.id

    response = client.post(
        "/api/metrics/manual",
        headers=owner_headers,
        json={
            "store_id": store_id,
            "metric_date": "2026-08-10",
            "sales_amount": 100,
        },
    )

    assert response.status_code == 403
    with test_db() as db:
        assert db.query(MetricDaily).filter(MetricDaily.store_id == store_id).count() == 0
