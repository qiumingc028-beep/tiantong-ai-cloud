import pytest

from backend.config import ConfigurationError, Settings


PRODUCTION_KEYS = (
    "APP_ENV",
    "ENV",
    "DATABASE_URL",
    "REDIS_URL",
    "JWT_SECRET",
    "BOSS_INITIAL_PASSWORD",
    "CORS_ALLOWED_ORIGINS",
    "CORS_ALLOW_CREDENTIALS",
    "DEBUG",
)


def production_env(monkeypatch, **overrides):
    for key in PRODUCTION_KEYS:
        monkeypatch.delenv(key, raising=False)
    values = {
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql+psycopg2://app:isolated-test-password@postgres:5432/app",
        "REDIS_URL": "redis://:isolated-test-password@redis:6379/0",
        "JWT_SECRET": "isolated-production-policy-jwt-secret-32-plus",
        "BOSS_INITIAL_PASSWORD": "isolated-boss-password",
        "CORS_ALLOWED_ORIGINS": "https://app.example.com,https://admin.example.com/",
        "CORS_ALLOW_CREDENTIALS": "true",
        "DEBUG": "false",
    }
    values.update(overrides)
    for key, value in values.items():
        if value is not None:
            monkeypatch.setenv(key, value)


def test_valid_production_origins_and_credentials(monkeypatch):
    production_env(monkeypatch)

    settings = Settings()

    assert settings.IS_PRODUCTION is True
    assert settings.CORS_ALLOWED_ORIGINS == ["https://app.example.com", "https://admin.example.com"]
    assert settings.CORS_ALLOW_CREDENTIALS is True
    assert settings.DEBUG is False


def test_production_requires_cors_origins(monkeypatch):
    production_env(monkeypatch, CORS_ALLOWED_ORIGINS=None)

    with pytest.raises(ConfigurationError, match="CORS_ALLOWED_ORIGINS"):
        Settings()


@pytest.mark.parametrize("origins", ["*", "https://app.example.com,*"])
def test_production_rejects_wildcard_origins(monkeypatch, origins):
    production_env(monkeypatch, CORS_ALLOWED_ORIGINS=origins)

    with pytest.raises(ConfigurationError, match="wildcard"):
        Settings()


def test_wildcard_is_rejected_even_when_credentials_are_disabled(monkeypatch):
    production_env(monkeypatch, CORS_ALLOWED_ORIGINS="*", CORS_ALLOW_CREDENTIALS="false")

    with pytest.raises(ConfigurationError, match="wildcard"):
        Settings()


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("JWT_SECRET", "change-me-in-production", "JWT_SECRET"),
        ("BOSS_INITIAL_PASSWORD", "Tiantong@2026", "BOSS_INITIAL_PASSWORD"),
        (
            "DATABASE_URL",
            "postgresql+psycopg2://tiantong:tiantong@postgres:5432/tiantong_ai",
            "database credentials",
        ),
        ("REDIS_URL", "redis://redis:6379/0", "REDIS_URL"),
        ("DEBUG", "true", "DEBUG"),
    ],
)
def test_production_rejects_insecure_fallbacks(monkeypatch, key, value, message):
    production_env(monkeypatch, **{key: value})

    with pytest.raises(ConfigurationError, match=message):
        Settings()


def test_production_fails_fast_when_required_secret_is_missing(monkeypatch):
    production_env(monkeypatch, JWT_SECRET=None)

    with pytest.raises(ConfigurationError, match="JWT_SECRET"):
        Settings()
