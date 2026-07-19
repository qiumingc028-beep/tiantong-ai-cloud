import importlib
import os
from urllib.parse import urlsplit, unquote

import pytest
import redis
from sqlalchemy.engine import make_url

from backend.config import ConfigurationError, Settings, get_settings

ALL_KEYS = (
    "APP_ENV", "ENV", "DATABASE_URL", "REDIS_URL",
    "DATABASE_HOST", "DATABASE_PORT", "DATABASE_NAME", "DATABASE_USER", "DATABASE_PASSWORD",
    "REDIS_HOST", "REDIS_PORT", "REDIS_DB", "REDIS_USERNAME", "REDIS_PASSWORD",
    "JWT_SECRET", "BOSS_INITIAL_PASSWORD", "CORS_ALLOWED_ORIGINS",
    "AGENT_RUNTIME_ENABLED", "ALPHA_WORKFLOW_ENABLED", "ALPHA_SCENARIO_ENABLED",
    "ALPHA_WORKFLOW_DASHBOARD_ENABLED", "ALPHA_DASHBOARD_ENABLED",
)


def reset_env(monkeypatch, **overrides):
    get_settings.cache_clear()
    for key in ALL_KEYS:
        monkeypatch.delenv(key, raising=False)
    values = {
        "APP_ENV": "production",
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


def test_legacy_database_url_compatible(monkeypatch):
    reset_env(monkeypatch)
    assert Settings().DATABASE_URL == "postgresql+psycopg2://legacy-user:legacy-password@legacy-db:5432/legacy_name"


def test_legacy_redis_url_compatible(monkeypatch):
    reset_env(monkeypatch)
    assert Settings().REDIS_URL == "redis://:legacy-password@legacy-redis:6379/5"


def test_postgresql_split_fields_build_database_url(monkeypatch):
    password = "空 格@:/?#%+\\中文ß"
    reset_env(monkeypatch, DATABASE_HOST="pg.internal", DATABASE_PORT="6543", DATABASE_NAME="service_db", DATABASE_USER="svc_user", DATABASE_PASSWORD=password)
    settings = Settings()
    parsed = make_url(settings.DATABASE_URL)
    assert parsed.username == "svc_user"
    assert parsed.password == password
    assert parsed.host == "pg.internal"
    assert parsed.port == 6543
    assert parsed.database == "service_db"


def test_redis_split_fields_build_redis_url(monkeypatch):
    password = "空 格@:/?#%+\\中文ß"
    username = "服务@user 空格"
    reset_env(monkeypatch, REDIS_HOST="redis.internal", REDIS_PORT="6380", REDIS_DB="7", REDIS_USERNAME=username, REDIS_PASSWORD=password)
    settings = Settings()
    parsed = urlsplit(settings.REDIS_URL)
    pool = redis.ConnectionPool.from_url(settings.REDIS_URL)
    kwargs = pool.connection_kwargs
    userinfo = parsed.netloc.rsplit("@", 1)[0]
    encoded_user, encoded_password = userinfo.split(":", 1)
    assert unquote(encoded_user) == username
    assert unquote(encoded_password) == password
    assert kwargs["username"] == username
    assert kwargs["password"] == password
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
    assert "pg.internal" not in str(exc.value)


def test_redis_partial_split_config_fails_closed(monkeypatch):
    reset_env(monkeypatch, REDIS_HOST="redis.internal", REDIS_PASSWORD="secret")
    with pytest.raises(ConfigurationError, match="REDIS split configuration is incomplete") as exc:
        Settings()
    assert "secret" not in str(exc.value)


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
        DATABASE_PASSWORD="password",
        REDIS_HOST="redis",
        REDIS_PORT="6379",
        REDIS_DB="0",
        REDIS_PASSWORD="password",
    )
    module = importlib.import_module("backend.database")
    module = importlib.reload(module)
    assert str(module.engine.url) == "postgresql+psycopg2://user:***@db:5432/name"
    assert module.get_redis().connection_pool.connection_kwargs["password"] == "password"


def test_flags_remain_false_when_bound_false(monkeypatch):
    reset_env(monkeypatch)
    settings = Settings()
    assert settings.AGENT_RUNTIME_ENABLED is False
    assert settings.ALPHA_WORKFLOW_ENABLED is False
    assert settings.ALPHA_SCENARIO_ENABLED is False
    assert settings.ALPHA_WORKFLOW_DASHBOARD_ENABLED is False
    assert settings.ALPHA_DASHBOARD_ENABLED is False


def test_passwords_are_url_encoded(monkeypatch):
    database_password = "db 空格@:/?#%+\\中文ß"
    redis_password = "redis 空格@:/?#%+\\中文ß"
    redis_username = "redis 用户 空格@:/?#%+\\中文ß"
    reset_env(
        monkeypatch,
        DATABASE_HOST="pg.internal",
        DATABASE_PORT="5432",
        DATABASE_NAME="service_db",
        DATABASE_USER="svc_user",
        DATABASE_PASSWORD=database_password,
        REDIS_HOST="redis.internal",
        REDIS_PORT="6379",
        REDIS_DB="8",
        REDIS_USERNAME=redis_username,
        REDIS_PASSWORD=redis_password,
    )
    settings = Settings()
    db_parsed = make_url(settings.DATABASE_URL)
    redis_parsed = urlsplit(settings.REDIS_URL)
    redis_pool = redis.ConnectionPool.from_url(settings.REDIS_URL)
    kwargs = redis_pool.connection_kwargs
    assert db_parsed.password == database_password
    assert kwargs["password"] == redis_password
    assert kwargs["username"] == redis_username
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


def test_production_rejects_unauthenticated_redis_url(monkeypatch):
    reset_env(monkeypatch, REDIS_URL="redis://redis:6379/0")
    with pytest.raises(ConfigurationError, match="REDIS_URL"):
        Settings()
