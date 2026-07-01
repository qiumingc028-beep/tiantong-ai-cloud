import os
from functools import lru_cache

from dotenv import load_dotenv


load_dotenv()


class Settings:
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://tiantong:tiantong@postgres:5432/tiantong_ai")
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
    JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    AI_PROVIDER = os.getenv("AI_PROVIDER", "mock").lower()
    JWT_ALGORITHM = "HS256"
    SESSION_TTL_SECONDS = 7 * 24 * 3600


@lru_cache
def get_settings():
    return Settings()
