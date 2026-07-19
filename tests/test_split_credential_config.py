import importlib
import os
from urllib.parse import unquote, urlsplit

import pytest
import redis
from sqlalchemy.engine import make_url

from backend.config import ConfigurationError, Settings, get_settings

ALL_KEYS = (
    "APP_ENV", "ENV", "SERVICE_ROLE", "DATABASE_URL", "REDIS_URL",
    "DATABASE_HOST", "DATABASE_PORT", "DATABASE_NAME", "DATABASE_USER", "DATABASE_PASSWORD",
    "REDIS_HOST", "REDIS_PORT", "REDIS_DB", "REDIS_USERNAME", "REDIS_PASSWORD",
    "JWT_SECRET", "BOSS_INITIAL_PASSWORD", "CORS_ALLOWED_ORIGINS",
    "AGENT_RUNTIME_ENABLED", "ALPHA_WORKFLOW_ENABLED", "ALPHA_SCENARIO_ENABLED",
    "ALPHA_WORKFLOW_DASHBOARD_ENABLED", "ALPHA_DASHBOARD_ENABLED",
)

DATABASE_EDGE_PASSWORD = " 前 空格@:/?#%+\中文ß尾 "
REDIS_EDGE_USERNAME = " 前用户@:/?#%+\中文ß尾 "
REDIS_EDGE_PASSWORD = " 前密码@:/?#%+\中文ß尾 "


def reset_env(monkeypatch, **overrides):
    get_settings.cache_clear()
    for key in ALL_KEYS:
        monkeypatch.delenv(key, raising=False)
    values = {
        "APP_ENV": "production",
        "SERVICE_ROLE": "backend",
        "JWT_SECRET": "isolated-production-policy-jwt-secret-32-plus",
        "BOSS_INITIAL_PASSWORD": "isolated-boss-password",
        "CORS_ALLOWED_ORIGINS": "https://app.example.com",
        "DATABASE_URL": "postgresql+psycopg2://legacy-user:legacy-password@legacy-db:5432/legacy_name",
        "REDIS_URL": "redis://:legacy-password@legacy-redis:6379/5",
        "AGENT_RUNTIME_ENABLED": "false",
        "ALPHA_WORKFLOW_ENABLED": "false",
        "ALPHA_SCENARIO_ENABLED": "false",
        "ALPHA_WORKFLOW_DASHBOARD_ENABLED": "false",
        "ALPHA_DASHBOARD_ENABLED": "false",
    }
    values.update(overrides)
    for key, value in values.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


def assert_no_secret_leak(message: str, *secrets: str):
    for secret in secrets:
        assert secret not in message


def test_legacy_database_url_compatible(monkeypatch):
    reset_env(monkeypatch)
    assert Settings().DATABASE_URL == "postgresql+psycopg2://legacy-user:legacy-password@legacy-db:5432/legacy_name"


def test_legacy_redis_url_compatible(monkeypatch):
    reset_env(monkeypatch)
    assert Settings().REDIS_URL == "redis://:legacy-password@legacy-redis:6379/5"


def test_postgresql_split_fields_build_database_url(monkeypatch):
    reset_env(
        monkeypatch,
        DATABASE_HOST="pg.internal",
        DATABASE_PORT="6543",
        DATABASE_NAME="service_db",
        DATABASE_USER="svc_user",
        DATABASE_PASSWORD=DATABASE_EDGE_PASSWORD,
    )
    settings = Settings()
    parsed = make_url(settings.DATABASE_URL)
    assert parsed.username == "svc_user"
    assert parsed.password == DATABASE_EDGE_PASSWORD
    assert parsed.host == "pg.internal"
    assert parsed.port == 6543
    assert parsed.database == "service_db"


