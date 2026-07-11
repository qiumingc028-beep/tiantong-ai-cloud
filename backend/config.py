import os
from functools import lru_cache
from urllib.parse import urlparse

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    pass


def _environment() -> str:
    return (os.getenv("APP_ENV") or os.getenv("ENV") or "development").strip().lower()


if _environment() != "production":
    load_dotenv()


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value or (value.startswith("<") and value.endswith(">")):
        raise ConfigurationError(f"{name} is required in production")
    return value


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be a boolean")


def _cors_origins(raw: str, *, production: bool) -> list[str]:
    origins = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    if production and not origins:
        raise ConfigurationError("CORS_ALLOWED_ORIGINS is required in production")
    if "*" in origins:
        raise ConfigurationError("wildcard CORS origins are forbidden")
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
            raise ConfigurationError(f"invalid CORS origin: {origin}")
    return origins


class Settings:
    def __init__(self):
        self.APP_ENV = _environment()
        self.IS_PRODUCTION = self.APP_ENV == "production"

        if self.IS_PRODUCTION:
            self.DATABASE_URL = _required("DATABASE_URL")
            self.REDIS_URL = _required("REDIS_URL")
            self.JWT_SECRET = _required("JWT_SECRET")
            self.BOSS_INITIAL_PASSWORD = _required("BOSS_INITIAL_PASSWORD")
            cors_raw = _required("CORS_ALLOWED_ORIGINS")
        else:
            self.DATABASE_URL = os.getenv(
                "DATABASE_URL", "postgresql+psycopg2://tiantong:tiantong@postgres:5432/tiantong_ai"
            )
            self.REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
            self.JWT_SECRET = os.getenv("JWT_SECRET", "development-only-jwt-secret-change-me")
            self.BOSS_INITIAL_PASSWORD = os.getenv("BOSS_INITIAL_PASSWORD", "Tiantong@2026")
            cors_raw = os.getenv(
                "CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
            )

        self.CORS_ALLOWED_ORIGINS = _cors_origins(cors_raw, production=self.IS_PRODUCTION)
        self.CORS_ALLOW_CREDENTIALS = _boolean("CORS_ALLOW_CREDENTIALS", True)
        self.DEBUG = _boolean("DEBUG", False)
        self.AGENT_RUNTIME_ENABLED = _boolean("AGENT_RUNTIME_ENABLED", True)
        self.REAL_EXECUTOR_ENABLED = _boolean("REAL_EXECUTOR_ENABLED", False)
        self.COMPUTER_CONTROL_ENABLED = _boolean("COMPUTER_CONTROL_ENABLED", False)
        self.MOBILE_CONTROL_ENABLED = _boolean("MOBILE_CONTROL_ENABLED", False)
        self.BROWSER_CONTROL_ENABLED = _boolean("BROWSER_CONTROL_ENABLED", False)
        self.SHELL_EXECUTION_ENABLED = _boolean("SHELL_EXECUTION_ENABLED", False)
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
        self.AI_PROVIDER = os.getenv("AI_PROVIDER", "mock").lower()
        self.JWT_ALGORITHM = "HS256"
        self.SESSION_TTL_SECONDS = 7 * 24 * 3600

        if self.IS_PRODUCTION:
            self._validate_production()

    def _validate_production(self):
        if len(self.JWT_SECRET) < 32 or self.JWT_SECRET in {
            "change-me-in-production",
            "development-only-jwt-secret-change-me",
        }:
            raise ConfigurationError("JWT_SECRET must contain at least 32 non-default characters")
        if len(self.BOSS_INITIAL_PASSWORD) < 12 or self.BOSS_INITIAL_PASSWORD == "Tiantong@2026":
            raise ConfigurationError("BOSS_INITIAL_PASSWORD must be an explicit non-default value")
        if "tiantong:tiantong@" in self.DATABASE_URL:
            raise ConfigurationError("development database credentials are forbidden in production")
        if self.REDIS_URL == "redis://redis:6379/0" or ":@" in self.REDIS_URL:
            raise ConfigurationError("authenticated REDIS_URL is required in production")
        if self.DEBUG:
            raise ConfigurationError("DEBUG must be disabled in production")


@lru_cache
def get_settings():
    return Settings()
