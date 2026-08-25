from backend.models import Store, User, UserStoreMembership
from backend.store_authorization import authorized_stores


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


def test_replacing_manager_revokes_only_assignment_managed_membership(
    client, owner_headers, operator_headers, test_db
):
    with test_db() as db:
        store_id = db.query(Store.id).filter(Store.store_code == "JD01").scalar()
        owner = db.query(User).filter(User.username == "owner").one()
        operator_id = db.query(User.id).filter(User.username == "operator").scalar()
        db.query(UserStoreMembership).filter(
            UserStoreMembership.user_id == operator_id,
            UserStoreMembership.store_id == store_id,
        ).update(
            {
                UserStoreMembership.active: True,
                UserStoreMembership.can_read: True,
                UserStoreMembership.can_write: False,
                UserStoreMembership.assignment_managed: False,
            }
        )
        db.commit()
        assert authorized_stores(db, owner, write=True).filter(Store.id == store_id).count() == 1

    client.cookies.clear()
    assigned = client.post(
        f"/api/stores/{store_id}/assign",
        headers=owner_headers,
        json={"manager_user_id": operator_id},
    )
    assert assigned.status_code == 200, assigned.text
    assert client.get("/api/stores", headers=operator_headers).status_code == 200

    cleared = client.post(
        f"/api/stores/{store_id}/assign",
        headers=owner_headers,
        json={"manager_user_id": None},
    )
    assert cleared.status_code == 200
    assert [row["id"] for row in client.get("/api/stores", headers=operator_headers).json()] == [store_id]
    denied_write = client.post(
        "/api/metrics/manual",
        headers=operator_headers,
        json={"store_id": store_id, "metric_date": "2026-08-10", "sales_amount": 1},
    )
    assert denied_write.status_code == 403

    with test_db() as db:
        membership = db.query(UserStoreMembership).filter(
            UserStoreMembership.user_id == operator_id,
            UserStoreMembership.store_id == store_id,
        ).one()
        assert membership.assignment_managed is False
        assert membership.active is True
        assert membership.can_read is True
        assert membership.can_write is False
        assert membership.assignment_previous_active is None
        assert membership.assignment_previous_can_read is None
        assert membership.assignment_previous_can_write is None
