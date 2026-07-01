def test_jd_dashboard_requires_login(client):
    response = client.get("/api/jd/dashboard")

    assert response.status_code == 401


def test_owner_can_open_jd_dashboard_api(client, owner_headers):
    response = client.get("/api/jd/dashboard", headers=owner_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert isinstance(data["stores"], list)
    assert data["stores"][0]["store_code"] == "JD01"


def test_low_privilege_user_cannot_open_jd_dashboard_api(client, viewer_headers):
    response = client.get("/api/jd/dashboard", headers=viewer_headers)

    assert response.status_code == 403