def test_redis_split_fields_build_redis_url(monkeypatch):
    reset_env(
        monkeypatch,
        REDIS_HOST="redis.internal",
        REDIS_PORT="6380",
        REDIS_DB="7",
        REDIS_USERNAME=REDIS_EDGE_USERNAME,
        REDIS_PASSWORD=REDIS_EDGE_PASSWORD,
    )
    settings = Settings()
    parsed = urlsplit(settings.REDIS_URL)
    pool = redis.ConnectionPool.from_url(settings.REDIS_URL)
    kwargs = pool.connection_kwargs
    encoded_user, encoded_password = parsed.netloc.rsplit("@", 1)[0].split(":", 1)
    assert unquote(encoded_user) == REDIS_EDGE_USERNAME
    assert unquote(encoded_password) == REDIS_EDGE_PASSWORD
    assert kwargs["username"] == REDIS_EDGE_USERNAME
    assert kwargs["password"] == REDIS_EDGE_PASSWORD
    assert parsed.hostname == "redis.internal"
    assert parsed.port == 6380
    assert parsed.path == "/7"
    assert kwargs["host"] == "redis.internal"
    assert kwargs["port"] == 6380
    assert kwargs["db"] == 7


def test_database_partial_split_config_fails_closed(monkeypatch):
    reset_env(monkeypatch, DATABASE_HOST="pg.internal")
    with pytest.raises(ConfigurationError, match="DATABASE split configuration is incomplete") as exc:
        Settings()
    assert_no_secret_leak(str(exc.value), "pg.internal")


def test_redis_partial_split_config_fails_closed(monkeypatch):
    reset_env(monkeypatch, REDIS_HOST="redis.internal", REDIS_PASSWORD="secret")
    with pytest.raises(ConfigurationError, match="REDIS split configuration is incomplete") as exc:
        Settings()
    assert_no_secret_leak(str(exc.value), "secret")


@pytest.mark.parametrize("field", [
    "DATABASE_HOST", "DATABASE_PORT", "DATABASE_NAME", "DATABASE_USER", "DATABASE_PASSWORD",
])
@pytest.mark.parametrize("value", ["", "   "])
def test_database_split_blank_or_whitespace_required_fields_fail_closed(monkeypatch, field, value):
    kwargs = {
        "DATABASE_HOST": "pg.internal",
        "DATABASE_PORT": "5432",
        "DATABASE_NAME": "service_db",
        "DATABASE_USER": "svc_user",
        "DATABASE_PASSWORD": DATABASE_EDGE_PASSWORD,
    }
    kwargs[field] = value
    reset_env(monkeypatch, **kwargs)
    with pytest.raises(ConfigurationError, match="DATABASE split configuration is incomplete"):
        Settings()


@pytest.mark.parametrize("field", [
    "REDIS_HOST", "REDIS_PORT", "REDIS_DB", "REDIS_PASSWORD",
])
@pytest.mark.parametrize("value", ["", "   "])
def test_redis_split_blank_or_whitespace_required_fields_fail_closed(monkeypatch, field, value):
    kwargs = {
        "REDIS_HOST": "redis.internal",
        "REDIS_PORT": "6379",
        "REDIS_DB": "4",
        "REDIS_PASSWORD": REDIS_EDGE_PASSWORD,
    }
    kwargs[field] = value
    reset_env(monkeypatch, **kwargs)
    with pytest.raises(ConfigurationError, match="REDIS split configuration is incomplete"):
        Settings()


def test_split_config_takes_priority_over_legacy_urls(monkeypatch):
    reset_env(
        monkeypatch,
        DATABASE_HOST="pg.internal",
        DATABASE_PORT="5432",
        DATABASE_NAME="service_db",
        DATABASE_USER="svc_user",
        DATABASE_PASSWORD="split-password",
        REDIS_HOST="redis.internal",
        REDIS_PORT="6379",
        REDIS_DB="4",
        REDIS_PASSWORD="split-redis-password",
    )
    settings = Settings()
    assert "legacy-password" not in settings.DATABASE_URL
    assert "legacy-password" not in settings.REDIS_URL
    assert settings.DATABASE_URL.startswith("postgresql+psycopg2://svc_user:")
    assert settings.REDIS_URL.startswith("redis://:")


