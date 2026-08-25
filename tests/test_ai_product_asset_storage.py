from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.config import ConfigurationError, Settings
from backend.models import Store


PRODUCTION_ENV = {
    "APP_ENV": "production",
    "SERVICE_ROLE": "backend",
    "DATABASE_URL": "postgresql+psycopg2://app:test-password@postgres:5432/app",
    "REDIS_URL": "redis://:test-password@redis:6379/0",
    "JWT_SECRET": "isolated-production-policy-jwt-secret-32-plus",
    "BOSS_INITIAL_PASSWORD": "isolated-boss-password",
    "CORS_ALLOWED_ORIGINS": "https://app.example.com",
}


def _production_settings(monkeypatch, asset_root):
    for key, value in PRODUCTION_ENV.items():
        monkeypatch.setenv(key, value)
    if asset_root is None:
        monkeypatch.delenv("ASSET_STORAGE_ROOT", raising=False)
    else:
        monkeypatch.setenv("ASSET_STORAGE_ROOT", asset_root)
    return Settings()


@pytest.mark.parametrize(
    "asset_root",
    ["", "artifacts/product-assets", "/app/assets", "/data/../app/assets", "/"],
)
def test_production_requires_a_safe_absolute_asset_storage_root(monkeypatch, asset_root):
    with pytest.raises(ConfigurationError, match="ASSET_STORAGE_ROOT"):
        _production_settings(monkeypatch, asset_root)


def test_production_defaults_to_dedicated_absolute_asset_storage_root(monkeypatch):
    settings = _production_settings(monkeypatch, None)

    assert settings.ASSET_STORAGE_ROOT == Path("/data/product-assets")


def test_production_accepts_dedicated_absolute_asset_storage_root(monkeypatch):
    settings = _production_settings(monkeypatch, "/data/product-assets")

    assert settings.ASSET_STORAGE_ROOT == Path("/data/product-assets")


def test_backend_dockerfile_prepares_asset_directory_for_runtime_user():
    dockerfile = Path("Dockerfile.backend").read_text()

    assert "install -d -o 10001 -g 10001 -m 0750 /data/product-assets" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "chmod -R a-w /app" in dockerfile


@pytest.mark.parametrize("compose_file", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_backend_compose_uses_dedicated_persistent_asset_volume(compose_file):
    compose = Path(compose_file).read_text()

    assert "ASSET_STORAGE_ROOT: /data/product-assets" in compose
    assert "product_assets:/data/product-assets" in compose
    assert "\n  product_assets:" in compose


def test_symlinked_storage_root_is_rejected(client, owner_headers, tmp_path, monkeypatch):
    actual_root = tmp_path / "actual"
    actual_root.mkdir()
    symlink_root = tmp_path / "linked"
    symlink_root.symlink_to(actual_root, target_is_directory=True)
    monkeypatch.setattr(
        "backend.routers.ai_product_assets.get_settings",
        lambda: SimpleNamespace(ASSET_STORAGE_ROOT=symlink_root),
    )

    response = client.post(
        "/api/ai-products/assets",
        headers=owner_headers,
        data={"shop_id": "1"},
        files=[("files", ("hero.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 24, "image/png"))],
    )

    assert response.status_code == 500
    assert list(actual_root.iterdir()) == []


def test_symlink_escape_below_storage_root_is_rejected(
    client, owner_headers, test_db, tmp_path, monkeypatch
):
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    escaped = tmp_path / "escaped"
    escaped.mkdir()
    with test_db() as db:
        tenant_key = str(db.get(Store, 1).tenant_id)
    (storage_root / tenant_key).symlink_to(escaped, target_is_directory=True)
    monkeypatch.setattr(
        "backend.routers.ai_product_assets.get_settings",
        lambda: SimpleNamespace(ASSET_STORAGE_ROOT=storage_root),
    )

    response = client.post(
        "/api/ai-products/assets",
        headers=owner_headers,
        data={"shop_id": "1"},
        files=[("files", ("hero.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 24, "image/png"))],
    )

    assert response.status_code == 500
    assert list(escaped.iterdir()) == []
