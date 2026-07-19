import importlib
import sys

import pytest

import backend.config as config_module
from backend.config import (
    BACKEND_SERVICE_ROLE,
    WORKER_SERVICE_ROLE,
    ConfigurationError,
    SERVICE_ROLE_FIELD_NAME,
    Settings,
    get_settings,
)


ALL_KEYS = (
    "APP_ENV",
    "ENV",
    SERVICE_ROLE_FIELD_NAME,
    "DATABASE_URL",
    "REDIS_URL",
    "DATABASE_HOST",
    "DATABASE_PORT",
    "DATABASE_NAME",
    "DATABASE_USER",
    "DATABASE_PASSWORD",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_DB",
    "REDIS_USERNAME",
    "REDIS_PASSWORD",
    "JWT_SECRET",
    "BOSS_INITIAL_PASSWORD",
    "CORS_ALLOWED_ORIGINS",
    "AGENT_RUNTIME_ENABLED",
    "ALPHA_WORKFLOW_ENABLED",
    "ALPHA_SCENARIO_ENABLED",
    "ALPHA_WORKFLOW_DASHBOARD_ENABLED",
    "ALPHA_DASHBOARD_ENABLED",
)

JWT_SECRET = "worker-secret-isolation-jwt-secret-32-plus"
BOSS_PASSWORD = "worker-secret-isolation-boss-password"