def test_backend_database_import_works_with_split_config(monkeypatch):
    reset_env(
        monkeypatch,
        APP_ENV="development",
        ENV=None,
        DATABASE_URL=None,
        REDIS_URL=None,
        DATABASE_HOST="db",
        DATABASE_PORT="5432",
        DATABASE_NAME="name",
        DATABASE_USER="user",
        DATABASE_PASSWORD=DATABASE_EDGE_PASSWORD,
        REDIS_HOST="redis",
        REDIS_PORT="6379",
        REDIS_DB="0",
        REDIS_USERNAME=REDIS_EDGE_USERNAME,
        REDIS_PASSWORD=REDIS_EDGE_PASSWORD,
    )
    module = importlib.import_module("backend.database")
    module = importlib.reload(module)
    assert str(module.engine.url) == "postgresql+psycopg2://user:***@db:5432/name"
    assert module.engine.url.password == DATABASE_EDGE_PASSWORD
    kwargs = module.get_redis().connection_pool.connection_kwargs
    assert kwargs["username"] == REDIS_EDGE_USERNAME
    assert kwargs["password"] == REDIS_EDGE_PASSWORD


def test_flags_remain_false_when_bound_false(monkeypatch):
    reset_env(monkeypatch)
    settings = Settings()
    assert settings.AGENT_RUNTIME_ENABLED is False
    assert settings.ALPHA_WORKFLOW_ENABLED is False
    assert settings.ALPHA_SCENARIO_ENABLED is False
    assert settings.ALPHA_WORKFLOW_DASHBOARD_ENABLED is False
    assert settings.ALPHA_DASHBOARD_ENABLED is False


def test_passwords_are_url_encoded_once_and_roundtrip_exact(monkeypatch):
    reset_env(
        monkeypatch,
        DATABASE_HOST="pg.internal",
        DATABASE_PORT="5432",
        DATABASE_NAME="service_db",
        DATABASE_USER="svc_user",
        DATABASE_PASSWORD=DATABASE_EDGE_PASSWORD,
        REDIS_HOST="redis.internal",
        REDIS_PORT="6379",
        REDIS_DB="8",
        REDIS_USERNAME=REDIS_EDGE_USERNAME,
        REDIS_PASSWORD=REDIS_EDGE_PASSWORD,
    )
    settings = Settings()
    db_parsed = make_url(settings.DATABASE_URL)
    redis_parsed = urlsplit(settings.REDIS_URL)
    redis_pool = redis.ConnectionPool.from_url(settings.REDIS_URL)
    kwargs = redis_pool.connection_kwargs
    assert db_parsed.password == DATABASE_EDGE_PASSWORD
    assert kwargs["username"] == REDIS_EDGE_USERNAME
    assert kwargs["password"] == REDIS_EDGE_PASSWORD
    assert redis_parsed.hostname == "redis.internal"
    assert redis_parsed.port == 6379
    assert redis_parsed.path == "/8"
    assert kwargs["host"] == "redis.internal"
    assert kwargs["port"] == 6379
    assert kwargs["db"] == 8
    assert os.getenv("DATABASE_URL") == "postgresql+psycopg2://legacy-user:legacy-password@legacy-db:5432/legacy_name"
    assert os.getenv("REDIS_URL") == "redis://:legacy-password@legacy-redis:6379/5"


@pytest.mark.parametrize("value", [None, "", "   ", "<DATABASE_URL>"])
def test_production_rejects_missing_blank_or_placeholder_database_url_without_split(monkeypatch, value):
    reset_env(monkeypatch, DATABASE_URL=value)
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        Settings()


@pytest.mark.parametrize("value", [None, "", "   ", "<REDIS_URL>"])
def test_production_rejects_missing_blank_or_placeholder_redis_url_without_split(monkeypatch, value):
    reset_env(monkeypatch, REDIS_URL=value)
    with pytest.raises(ConfigurationError, match="REDIS_URL"):
        Settings()


@pytest.mark.parametrize("value", ["redis://redis:6379/0", "redis://user@redis:6379/0", "redis://:@redis:6379/0", "redis://:%20%20%20@redis:6379/0", "redis://:%3CREDIS_PASSWORD%3E@redis:6379/0"])
def test_production_rejects_redis_urls_without_valid_password_auth(monkeypatch, value):
    reset_env(monkeypatch, REDIS_URL=value)
    with pytest.raises(ConfigurationError, match="authenticated REDIS_URL"):
        Settings()
