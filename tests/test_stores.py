def test_stores_requires_login(client):
    response = client.get("/api/stores")

    assert response.status_code == 401


def test_owner_can_list_stores(client, owner_headers):
    response = client.get("/api/stores", headers=owner_headers)

    assert response.status_code == 200
    stores = response.json()
    assert isinstance(stores, list)
    assert stores[0]["store_code"] == "JD01"


def test_low_privilege_user_cannot_list_stores(client, viewer_headers):
    response = client.get("/api/stores", headers=viewer_headers)

    assert response.status_code == 403
