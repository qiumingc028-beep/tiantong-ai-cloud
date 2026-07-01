from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
import redis

from .config import get_settings


settings = get_settings()
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_redis():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def ensure_tables():
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
