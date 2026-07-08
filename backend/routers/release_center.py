from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_db
from ..release_models import ReleaseVersion


router = APIRouter(prefix="/api/release")
BASE_DIR = Path(__file__).resolve().parents[2]
PRIVILEGED_ROLES = {"owner", "admin"}


class ReleaseCreatePayload(BaseModel):
    version: str
    sprint_name: str
    commit_id: str | None = None
    branch: str | None = None
    author: str | None = None


class ReleaseApprovePayload(BaseModel):
    release_id: int | None = None
    version: str | None = None
    boss_confirmed: bool = False
    security_audited: bool = False


@router.get("/current")
def get_current_release(request: Request, db: Session = Depends(get_db)):
    require_release_user(request, db)
    release = db.query(ReleaseVersion).order_by(ReleaseVersion.id.desc()).first()
    if release:
        return {"release": release_to_dict(release), "check": build_release_check()}
    return {
        "release": {
            "id": None,
            "version": "unreleased",
            "sprint_name": "",
            "commit_id": current_commit_id(),
            "branch": current_branch(),
            "author": None,
            "status": "not_created",
            "created_at": None,
            "approved_by": None,
            "deploy_status": "waiting",
        },
        "check": build_release_check(),
    }


@router.get("/check")
def check_release(request: Request, db: Session = Depends(get_db)):
    require_release_user(request, db)
    return build_release_check()


@router.post("/create")
def create_release(payload: ReleaseCreatePayload, request: Request, db: Session = Depends(get_db)):
    user = require_release_admin(request, db)
    existing = db.query(ReleaseVersion).filter(ReleaseVersion.version == payload.version).first()
    if existing:
        raise HTTPException(status_code=409, detail="Release version already exists")
    release = ReleaseVersion(
        version=payload.version,
        sprint_name=payload.sprint_name,
        commit_id=payload.commit_id or current_commit_id() or "unknown",
        branch=payload.branch or current_branch() or "unknown",
        author=payload.author or user.username,
        status="draft",
        approved_by=None,
        deploy_status="waiting",
    )
    db.add(release)
    db.commit()
    db.refresh(release)
    return {"release": release_to_dict(release), "check": build_release_check()}


@router.post("/approve")
def approve_release(payload: ReleaseApprovePayload, request: Request, db: Session = Depends(get_db)):
    user = require_release_admin(request, db)
    if not (payload.boss_confirmed and payload.security_audited):
        raise HTTPException(status_code=403, detail="Release approval requires boss confirmation and security audit")
    query = db.query(ReleaseVersion)
    if payload.release_id:
        release = query.filter(ReleaseVersion.id == payload.release_id).first()
    elif payload.version:
        release = query.filter(ReleaseVersion.version == payload.version).first()
    else:
        release = query.order_by(ReleaseVersion.id.desc()).first()
    if not release:
        raise HTTPException(status_code=404, detail="Release version not found")
    release.status = "approved"
    release.approved_by = user.username
    release.deploy_status = "waiting"
    db.commit()
    db.refresh(release)
    return {"release": release_to_dict(release), "check": build_release_check()}


def require_release_user(request: Request, db: Session):
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role in PRIVILEGED_ROLES:
        return user
    raise HTTPException(status_code=403, detail="无 Release Center 访问权限")


def require_release_admin(request: Request, db: Session):
    user = require_release_user(request, db)
    return user


def build_release_check() -> dict:
    git_dir = BASE_DIR / ".git"
    result = {
        "commit": bool(current_commit_id()) or not git_dir.exists(),
        "test": (BASE_DIR / "tests").is_dir() and any((BASE_DIR / "tests").glob("test_*.py")),
        "migration": (BASE_DIR / "alembic" / "versions" / "0026_sprint26_ai_employee_execution_mvp.py").is_file(),
        "docker": any((BASE_DIR / name).is_file() for name in ("Dockerfile", "Dockerfile.backend", "docker-compose.yml", "docker-compose.prod.yml")),
        "nginx": (BASE_DIR / "nginx" / "default.conf").is_file(),
        "docs": (BASE_DIR / "docs").is_dir() or not git_dir.exists(),
    }
    result["can_release"] = all(result.values())
    return result


def current_commit_id() -> str | None:
    for key in ("GIT_COMMIT", "COMMIT_HASH", "SOURCE_VERSION", "DEPLOY_COMMIT"):
        value = os.getenv(key)
        if value:
            return value
    git_dir = BASE_DIR / ".git"
    head_path = git_dir / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            ref_path = git_dir / head.removeprefix("ref: ")
            if ref_path.is_file():
                return ref_path.read_text(encoding="utf-8").strip()
        return head or None
    except OSError:
        return None


def current_branch() -> str | None:
    for key in ("GIT_BRANCH", "BRANCH", "DEPLOY_BRANCH"):
        value = os.getenv(key)
        if value:
            return value
    git_dir = BASE_DIR / ".git"
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if head.startswith("ref: refs/heads/"):
        return head.removeprefix("ref: refs/heads/")
    return None


def release_to_dict(row: ReleaseVersion) -> dict:
    return {
        "id": row.id,
        "version": row.version,
        "sprint_name": row.sprint_name,
        "commit_id": row.commit_id,
        "branch": row.branch,
        "author": row.author,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "approved_by": row.approved_by,
        "deploy_status": row.deploy_status,
    }
