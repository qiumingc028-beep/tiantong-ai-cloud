from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..database import get_db
from ..models import AiEmployee, TaskCenterTask, User
from ..skills_engine.audit import list_audit_logs, record_skill_audit
from ..skills_engine.models import Skill, SkillInstallation, SkillInvocation
from ..skills_engine.permissions import require_feature_enabled, require_skills_manage_user, require_skills_user
from ..skills_engine.registry import ensure_default_skills, installation_to_dict, invocation_to_dict, permission_to_dict, skill_to_dict, skill_version_to_dict
from ..skills_engine.schemas import SkillCreatePayload, SkillInstallPayload, SkillInvokePayload, SkillPermissionPayload, SkillReviewPayload, SkillStatusUpdatePayload, SkillUpdatePayload, SkillVersionCreatePayload
from ..skills_engine.service import (
    approve_skill,
    cancel_invocation,
    create_skill_from_manifest,
    create_version,
    disable_skill,
    get_skill_or_404,
    get_skill_by_code_or_404,
    find_installation,
    install_skill,
    invoke_skill,
    list_skills,
    retry_invocation,
    set_employee_permission,
    submit_review,
    update_skill,
    reject_skill,
)


router = APIRouter(prefix="/api/v2/skills")
health_router = APIRouter(prefix="/api/v2/skills-engine")


