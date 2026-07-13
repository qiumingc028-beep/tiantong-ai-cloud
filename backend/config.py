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
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        self.DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
        self.AI_PROVIDER = os.getenv("AI_PROVIDER", "mock").lower()
        self.AGENT_RUNTIME_ENABLED = _boolean("AGENT_RUNTIME_ENABLED", True)
        self.REAL_EXECUTOR_ENABLED = _boolean("REAL_EXECUTOR_ENABLED", False)
        self.COMPUTER_CONTROL_ENABLED = _boolean("COMPUTER_CONTROL_ENABLED", False)
        self.OPENCLAW_ADAPTER_ENABLED = _boolean("OPENCLAW_ADAPTER_ENABLED", False)
        self.COMPUTER_EXECUTOR_ENABLED = _boolean("COMPUTER_EXECUTOR_ENABLED", False)
        self.ISOLATED_DESKTOP_ENABLED = _boolean("ISOLATED_DESKTOP_ENABLED", False)
        self.SCREEN_CAPTURE_ENABLED = _boolean("SCREEN_CAPTURE_ENABLED", False)
        self.HUMAN_TAKEOVER_ENABLED = _boolean("HUMAN_TAKEOVER_ENABLED", False)
        self.COMPUTER_TEXT_INPUT_ENABLED = _boolean("COMPUTER_TEXT_INPUT_ENABLED", False)
        self.COMPUTER_MOUSE_INPUT_ENABLED = _boolean("COMPUTER_MOUSE_INPUT_ENABLED", False)
        self.CLIPBOARD_READ_ENABLED = _boolean("CLIPBOARD_READ_ENABLED", False)
        self.CLIPBOARD_WRITE_ENABLED = _boolean("CLIPBOARD_WRITE_ENABLED", False)
        self.FILE_UPLOAD_ENABLED = _boolean("FILE_UPLOAD_ENABLED", False)
        self.FILE_DOWNLOAD_ENABLED = _boolean("FILE_DOWNLOAD_ENABLED", False)
        self.MAC_SAFE_ACTION_ENABLED = _boolean("MAC_SAFE_ACTION_ENABLED", False)
        self.MAC_SAFE_MOUSE_MOVE_ENABLED = _boolean("MAC_SAFE_MOUSE_MOVE_ENABLED", False)
        self.MAC_SAFE_CLICK_ENABLED = _boolean("MAC_SAFE_CLICK_ENABLED", False)
        self.MAC_SAFE_TEXT_INPUT_ENABLED = _boolean("MAC_SAFE_TEXT_INPUT_ENABLED", False)
        self.PER_ACTION_APPROVAL_ENABLED = _boolean("PER_ACTION_APPROVAL_ENABLED", False)
        self.POST_ACTION_VERIFICATION_ENABLED = _boolean("POST_ACTION_VERIFICATION_ENABLED", False)
        self.MAC_SAFE_WORKFLOW_ENABLED = _boolean("MAC_SAFE_WORKFLOW_ENABLED", False)
        self.MAC_MULTI_STEP_ENABLED = _boolean("MAC_MULTI_STEP_ENABLED", False)
        self.WORKFLOW_SCOPE_APPROVAL_ENABLED = _boolean("WORKFLOW_SCOPE_APPROVAL_ENABLED", False)
        self.WORKFLOW_CHECKPOINT_APPROVAL_ENABLED = _boolean("WORKFLOW_CHECKPOINT_APPROVAL_ENABLED", False)
        self.WORKFLOW_AUTO_CONTINUE_ENABLED = _boolean("WORKFLOW_AUTO_CONTINUE_ENABLED", False)
        self.WORKFLOW_RECOVERY_ENABLED = _boolean("WORKFLOW_RECOVERY_ENABLED", False)
        self.DEVICE_CENTER_ENABLED = _boolean("DEVICE_CENTER_ENABLED", False)
        self.MAC_DEVICE_AGENT_ENABLED = _boolean("MAC_DEVICE_AGENT_ENABLED", False)
        self.MAC_READONLY_OBSERVER_ENABLED = _boolean("MAC_READONLY_OBSERVER_ENABLED", False)
        self.MAC_WINDOW_ENUMERATION_ENABLED = _boolean("MAC_WINDOW_ENUMERATION_ENABLED", False)
        self.MAC_SCREEN_CAPTURE_ENABLED = _boolean("MAC_SCREEN_CAPTURE_ENABLED", False)
        self.LOCAL_VISION_PROVIDER_ENABLED = _boolean("LOCAL_VISION_PROVIDER_ENABLED", False)
        self.EXTERNAL_VISION_PROVIDER_ENABLED = _boolean("EXTERNAL_VISION_PROVIDER_ENABLED", False)
        self.COMPUTER_ALLOWED_APPLICATIONS = [item.strip() for item in os.getenv("COMPUTER_ALLOWED_APPLICATIONS", "").split(",") if item.strip()]
        self.COMPUTER_BLOCKED_APPLICATIONS = [item.strip() for item in os.getenv("COMPUTER_BLOCKED_APPLICATIONS", "").split(",") if item.strip()]
        self.COMPUTER_ALLOWED_WINDOW_PATTERNS = [item.strip() for item in os.getenv("COMPUTER_ALLOWED_WINDOW_PATTERNS", "").split(",") if item.strip()]
        self.COMPUTER_BLOCKED_WINDOW_PATTERNS = [item.strip() for item in os.getenv("COMPUTER_BLOCKED_WINDOW_PATTERNS", "").split(",") if item.strip()]
        self.MOBILE_CONTROL_ENABLED = _boolean("MOBILE_CONTROL_ENABLED", False)
        self.BROWSER_CONTROL_ENABLED = _boolean("BROWSER_CONTROL_ENABLED", False)
        self.BROWSER_READONLY_ENABLED = _boolean("BROWSER_READONLY_ENABLED", False)
        self.BROWSER_ALLOW_HTTP = _boolean("BROWSER_ALLOW_HTTP", False)
        self.BROWSER_ALLOWED_DOMAINS = [item.strip() for item in os.getenv("BROWSER_ALLOWED_DOMAINS", "").split(",") if item.strip()]
        self.BROWSER_BLOCK_PRIVATE_NETWORKS = _boolean("BROWSER_BLOCK_PRIVATE_NETWORKS", True)
        self.BROWSER_MAX_REDIRECTS = int(os.getenv("BROWSER_MAX_REDIRECTS", "3"))
        self.BROWSER_DEFAULT_TIMEOUT_SECONDS = int(os.getenv("BROWSER_DEFAULT_TIMEOUT_SECONDS", "20"))
        self.BROWSER_MAX_RESPONSE_BYTES = int(os.getenv("BROWSER_MAX_RESPONSE_BYTES", "2000000"))
        self.BROWSER_USER_AGENT = os.getenv("BROWSER_USER_AGENT", "").strip()
        self.PUBLIC_RESEARCH_ENABLED = _boolean("PUBLIC_RESEARCH_ENABLED", False)
        self.PUBLIC_SEARCH_ENABLED = _boolean("PUBLIC_SEARCH_ENABLED", False)
        self.PUBLIC_SEARCH_PROVIDER = os.getenv("PUBLIC_SEARCH_PROVIDER", "").strip()
        self.PUBLIC_SEARCH_MAX_QUERIES = int(os.getenv("PUBLIC_SEARCH_MAX_QUERIES", "5"))
        self.PUBLIC_SEARCH_MAX_RESULTS_PER_QUERY = int(os.getenv("PUBLIC_SEARCH_MAX_RESULTS_PER_QUERY", "10"))
        self.PUBLIC_RESEARCH_MAX_SOURCES = int(os.getenv("PUBLIC_RESEARCH_MAX_SOURCES", "20"))
        self.PUBLIC_RESEARCH_DEFAULT_MIN_SOURCES = int(os.getenv("PUBLIC_RESEARCH_DEFAULT_MIN_SOURCES", "2"))
        self.PUBLIC_RESEARCH_TIMEOUT_SECONDS = int(os.getenv("PUBLIC_RESEARCH_TIMEOUT_SECONDS", "20"))
        self.PUBLIC_RESEARCH_ALLOWED_DOMAINS = [item.strip() for item in os.getenv("PUBLIC_RESEARCH_ALLOWED_DOMAINS", "").split(",") if item.strip()]
        self.PUBLIC_RESEARCH_BLOCKED_DOMAINS = [item.strip() for item in os.getenv("PUBLIC_RESEARCH_BLOCKED_DOMAINS", "").split(",") if item.strip()]
        self.PUBLIC_RESEARCH_MAX_TEXT_LENGTH = int(os.getenv("PUBLIC_RESEARCH_MAX_TEXT_LENGTH", "20000"))
        self.PUBLIC_RESEARCH_MAX_CONCURRENT_SOURCES = int(os.getenv("PUBLIC_RESEARCH_MAX_CONCURRENT_SOURCES", "5"))
        self.SHELL_EXECUTION_ENABLED = _boolean("SHELL_EXECUTION_ENABLED", False)
        self.KNOWLEDGE_CENTER_ENABLED = _boolean("KNOWLEDGE_CENTER_ENABLED", False)
        self.KNOWLEDGE_SUBMISSION_ENABLED = _boolean("KNOWLEDGE_SUBMISSION_ENABLED", False)
        self.KNOWLEDGE_PUBLISH_ENABLED = _boolean("KNOWLEDGE_PUBLISH_ENABLED", False)
        self.KNOWLEDGE_LOCAL_SEARCH_ENABLED = _boolean("KNOWLEDGE_LOCAL_SEARCH_ENABLED", False)
        self.KNOWLEDGE_VECTOR_SEARCH_ENABLED = _boolean("KNOWLEDGE_VECTOR_SEARCH_ENABLED", False)
        self.ALPHA_WORKFLOW_ENABLED = _boolean("ALPHA_WORKFLOW_ENABLED", False)
        self.ALPHA_SCENARIO_ENABLED = _boolean("ALPHA_SCENARIO_ENABLED", False)
        self.ALPHA_WORKFLOW_DASHBOARD_ENABLED = _boolean("ALPHA_WORKFLOW_DASHBOARD_ENABLED", False)
        self.ALPHA_DASHBOARD_ENABLED = _boolean("ALPHA_DASHBOARD_ENABLED", False)
        self.SKILLS_ENGINE_ENABLED = _boolean("SKILLS_ENGINE_ENABLED", False)
        self.SKILL_INSTALLATION_ENABLED = _boolean("SKILL_INSTALLATION_ENABLED", False)
        self.SKILL_INVOCATION_ENABLED = _boolean("SKILL_INVOCATION_ENABLED", False)
        self.THIRD_PARTY_SKILLS_ENABLED = _boolean("THIRD_PARTY_SKILLS_ENABLED", False)
        self.UNSIGNED_SKILLS_ENABLED = _boolean("UNSIGNED_SKILLS_ENABLED", False)
        self.AUTO_SKILL_UPDATE_ENABLED = _boolean("AUTO_SKILL_UPDATE_ENABLED", False)
        self.SKILL_MARKETPLACE_ENABLED = _boolean("SKILL_MARKETPLACE_ENABLED", False)
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
        if self.EXTERNAL_VISION_PROVIDER_ENABLED:
            raise ConfigurationError("EXTERNAL_VISION_PROVIDER_ENABLED must remain disabled in production")


@lru_cache
def get_settings():
    return Settings()
