from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from backend.auth import hash_password
from backend.models import (
    AiProductAsset,
    AiProductDraft,
    Company,
    Store,
    Tenant,
    User,
    UserStoreMembership,
)


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 28
WEBP = b"RIFF" + (24).to_bytes(4, "little") + b"WEBP" + b"\x00" * 20


@pytest.fixture(autouse=True)
def product_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backend.routers.ai_product_assets.get_settings",
        lambda: SimpleNamespace(ASSET_STORAGE_ROOT=tmp_path),
    )
    return tmp_path


def _login(client, username: str) -> dict[str, str]:
    client.cookies.clear()
    response = client.post("/api/login", json={"username": username, "password": "password"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _record_asset(db, store: Store, user: User, marker: str) -> AiProductAsset:
    draft = AiProductDraft(
        tenant_id=str(store.tenant_id),
        shop_id=store.id,
        created_by=user.id,
        status="draft",
    )
    db.add(draft)
    db.flush()
    asset = AiProductAsset(
        draft_id=draft.id,
        tenant_id=str(store.tenant_id),
        shop_id=store.id,
        created_by=user.id,
        original_filename=f"{marker}.png",
        storage_key=marker.ljust(64, "0")[:64],
        mime_type="image/png",
        size_bytes=len(PNG),
        sha256=marker.ljust(64, "1")[:64],
        status="ready",
    )
    db.add(asset)
    db.flush()
    return asset


def _assert_store_denied(client, headers, store_id: int, asset_id: int, product_storage):
    before_files = {path for path in product_storage.rglob("*") if path.is_file()}
    assert store_id not in {
        row["id"]
        for row in client.get("/api/ai-products/shops", headers=headers).json()["shops"]
    }
    denied_upload = client.post(
        "/api/ai-products/assets",
        headers=headers,
        data={"shop_id": str(store_id), "tenant_id": "attacker", "company_id": "999"},
        files=[("files", ("forbidden.png", PNG, "image/png"))],
    )
    assert denied_upload.status_code == 403
    assert client.get(
        f"/api/ai-products/assets?shop_id={store_id}", headers=headers
    ).status_code == 403
    assert asset_id not in {
        row["id"]
        for row in client.get("/api/ai-products/assets", headers=headers).json()["assets"]
    }
    assert client.get(
        f"/api/ai-products/assets/{asset_id}", headers=headers
    ).status_code == 404
    assert {path for path in product_storage.rglob("*") if path.is_file()} == before_files


def test_owner_can_upload_product_asset_and_read_it_after_refresh(client, owner_headers):
    upload = client.post(
        "/api/ai-products/assets",
        headers=owner_headers,
        data={"shop_id": "1"},
        files=[("files", ("hero.png", BytesIO(PNG), "image/png"))],
    )

    assert upload.status_code == 201
    asset = upload.json()["assets"][0]
    assert asset["original_filename"] == "hero.png"
    assert asset["mime_type"] == "image/png"
    assert asset["size_bytes"] == len(PNG)

    refreshed = client.get("/api/ai-products/assets", headers=owner_headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["assets"] == [asset]
    assert client.get(f"/api/ai-products/assets/{asset['id']}", headers=owner_headers).json() == asset
    assert "tenant_id" not in asset
    assert "storage_key" not in asset


def test_admin_access_is_limited_to_explicitly_authorized_stores(
    client, admin_headers, test_db, product_storage
):
    with test_db() as db:
        admin = db.query(User).filter(User.username == "admin").one()
        owner = db.query(User).filter(User.username == "owner").one()
        authorized_store = db.get(Store, 1)
        assert admin.role == "admin"
        assert admin.id != owner.id
        assert {
            membership.store_id
            for membership in db.query(UserStoreMembership)
            .filter(UserStoreMembership.user_id == admin.id)
            .all()
        } == {authorized_store.id}

        unauthorized_store = Store(
            store_code="ADMIN-NO-MEMBERSHIP",
            store_name="Admin No Membership",
            tenant_id=admin.tenant_id,
            company_id=admin.company_id,
            active=True,
        )
        db.add(unauthorized_store)
        db.flush()
        authorized_asset = _record_asset(db, authorized_store, admin, "admin-authorized")
        unauthorized_asset = _record_asset(db, unauthorized_store, admin, "admin-denied")
        db.commit()
        authorized_store_id = authorized_store.id
        unauthorized_store_id = unauthorized_store.id
        authorized_asset_id = authorized_asset.id
        unauthorized_asset_id = unauthorized_asset.id

    shops = client.get("/api/ai-products/shops", headers=admin_headers)
    assert shops.status_code == 200
    shop_ids = {row["id"] for row in shops.json()["shops"]}
    assert authorized_store_id in shop_ids
    assert unauthorized_store_id not in shop_ids

    upload = client.post(
        "/api/ai-products/assets",
        headers=admin_headers,
        data={"shop_id": str(authorized_store_id)},
        files=[("files", ("admin.png", PNG, "image/png"))],
    )
    assert upload.status_code == 201
    uploaded_asset_id = upload.json()["assets"][0]["id"]

    listed = client.get(
        f"/api/ai-products/assets?shop_id={authorized_store_id}", headers=admin_headers
    )
    assert listed.status_code == 200
    assert {authorized_asset_id, uploaded_asset_id}.issubset(
        {row["id"] for row in listed.json()["assets"]}
    )
    assert client.get(
        f"/api/ai-products/assets/{authorized_asset_id}", headers=admin_headers
    ).status_code == 200

    _assert_store_denied(
        client,
        admin_headers,
        unauthorized_store_id,
        unauthorized_asset_id,
        product_storage,
    )


def test_product_asset_routes_require_login(client):
    assert client.get("/api/ai-products/shops").status_code == 401
    assert client.get("/api/ai-products/assets").status_code == 401
    assert client.get("/api/ai-products/assets/1").status_code == 401


def test_owner_cannot_enumerate_upload_list_or_read_cross_tenant_assets(
    client, owner_headers, test_db, product_storage
):
    with test_db() as db:
        tenant_b = Tenant(tenant_code="tenant-b", tenant_name="Tenant B", active=True)
        db.add(tenant_b)
        db.flush()
        company_b = Company(
            tenant_id=tenant_b.id,
            company_code="company-b",
            company_name="Company B",
            active=True,
        )
        db.add(company_b)
        db.flush()
        owner_b = User(
            username="owner-b",
            password_hash=hash_password("password"),
            role="owner",
            display_name="Owner B",
            tenant_id=tenant_b.id,
            company_id=company_b.id,
            active=True,
        )
        store_b = Store(
            platform="jd",
            store_code="B-STORE",
            store_name="Store B",
            tenant_id=tenant_b.id,
            company_id=company_b.id,
            active=True,
        )
        db.add_all([owner_b, store_b])
        db.flush()
        db.add(
            UserStoreMembership(
                user_id=owner_b.id,
                store_id=store_b.id,
                can_read=True,
                can_write=True,
                active=True,
            )
        )
        db.commit()
        store_b_id = store_b.id

    client.cookies.clear()
    owner_b_login = client.post(
        "/api/login", json={"username": "owner-b", "password": "password"}
    )
    assert owner_b_login.status_code == 200
    owner_b_headers = {"Authorization": f"Bearer {owner_b_login.json()['token']}"}
    client.cookies.clear()
    uploaded_b = client.post(
        "/api/ai-products/assets",
        headers=owner_b_headers,
        data={"shop_id": str(store_b_id)},
        files=[("files", ("tenant-b.png", PNG, "image/png"))],
    )
    assert uploaded_b.status_code == 201
    asset_b_id = uploaded_b.json()["assets"][0]["id"]

    before_files = {path for path in product_storage.rglob("*") if path.is_file()}
    with test_db() as db:
        before_drafts = db.query(AiProductDraft).count()
        before_assets = db.query(AiProductAsset).count()

    client.cookies.clear()
    shops_a = client.get("/api/ai-products/shops", headers=owner_headers)
    assert store_b_id not in {row["id"] for row in shops_a.json()["shops"]}
    denied_upload = client.post(
        "/api/ai-products/assets",
        headers=owner_headers,
        data={"shop_id": str(store_b_id), "tenant_id": "tenant-b"},
        files=[("files", ("forbidden.png", PNG, "image/png"))],
    )
    assert denied_upload.status_code in {403, 404}
    assert client.get(
        f"/api/ai-products/assets?shop_id={store_b_id}", headers=owner_headers
    ).status_code in {403, 404}
    assert asset_b_id not in {
        row["id"]
        for row in client.get("/api/ai-products/assets", headers=owner_headers).json()["assets"]
    }
    assert client.get(
        f"/api/ai-products/assets/{asset_b_id}", headers=owner_headers
    ).status_code in {403, 404}

    with test_db() as db:
        assert db.query(AiProductDraft).count() == before_drafts
        assert db.query(AiProductAsset).count() == before_assets
    assert {path for path in product_storage.rglob("*") if path.is_file()} == before_files


def test_owner_cannot_access_same_tenant_unassigned_cross_company_or_inactive_stores(
    client, owner_headers, test_db, product_storage
):
    with test_db() as db:
        owner = db.query(User).filter(User.username == "owner").one()
        tenant = db.get(Tenant, owner.tenant_id)
        same_company = db.get(Company, owner.company_id)
        other_company = Company(
            tenant_id=tenant.id,
            company_code="other-company",
            company_name="Other Company",
            active=True,
        )
        db.add(other_company)
        db.flush()
        stores = [
            Store(
                store_code="NO-MEMBERSHIP",
                store_name="No Membership",
                tenant_id=tenant.id,
                company_id=same_company.id,
                active=True,
            ),
            Store(
                store_code="CROSS-COMPANY",
                store_name="Cross Company",
                tenant_id=tenant.id,
                company_id=other_company.id,
                active=True,
            ),
            Store(
                store_code="INACTIVE-STORE",
                store_name="Inactive Store",
                tenant_id=tenant.id,
                company_id=same_company.id,
                active=False,
            ),
            Store(
                store_code="INACTIVE-MEMBERSHIP",
                store_name="Inactive Membership",
                tenant_id=tenant.id,
                company_id=same_company.id,
                active=True,
            ),
        ]
        db.add_all(stores)
        db.flush()
        db.add_all(
            [
                UserStoreMembership(
                    user_id=owner.id,
                    store_id=stores[1].id,
                    can_read=True,
                    can_write=True,
                    active=True,
                ),
                UserStoreMembership(
                    user_id=owner.id,
                    store_id=stores[2].id,
                    can_read=True,
                    can_write=True,
                    active=True,
                ),
                UserStoreMembership(
                    user_id=owner.id,
                    store_id=stores[3].id,
                    can_read=True,
                    can_write=True,
                    active=False,
                ),
            ]
        )
        assets = [
            _record_asset(db, store, owner, f"scope-{index}")
            for index, store in enumerate(stores)
        ]
        db.commit()
        denied = [(store.id, asset.id) for store, asset in zip(stores, assets, strict=True)]
        expected_drafts = db.query(AiProductDraft).count()
        expected_assets = db.query(AiProductAsset).count()

    for store_id, asset_id in denied:
        _assert_store_denied(client, owner_headers, store_id, asset_id, product_storage)

    with test_db() as db:
        assert db.query(AiProductDraft).count() == expected_drafts
        assert db.query(AiProductAsset).count() == expected_assets


def test_read_only_membership_can_list_and_read_but_cannot_upload(
    client, owner_headers, test_db, product_storage
):
    with test_db() as db:
        owner = db.query(User).filter(User.username == "owner").one()
        store = Store(
            store_code="READ-ONLY",
            store_name="Read Only",
            tenant_id=owner.tenant_id,
            company_id=owner.company_id,
            active=True,
        )
        db.add(store)
        db.flush()
        db.add(
            UserStoreMembership(
                user_id=owner.id,
                store_id=store.id,
                can_read=True,
                can_write=False,
                active=True,
            )
        )
        asset = _record_asset(db, store, owner, "read-only")
        db.commit()
        store_id = store.id
        asset_id = asset.id
        before_drafts = db.query(AiProductDraft).count()
        before_assets = db.query(AiProductAsset).count()

    shops = client.get("/api/ai-products/shops", headers=owner_headers)
    assert store_id in {row["id"] for row in shops.json()["shops"]}
    listed = client.get(
        f"/api/ai-products/assets?shop_id={store_id}", headers=owner_headers
    )
    assert listed.status_code == 200
    assert asset_id in {row["id"] for row in listed.json()["assets"]}
    assert client.get(
        f"/api/ai-products/assets/{asset_id}", headers=owner_headers
    ).status_code == 200
    assert client.post(
        "/api/ai-products/assets",
        headers=owner_headers,
        data={"shop_id": str(store_id)},
        files=[("files", ("forbidden.png", PNG, "image/png"))],
    ).status_code == 403
    with test_db() as db:
        assert db.query(AiProductDraft).count() == before_drafts
        assert db.query(AiProductAsset).count() == before_assets
    assert [path for path in product_storage.rglob("*") if path.is_file()] == []


@pytest.mark.parametrize("inactive_scope", ["tenant", "company"])
def test_inactive_tenant_or_company_denies_asset_access(
    client, test_db, product_storage, inactive_scope
):
    with test_db() as db:
        tenant = Tenant(
            tenant_code=f"inactive-{inactive_scope}",
            tenant_name=f"Inactive {inactive_scope}",
            active=inactive_scope != "tenant",
        )
        db.add(tenant)
        db.flush()
        company = Company(
            tenant_id=tenant.id,
            company_code=f"inactive-{inactive_scope}",
            company_name=f"Inactive {inactive_scope}",
            active=inactive_scope != "company",
        )
        db.add(company)
        db.flush()
        owner = User(
            username=f"inactive-{inactive_scope}-owner",
            password_hash=hash_password("password"),
            role="owner",
            display_name="Inactive Scope Owner",
            tenant_id=tenant.id,
            company_id=company.id,
            active=True,
        )
        store = Store(
            store_code=f"INACTIVE-{inactive_scope.upper()}",
            store_name="Inactive Scope Store",
            tenant_id=tenant.id,
            company_id=company.id,
            active=True,
        )
        db.add_all([owner, store])
        db.flush()
        db.add(
            UserStoreMembership(
                user_id=owner.id,
                store_id=store.id,
                can_read=True,
                can_write=True,
                active=True,
            )
        )
        asset = _record_asset(db, store, owner, f"inactive-{inactive_scope}")
        db.commit()
        username = owner.username
        store_id = store.id
        asset_id = asset.id
        expected_drafts = db.query(AiProductDraft).count()
        expected_assets = db.query(AiProductAsset).count()

    headers = _login(client, username)
    _assert_store_denied(client, headers, store_id, asset_id, product_storage)
    with test_db() as db:
        assert db.query(AiProductDraft).count() == expected_drafts
        assert db.query(AiProductAsset).count() == expected_assets


def test_available_shops_require_server_side_membership(client, viewer_headers, test_db):
    with test_db() as db:
        viewer = db.query(User).filter(User.username == "viewer").one()
        assigned = Store(store_code="JD02", store_name="Assigned", manager_user_id=viewer.id, tenant_id=viewer.tenant_id, company_id=viewer.company_id, active=True)
        unassigned = Store(store_code="JD03", store_name="Unassigned", tenant_id=viewer.tenant_id, company_id=viewer.company_id, active=True)
        db.add_all([assigned, unassigned])
        db.flush()
        db.add(
            UserStoreMembership(
                user_id=viewer.id,
                store_id=assigned.id,
                can_read=True,
                can_write=False,
                active=True,
            )
        )
        db.commit()
        assigned_id = assigned.id
        unassigned_id = unassigned.id

    shops = client.get("/api/ai-products/shops", headers=viewer_headers)
    assert shops.status_code == 200
    assert [row["id"] for row in shops.json()["shops"]] == [assigned_id]

    read_only_denied = client.post(
        "/api/ai-products/assets",
        headers=viewer_headers,
        data={"shop_id": str(assigned_id)},
        files=[("files", ("hero.png", PNG, "image/png"))],
    )
    assert read_only_denied.status_code == 403

    unassigned_denied = client.post(
        "/api/ai-products/assets",
        headers=viewer_headers,
        data={"shop_id": str(unassigned_id), "tenant_id": "attacker"},
        files=[("files", ("hero.png", PNG, "image/png"))],
    )
    assert unassigned_denied.status_code == 403


def test_client_cannot_select_tenant_and_other_tenant_rows_fail_closed(
    client, owner_headers, test_db
):
    uploaded = client.post(
        "/api/ai-products/assets",
        headers=owner_headers,
        data={"shop_id": "1", "tenant_id": "attacker"},
        files=[("files", ("hero.png", PNG, "image/png"))],
    )
    assert uploaded.status_code == 201
    with test_db() as db:
        saved = db.query(AiProductAsset).filter(AiProductAsset.id == uploaded.json()["assets"][0]["id"]).one()
        store = db.get(Store, saved.shop_id)
        assert saved.tenant_id == str(store.tenant_id)
        alien_draft = AiProductDraft(tenant_id="other", shop_id=1, created_by=1, status="draft")
        db.add(alien_draft)
        db.flush()
        alien = AiProductAsset(
            draft_id=alien_draft.id,
            tenant_id="other",
            shop_id=1,
            created_by=1,
            original_filename="alien.png",
            storage_key="a" * 64,
            mime_type="image/png",
            size_bytes=len(PNG),
            sha256="b" * 64,
            status="ready",
        )
        db.add(alien)
        db.commit()
        alien_id = alien.id

    listed_ids = [row["id"] for row in client.get("/api/ai-products/assets", headers=owner_headers).json()["assets"]]
    assert alien_id not in listed_ids
    assert client.get(f"/api/ai-products/assets/{alien_id}", headers=owner_headers).status_code == 404


def test_jpeg_png_and_webp_are_accepted_and_storage_keys_are_opaque(
    client, owner_headers, test_db, product_storage
):
    response = client.post(
        "/api/ai-products/assets",
        headers=owner_headers,
        data={"shop_id": "1"},
        files=[
            ("files", ("one.jpg", JPEG, "image/jpeg")),
            ("files", ("two.png", PNG, "image/png")),
            ("files", ("three.webp", WEBP, "image/webp")),
        ],
    )
    assert response.status_code == 201
    with test_db() as db:
        rows = db.query(AiProductAsset).order_by(AiProductAsset.id).all()
        store = db.get(Store, 1)
        assert all(len(row.storage_key) == 64 and row.original_filename not in row.storage_key for row in rows)
        stored = [path for path in product_storage.rglob("*") if path.is_file()]
        assert {path.name for path in stored} == {row.storage_key for row in rows}
        assert {path.parent.relative_to(product_storage).as_posix() for path in stored} == {
            f"{store.tenant_id}/1"
        }


@pytest.mark.parametrize(
    ("filename", "content", "mime", "expected_status"),
    [
        ("empty.png", b"", "image/png", 400),
        ("spoof.png", b"not a png", "image/png", 400),
        ("mismatch.png", PNG, "image/jpeg", 400),
        ("photo.jpg.exe", JPEG, "image/jpeg", 400),
        ("photo.png.jpg", JPEG, "image/jpeg", 400),
        ("../photo.png", PNG, "image/png", 400),
        ("..\\photo.png", PNG, "image/png", 400),
        ("danger<script>.png", PNG, "image/png", 400),
        ("archive.zip", b"PK\x03\x04", "application/zip", 400),
    ],
)
def test_unsafe_or_inconsistent_uploads_are_rejected_without_artifacts(
    client, owner_headers, product_storage, filename, content, mime, expected_status
):
    response = client.post(
        "/api/ai-products/assets",
        headers=owner_headers,
        data={"shop_id": "1"},
        files=[("files", (filename, content, mime))],
    )
    assert response.status_code == expected_status
    assert [path for path in product_storage.rglob("*") if path.is_file()] == []


def test_upload_limits_are_enforced_without_artifacts(client, owner_headers, product_storage):
    maximum = client.post(
        "/api/ai-products/assets",
        headers=owner_headers,
        data={"shop_id": "1"},
        files=[("files", (f"{index}.png", PNG, "image/png")) for index in range(9)],
    )
    assert maximum.status_code == 201
    assert len(maximum.json()["assets"]) == 9
    for path in product_storage.rglob("*"):
        if not path.is_file():
            continue
        path.unlink()

    too_many = client.post(
        "/api/ai-products/assets",
        headers=owner_headers,
        data={"shop_id": "1"},
        files=[("files", (f"{index}.png", PNG, "image/png")) for index in range(10)],
    )
    assert too_many.status_code == 400

    too_large = client.post(
        "/api/ai-products/assets",
        headers=owner_headers,
        data={"shop_id": "1"},
        files=[("files", ("huge.png", PNG + b"x" * (10 * 1024 * 1024), "image/png"))],
    )
    assert too_large.status_code == 413
    assert [path for path in product_storage.rglob("*") if path.is_file()] == []


def test_one_invalid_file_rejects_whole_request_without_partial_artifacts(
    client, owner_headers, test_db, product_storage
):
    response = client.post(
        "/api/ai-products/assets",
        headers=owner_headers,
        data={"shop_id": "1"},
        files=[
            ("files", ("valid.png", PNG, "image/png")),
            ("files", ("spoof.png", b"not png", "image/png")),
        ],
    )
    assert response.status_code == 400
    assert [path for path in product_storage.rglob("*") if path.is_file()] == []
    with test_db() as db:
        assert db.query(AiProductDraft).count() == 0


def test_database_failure_removes_written_files_and_metadata(
    client, owner_headers, test_db, product_storage
):
    def fail_commit(_session):
        raise RuntimeError("simulated database failure")

    event.listen(test_db.class_, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="simulated database failure"):
            client.post(
                "/api/ai-products/assets",
                headers=owner_headers,
                data={"shop_id": "1"},
                files=[("files", ("hero.png", PNG, "image/png"))],
            )
    finally:
        event.remove(test_db.class_, "before_commit", fail_commit)

    assert [path for path in product_storage.rglob("*") if path.is_file()] == []
    with test_db() as db:
        assert db.query(AiProductDraft).count() == 0
        assert db.query(AiProductAsset).count() == 0


def test_storage_failure_removes_earlier_files_and_metadata(
    client, owner_headers, test_db, product_storage, monkeypatch
):
    real_open = Path.open
    calls = 0

    def fail_second_open(path, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated storage failure")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_second_open)
    with pytest.raises(OSError, match="simulated storage failure"):
        client.post(
            "/api/ai-products/assets",
            headers=owner_headers,
            data={"shop_id": "1"},
            files=[
                ("files", ("one.png", PNG, "image/png")),
                ("files", ("two.png", PNG, "image/png")),
            ],
        )

    assert [path for path in product_storage.rglob("*") if path.is_file()] == []
    with test_db() as db:
        assert db.query(AiProductDraft).count() == 0
        assert db.query(AiProductAsset).count() == 0