@router.get("")
def api_list_skills(request: Request, q: str | None = None, status: str | None = None, employee_code: str | None = None, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    user = require_skills_user(request, db)
    ensure_default_skills(db, created_by=user.id if user else None)
    return {
        "readonly": True,
        "skills": list_skills(db, employee_code=employee_code, q=q, status=status),
        "summary": skill_summary(db),
    }


@router.get("/{skill_id:int}")
def api_get_skill(skill_id: int, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    require_skills_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    return {"readonly": True, "skill": skill_to_dict(skill), "versions": [skill_version_to_dict(version) for version in skill.versions]}


@router.get("/code/{skill_code}")
def api_get_skill_by_code(skill_code: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    require_skills_user(request, db)
    skill = get_skill_by_code_or_404(db, skill_code)
    return {"readonly": True, "skill": skill_to_dict(skill), "versions": [skill_version_to_dict(version) for version in skill.versions]}


@router.post("")
def api_create_skill(payload: SkillCreatePayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    user = require_skills_manage_user(request, db)
    ensure_default_skills(db, created_by=user.id if user else None)
    return {"ok": True, "skill": create_skill_from_manifest(db, payload, user)}


@router.patch("/{skill_id:int}")
def api_update_skill(skill_id: int, payload: SkillUpdatePayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    user = require_skills_manage_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    return {"ok": True, "skill": update_skill(db, skill, payload, user)}


@router.get("/{skill_id:int}/versions")
def api_list_skill_versions(skill_id: int, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    require_skills_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    return {"skill_id": skill.id, "versions": [skill_version_to_dict(version) for version in skill.versions]}


@router.post("/{skill_id:int}/versions")
def api_create_skill_version(skill_id: int, payload: SkillVersionCreatePayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    user = require_skills_manage_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    return {"ok": True, "version": create_version(db, skill, payload, user)}


@router.get("/{skill_id:int}/permissions")
def api_list_skill_permissions(skill_id: int, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    require_skills_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    return {"skill_id": skill.id, "permissions": [permission_to_dict(row) for row in skill.permissions]}


@router.get("/{skill_id:int}/installations")
def api_list_skill_installations(skill_id: int, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    require_skills_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    return {"skill_id": skill.id, "installations": [installation_to_dict(row) for row in skill.installations]}


@router.post("/{skill_id:int}/permissions")
def api_create_skill_permission(skill_id: int, payload: SkillPermissionPayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    user = require_skills_manage_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    return {"ok": True, "permission": set_employee_permission(db, skill, payload, user)}


@router.post("/{skill_id:int}/submit-review")
def api_submit_skill_review(skill_id: int, payload: SkillReviewPayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    user = require_skills_manage_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    return {"ok": True, "review": submit_review(db, skill, payload, user)}


@router.post("/{skill_id:int}/approve")
def api_approve_skill(skill_id: int, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    user = require_skills_manage_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    return {"ok": True, "skill": approve_skill(db, skill, user)}


@router.post("/{skill_id:int}/reject")
def api_reject_skill(skill_id: int, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    user = require_skills_manage_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    return {"ok": True, "skill": reject_skill(db, skill, user)}


@router.post("/{skill_id:int}/install")
def api_install_skill(skill_id: int, payload: SkillInstallPayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    user = require_skills_manage_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    return {"ok": True, "installation": install_skill(db, skill, payload, user)}


@router.post("/{skill_id:int}/enable")
def api_enable_skill(skill_id: int, payload: SkillInstallPayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    user = require_skills_manage_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    installation = find_installation(db, skill, payload.employee_code)
    from ..skills_engine.service import enable_skill

    return {"ok": True, "installation": enable_skill(db, skill, installation, user)}


@router.post("/{skill_id:int}/disable")
def api_disable_skill(skill_id: int, payload: SkillInstallPayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    user = require_skills_manage_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    installation = find_installation(db, skill, payload.employee_code)
    return {"ok": True, "installation": disable_skill(db, skill, installation, user)}


@router.post("/{skill_id:int}/invoke")
def api_invoke_skill(skill_id: int, payload: SkillInvokePayload, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    user = require_skills_manage_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    return {"ok": True, "invocation": invoke_skill(db, skill, payload, user)}


@router.get("/invocations")
def api_list_invocations(request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    require_skills_user(request, db)
    rows = db.query(SkillInvocation).order_by(SkillInvocation.id.desc()).limit(200).all()
    return {"readonly": True, "invocations": [invocation_to_dict(row) for row in rows]}


@router.get("/invocations/{invocation_id:int}")
def api_get_invocation(invocation_id: int, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    require_skills_user(request, db)
    invocation = db.get(SkillInvocation, invocation_id)
    if not invocation:
        raise HTTPException(status_code=404, detail="调用记录不存在")
    return {"readonly": True, "invocation": invocation_to_dict(invocation)}


@router.post("/invocations/{invocation_id:int}/cancel")
def api_cancel_invocation(invocation_id: int, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    user = require_skills_manage_user(request, db)
    invocation = db.get(SkillInvocation, invocation_id)
    if not invocation:
        raise HTTPException(status_code=404, detail="调用记录不存在")
    return {"ok": True, "invocation": cancel_invocation(db, invocation, user)}


@router.post("/invocations/{invocation_id:int}/retry")
def api_retry_invocation(invocation_id: int, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    user = require_skills_manage_user(request, db)
    invocation = db.get(SkillInvocation, invocation_id)
    if not invocation:
        raise HTTPException(status_code=404, detail="调用记录不存在")
    return {"ok": True, "invocation": retry_invocation(db, invocation, user)}


@router.get("/invocations/{invocation_id:int}/audit")
def api_invocation_audit(invocation_id: int, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    require_skills_user(request, db)
    invocation = db.get(SkillInvocation, invocation_id)
    if not invocation:
        raise HTTPException(status_code=404, detail="调用记录不存在")
    return {"readonly": True, "audit": list_audit_logs(db, skill_id=invocation.skill_id, limit=20), "invocation": invocation_to_dict(invocation)}


@router.get("/{skill_id:int}/audit")
def api_skill_audit(skill_id: int, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    require_skills_user(request, db)
    skill = get_skill_or_404(db, skill_id)
    return {"readonly": True, "skill": skill_to_dict(skill), "audit": list_audit_logs(db, skill_id=skill.id, limit=20)}


@router.get("/employees/{employee_code}")
def api_skills_for_employee(employee_code: str, request: Request, db: Session = Depends(get_db)):
    require_feature_enabled("SKILLS_ENGINE_ENABLED")
    require_skills_user(request, db)
    from ..skills_engine.registry import list_employee_skill_cards

    return {"employee_code": employee_code, "skills": list_employee_skill_cards(db, employee_code)}


@health_router.get("/health")
@router.get("/health")
def api_health(request: Request, db: Session = Depends(get_db)):
    require_skills_user(request, db)
    ensure_default_skills(db)
    skills = db.query(Skill).count()
    enabled = db.query(Skill).filter(Skill.enabled.is_(True)).count()
    installed = db.query(SkillInstallation).filter(SkillInstallation.status.in_(["已安装", "已启用"])).count()
    from ..config import get_settings

    settings = get_settings()
    return {
        "service": "skills-engine",
        "ok": True,
        "status": "running",
        "feature_flags": {key: bool(getattr(settings, key, False)) for key in [
            "SKILLS_ENGINE_ENABLED",
            "SKILL_INSTALLATION_ENABLED",
            "SKILL_INVOCATION_ENABLED",
            "THIRD_PARTY_SKILLS_ENABLED",
            "UNSIGNED_SKILLS_ENABLED",
            "AUTO_SKILL_UPDATE_ENABLED",
            "SKILL_MARKETPLACE_ENABLED",
        ]},
        "stats": {"skills": skills, "enabled": enabled, "installed": installed},
        "time": datetime.now(timezone.utc).isoformat(),
    }


def skill_summary(db: Session) -> dict:
    ensure_default_skills(db)
    return {
        "total": db.query(Skill).count(),
        "enabled": db.query(Skill).filter(Skill.enabled.is_(True)).count(),
        "installed": db.query(SkillInstallation).filter(SkillInstallation.status.in_(["已安装", "已启用"])).count(),
        "awaiting_review": db.query(Skill).filter(Skill.status.in_(["待审核", "草稿"])).count(),
        "high_risk": db.query(Skill).filter(Skill.risk_level.in_(["高风险", "极高风险"])).count(),
        "recent_invocations": db.query(SkillInvocation).count(),
    }