def reset_env(monkeypatch, **overrides):
    get_settings.cache_clear()
    for key in ALL_KEYS:
        monkeypatch.delenv(key, raising=False)
    values = {
        "APP_ENV": "production",
        SERVICE_ROLE_FIELD_NAME: BACKEND_SERVICE_ROLE,
        "DATABASE_HOST": "pg.internal",
        "DATABASE_PORT": "5432",
        "DATABASE_NAME": "tiantong",
        "DATABASE_USER": "svc_user",
        "DATABASE_PASSWORD": "db secret:/?#%+ 中文",
        "REDIS_HOST": "redis.internal",
        "REDIS_PORT": "6379",
        "REDIS_DB": "5",
        "REDIS_PASSWORD": "redis secret:/?#%+ 中文",
        "JWT_SECRET": JWT_SECRET,
        "BOSS_INITIAL_PASSWORD": BOSS_PASSWORD,
        "CORS_ALLOWED_ORIGINS": "https://app.example.com",
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


def reload_module(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def test_backend_role_with_complete_security_config_passes(monkeypatch):
    reset_env(monkeypatch, SERVICE_ROLE=BACKEND_SERVICE_ROLE)
    settings = Settings()
    assert settings.SERVICE_ROLE == BACKEND_SERVICE_ROLE
    assert settings.JWT_SECRET == JWT_SECRET
    assert settings.BOSS_INITIAL_PASSWORD == BOSS_PASSWORD


def test_backend_role_missing_jwt_secret_fails_closed(monkeypatch):
    reset_env(monkeypatch, SERVICE_ROLE=BACKEND_SERVICE_ROLE, JWT_SECRET=None)
    with pytest.raises(ConfigurationError, match="JWT_SECRET"):
        Settings()


def test_backend_role_missing_boss_initial_password_fails_closed(monkeypatch):
    reset_env(monkeypatch, SERVICE_ROLE=BACKEND_SERVICE_ROLE, BOSS_INITIAL_PASSWORD=None)
    with pytest.raises(ConfigurationError, match="BOSS_INITIAL_PASSWORD"):
        Settings()


def test_worker_role_does_not_require_backend_only_secrets(monkeypatch):
    reset_env(
        monkeypatch,
        SERVICE_ROLE=WORKER_SERVICE_ROLE,
        JWT_SECRET=None,
        BOSS_INITIAL_PASSWORD=None,
    )
    settings = Settings()
    assert settings.SERVICE_ROLE == WORKER_SERVICE_ROLE
    with pytest.raises(ConfigurationError, match="backend service role"):
        _ = settings.JWT_SECRET
    with pytest.raises(ConfigurationError, match="backend service role"):
        _ = settings.BOSS_INITIAL_PASSWORD
    assert settings.__dict__["_jwt_secret"] is None
    assert settings.__dict__["_boss_initial_password"] is None


def test_worker_role_never_reads_backend_only_secret_env(monkeypatch):
    reset_env(
        monkeypatch,
        SERVICE_ROLE=WORKER_SERVICE_ROLE,
        JWT_SECRET=None,
        BOSS_INITIAL_PASSWORD=None,
    )
    counts = {"JWT_SECRET": 0, "BOSS_INITIAL_PASSWORD": 0}
    original = config_module.os.getenv

    def counting_getenv(name, default=None):
        if name in counts:
            counts[name] += 1
        return original(name, default)

    monkeypatch.setattr(config_module.os, "getenv", counting_getenv)
    Settings()
    assert counts["JWT_SECRET"] == 0
    assert counts["BOSS_INITIAL_PASSWORD"] == 0


def test_worker_role_keeps_backend_only_secrets_out_of_settings_even_if_present(monkeypatch):
    reset_env(monkeypatch, SERVICE_ROLE=WORKER_SERVICE_ROLE)
    settings = Settings()
    assert settings.__dict__["_jwt_secret"] is None
    assert settings.__dict__["_boss_initial_password"] is None


def test_worker_backend_only_secret_access_fails_closed(monkeypatch):
    reset_env(monkeypatch, SERVICE_ROLE=WORKER_SERVICE_ROLE)
    settings = Settings()
    with pytest.raises(ConfigurationError, match="JWT_SECRET is only available"):
        _ = settings.JWT_SECRET


@pytest.mark.parametrize("value", [None, "", "   ", "<SERVICE_ROLE>", "invalid"])
def test_missing_or_invalid_service_role_fails_closed_in_production(monkeypatch, value):
    reset_env(monkeypatch, SERVICE_ROLE=value)
    with pytest.raises(ConfigurationError, match=SERVICE_ROLE_FIELD_NAME):
        Settings()


def test_backend_main_import_fails_with_worker_role(monkeypatch):
    reset_env(monkeypatch, SERVICE_ROLE=WORKER_SERVICE_ROLE)
    get_settings.cache_clear()
    sys.modules.pop("backend.main", None)
    with pytest.raises(ConfigurationError, match=f"{SERVICE_ROLE_FIELD_NAME} must be backend"):
        importlib.import_module("backend.main")


def test_backend_worker_import_fails_with_backend_role(monkeypatch):
    reset_env(monkeypatch, SERVICE_ROLE=BACKEND_SERVICE_ROLE)
    get_settings.cache_clear()
    sys.modules.pop("backend.worker", None)
    with pytest.raises(ConfigurationError, match=f"{SERVICE_ROLE_FIELD_NAME} must be worker"):
        importlib.import_module("backend.worker")


def test_backend_main_import_passes_with_backend_role(monkeypatch):
    reset_env(monkeypatch, SERVICE_ROLE=BACKEND_SERVICE_ROLE)
    get_settings.cache_clear()
    module = reload_module("backend.main")
    assert module.app.title == "天统AI云中台"


def test_worker_import_passes_without_backend_secrets(monkeypatch):
    reset_env(
        monkeypatch,
        SERVICE_ROLE=WORKER_SERVICE_ROLE,
        JWT_SECRET=None,
        BOSS_INITIAL_PASSWORD=None,
    )
    get_settings.cache_clear()
    module = reload_module("backend.worker")
    assert module.WORKER_HEARTBEAT_KEY == "tiantong:worker:heartbeat"


def test_database_split_and_redis_split_behavior_unchanged_for_worker(monkeypatch):
    reset_env(
        monkeypatch,
        SERVICE_ROLE=WORKER_SERVICE_ROLE,
        JWT_SECRET=None,
        BOSS_INITIAL_PASSWORD=None,
    )
    settings = Settings()
    assert settings.DATABASE_URL.startswith("postgresql+psycopg2://svc_user:")
    assert settings.REDIS_URL.startswith("redis://:")


def test_flags_remain_false(monkeypatch):
    reset_env(
        monkeypatch,
        SERVICE_ROLE=WORKER_SERVICE_ROLE,
        JWT_SECRET=None,
        BOSS_INITIAL_PASSWORD=None,
    )
    settings = Settings()
    assert settings.AGENT_RUNTIME_ENABLED is False
    assert settings.ALPHA_WORKFLOW_ENABLED is False
    assert settings.ALPHA_SCENARIO_ENABLED is False
    assert settings.ALPHA_WORKFLOW_DASHBOARD_ENABLED is False
    assert settings.ALPHA_DASHBOARD_ENABLED is False
