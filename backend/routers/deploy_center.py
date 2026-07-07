from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db, get_redis
from ..deploy_models import DeployHealthCheck, DeployRecord, HealthCheckRecord


router = APIRouter(prefix="/api/deploy-center")

EXPECTED_ALEMBIC_VERSION = "0013_sprint17_auto_dispatch"
BASE_DIR = Path(__file__).resolve().parents[2]
STATE_FILES = [BASE_DIR / "deploy-state.json", BASE_DIR / "runtime-status.json"]


@router.get("/status")
def get_deploy_status(request: Request, db: Session = Depends(get_db)):
    require_deploy_center_user(request, db)
    database = check_database(db)
    redis = check_redis()
    last_record = latest_deploy_record(db)
    last_check = latest_health_check(db)
    service_status = "running"
    database_status = database["status"]
    redis_status = redis["status"]
    overall_status = combine_statuses([service_status, database_status, redis_status])
    return {
        "overall_status": overall_status,
        "service_status": service_status,
        "database_status": database_status,
        "redis_status": redis_status,
        "last_deploy_status": last_record.status if last_record else None,
        "last_health_check_status": last_check.status if last_check else None,
    }


@router.get("/version")
def get_version(request: Request, db: Session = Depends(get_db)):
    require_deploy_center_user(request, db)
    state = read_runtime_state()
    last_record = latest_deploy_record(db)
    commit_hash = (
        state.get("commit_hash")
        or read_env("DEPLOY_COMMIT", "GIT_COMMIT", "COMMIT_HASH", "SOURCE_VERSION")
        or (last_record.commit_hash if last_record else None)
    )
    branch = (
        state.get("branch")
        or read_env("DEPLOY_BRANCH", "GIT_BRANCH", "BRANCH")
        or (last_record.branch if last_record else None)
    )
    deploy_version = (
        state.get("deploy_version")
        or read_env("DEPLOY_VERSION", "APP_VERSION", "RELEASE_VERSION")
        or (last_record.deploy_version if last_record else None)
    )
    return {
        "branch": branch,
        "commit_hash": commit_hash,
        "commit_short": commit_hash[:7] if commit_hash else None,
        "deploy_version": deploy_version,
        "alembic_version": get_current_alembic_version(db),
        "build_time": state.get("build_time") or read_env("BUILD_TIME"),
    }


@router.get("/migration")
def get_migration_status(request: Request, db: Session = Depends(get_db)):
    require_deploy_center_user(request, db)
    current_version = get_current_alembic_version(db)
    return {
        "current_version": current_version,
        "expected_version": EXPECTED_ALEMBIC_VERSION,
        "status": "up_to_date" if current_version == EXPECTED_ALEMBIC_VERSION else "outdated",
    }


@router.get("/health")
def get_health(request: Request, db: Session = Depends(get_db)):
    require_deploy_center_user(request, db)
    return build_health_payload(db)


@router.post("/health/check")
def run_health_check(request: Request, db: Session = Depends(get_db)):
    require_deploy_center_user(request, db)
    payload = build_health_payload(db)
    checked_at = datetime.now(timezone.utc)
    for key in ("backend", "database", "redis", "migration", "nginx"):
        item = payload[key]
        db.add(
            DeployHealthCheck(
                check_type=key,
                target=item["target"],
                status=item["status"],
                message=item.get("message"),
                checked_at=checked_at,
            )
        )
        db.add(
            HealthCheckRecord(
                service=key,
                status=item["status"],
                checked_at=checked_at,
                latency=item.get("latency"),
            )
        )
    db.commit()
    return payload


@router.get("/records")
def list_deploy_records(request: Request, limit: int = 20, db: Session = Depends(get_db)):
    require_deploy_center_user(request, db)
    safe_limit = max(1, min(limit, 100))
    rows = db.query(DeployRecord).order_by(DeployRecord.id.desc()).limit(safe_limit).all()
    return [deploy_record_to_dict(row) for row in rows]


def require_deploy_center_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="no deploy center permission")
    return user


def build_health_payload(db: Session):
    now = datetime.now(timezone.utc).isoformat()
    database = measured_check(lambda: check_database(db))
    redis = measured_check(check_redis)
    migration = measured_check(lambda: check_migration(db))
    backend = measured_check(lambda: {"target": "backend", "status": "running", "message": "backend service is running"})
    nginx = measured_check(lambda: {"target": "nginx", "status": "unknown", "message": "nginx is not checked from backend runtime"})
    return {
        "backend": backend,
        "database": database,
        "redis": redis,
        "migration": migration,
        "nginx": nginx,
        "checked_at": now,
    }


def measured_check(check):
    started = time.perf_counter()
    result = check()
    result["latency"] = max(0, round((time.perf_counter() - started) * 1000))
    return result


def check_database(db: Session):
    try:
        db.execute(text("SELECT 1"))
        return {"target": "database", "status": "healthy", "message": "SELECT 1 succeeded"}
    except Exception as exc:
        return {"target": "database", "status": "unhealthy", "message": str(exc)}


def check_redis():
    try:
        ok = get_redis().ping()
        status = "healthy" if ok else "unhealthy"
        return {"target": "redis", "status": status, "message": "redis ping succeeded" if ok else "redis ping failed"}
    except Exception as exc:
        return {"target": "redis", "status": "unhealthy", "message": str(exc)}


def check_migration(db: Session):
    current_version = get_current_alembic_version(db)
    status = "healthy" if current_version == EXPECTED_ALEMBIC_VERSION else "warning"
    return {
        "target": "alembic_version",
        "status": status,
        "message": f"current={current_version or 'none'}, expected={EXPECTED_ALEMBIC_VERSION}",
    }


def get_current_alembic_version(db: Session):
    try:
        row = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).first()
        return row[0] if row else None
    except Exception:
        return None


def latest_deploy_record(db: Session):
    return db.query(DeployRecord).order_by(DeployRecord.id.desc()).first()


def latest_health_check(db: Session):
    return db.query(DeployHealthCheck).order_by(DeployHealthCheck.id.desc()).first()


def combine_statuses(statuses: list[str]):
    if any(status == "unhealthy" for status in statuses):
        return "unhealthy"
    if any(status in {"warning", "unknown"} for status in statuses):
        return "degraded"
    return "healthy"


def read_env(*keys: str):
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return None


def read_runtime_state():
    for path in STATE_FILES:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def iso(value: datetime | None):
    return value.isoformat() if value else None


def deploy_record_to_dict(record: DeployRecord):
    return {
        "id": record.id,
        "deploy_id": record.deploy_id,
        "version": record.version,
        "commit_id": record.commit_id,
        "deploy_time": iso(record.deploy_time),
        "deploy_status": record.deploy_status,
        "deploy_version": record.deploy_version,
        "commit_hash": record.commit_hash,
        "branch": record.branch,
        "operator": record.operator,
        "status": record.status,
        "started_at": iso(record.started_at),
        "finished_at": iso(record.finished_at),
        "note": record.note,
        "created_at": iso(record.created_at),
        "updated_at": iso(record.updated_at),
    }
