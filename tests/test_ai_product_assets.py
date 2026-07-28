from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from backend.models import AiProductAsset, AiProductDraft, Store, User


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


def test_product_asset_routes_require_login(client):
    assert client.get("/api/ai-products/shops").status_code == 401
    assert client.get("/api/ai-products/assets").status_code == 401
    assert client.get("/api/ai-products/assets/1").status_code == 401


def test_available_shops_use_server_side_manager_assignment(client, viewer_headers, test_db):
    with test_db() as db:
        viewer = db.query(User).filter(User.username == "viewer").one()
        assigned = Store(store_code="JD02", store_name="Assigned", manager_user_id=viewer.id, active=True)
        unassigned = Store(store_code="JD03", store_name="Unassigned", active=True)
        db.add_all([assigned, unassigned])
        db.commit()
        assigned_id = assigned.id
        unassigned_id = unassigned.id

    shops = client.get("/api/ai-products/shops", headers=viewer_headers)
    assert shops.status_code == 200
    assert [row["id"] for row in shops.json()["shops"]] == [assigned_id]

    denied = client.post(
        "/api/ai-products/assets",
        headers=viewer_headers,
        data={"shop_id": str(unassigned_id), "tenant_id": "attacker"},
        files=[("files", ("hero.png", PNG, "image/png"))],
    )
    assert denied.status_code == 404


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
        assert saved.tenant_id == "tiantong"
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
        assert all(len(row.storage_key) == 64 and row.original_filename not in row.storage_key for row in rows)
        stored = [path for path in product_storage.rglob("*") if path.is_file()]
        assert {path.name for path in stored} == {row.storage_key for row in rows}
        assert {path.parent.relative_to(product_storage).as_posix() for path in stored} == {
            "tiantong/1"
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
