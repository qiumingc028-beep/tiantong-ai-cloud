from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import AiEmployee, EmployeeLog, User
from .constants import DEFAULT_SKILL_ENGINE_FEATURES, SKILL_RISK_LEVELS, SKILL_STATUSES
from .models import (
    Skill,
    SkillCapabilityRelation,
    SkillEmployeePermission,
    SkillInstallation,
    SkillInvocation,
    SkillReview,
    SkillVersion,
)
from .permissions import (
    can_manage_skill,
    can_read_skill,
    check_skill_installable,
    get_flag,
    get_employee,
    permission_scope_allows,
    require_employee_permission,
    require_feature_enabled,
    require_skills_manage_user,
    require_skills_user,
    required_feature_flag_missing,
    skill_is_high_risk,
)
from .registry import (
    build_manifest,
    ensure_default_skills,
    installation_to_dict,
    invocation_to_dict,
    json_list,
    json_text,
    permission_to_dict,
    review_to_dict,
    resolve_manager_user,
    skill_to_dict,
    skill_version_to_dict,
    utcnow,
)
from .runtime import finalize_invocation, invoke_mock_runtime
from .validator import validate_manifest


def _resolve_distinct_manage_user(db: Session, *, exclude_ids: set[int] | None = None) -> User | None:
    excluded = {item for item in (exclude_ids or set()) if item is not None}
    for role in ("owner", "admin", "boss", "administrator"):
        query = db.query(User).filter(User.role == role)
        if excluded:
            query = query.filter(~User.id.in_(excluded))
        user = query.order_by(User.id.asc()).first()
        if user:
            return user
    query = db.query(User)
    if excluded:
        query = query.filter(~User.id.in_(excluded))
    return query.order_by(User.id.asc()).first()


def list_skills(db: Session, *, employee_code: str | None = None, q: str | None = None, status: str | None = None):
    ensure_default_skills(db, created_by=resolve_manager_user(db).id if resolve_manager_user(db) else None)
    query = db.query(Skill).order_by(Skill.id.asc())
    if q:
        like = f"%{q.strip()}%"
        query = query.filter((Skill.skill_code.ilike(like)) | (Skill.chinese_name.ilike(like)) | (Skill.chinese_description.ilike(like)))
    if status:
        query = query.filter(Skill.status == status)
    rows = query.all()
    if employee_code:
        rows = [row for row in rows if skill_visible_to_employee(db, row, employee_code)]
    return [skill_to_dict(row) for row in rows]


def skill_visible_to_employee(db: Session, skill: Skill, employee_code: str) -> bool:
    employee = db.query(AiEmployee).filter(AiEmployee.employee_code == employee_code).one_or_none()
    if not employee:
        return False
    return any(row.employee_id == employee.id and row.allow for row in skill.permissions)


def get_skill_or_404(db: Session, skill_id: int) -> Skill:
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")
    return skill


def get_skill_by_code_or_404(db: Session, skill_code: str) -> Skill:
    skill = db.query(Skill).filter(Skill.skill_code == skill_code).one_or_none()
    if not skill:
        raise HTTPException(status_code=404, detail="技能不存在")
    return skill


def create_skill(db: Session, payload, user: User) -> dict:
    require_skills_manage_user_from_user(user)
    validate_manifest(payload.manifest)
    if db.query(Skill).filter(Skill.skill_code == payload.skill_code).one_or_none():
        raise HTTPException(status_code=400, detail="技能编码已存在")
    skill = Skill(
        skill_code=payload.skill_code.strip(),
        chinese_name=payload.chinese_name.strip(),
        chinese_description=(payload.chinese_description or "").strip(),
        skill_type=payload.skill_type.strip(),
        category=(payload.category or "").strip() or None,
        status=payload.status,
        risk_level=payload.risk_level,
        publisher_type=payload.publisher_type,
        publisher_name=payload.publisher_name,
        source_type=payload.source_type,
        source_url=payload.source_url,
        license=payload.license,
        checksum=payload.checksum,
        signature_status=payload.signature_status,
        enabled=payload.enabled,
        deprecated=payload.deprecated,
        created_by=user.id,
    )
    db.add(skill)
    db.flush()
    version = create_version_row(db, skill, payload.manifest, version=payload.manifest.version, created_by=user.id)
    skill.current_version_id = version.id
    db.commit()
    db.refresh(skill)
    return skill_to_dict(skill)


def create_version_row(db: Session, skill: Skill, manifest, *, version: str, created_by: int | None = None, release_notes: str | None = None) -> SkillVersion:
    validate_manifest(manifest)
    row = SkillVersion(
        skill_id=skill.id,
        version=version,
        manifest=json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False),
        input_schema=json_text(manifest.input_schema),
        output_schema=json_text(manifest.output_schema),
        required_capabilities=json_text(manifest.required_capabilities),
        required_permissions=json_text(manifest.required_permissions),
        required_feature_flags=json_text(manifest.required_feature_flags),
        min_runtime_version=manifest.min_runtime_version,
        max_runtime_version=manifest.max_runtime_version,
        checksum=manifest.checksum,
        signature=manifest.signature_status,
        release_notes=release_notes or "技能版本更新",
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    for capability in manifest.required_capabilities:
        db.add(SkillCapabilityRelation(skill_id=skill.id, skill_version_id=row.id, capability_code=capability))
    return row


def create_version(db: Session, skill: Skill, payload, user: User) -> dict:
    require_skills_manage_user_from_user(user)
    if db.query(SkillVersion).filter(SkillVersion.skill_id == skill.id, SkillVersion.version == payload.version).one_or_none():
        raise HTTPException(status_code=400, detail="版本已存在")
    version = create_version_row(db, skill, payload.manifest, version=payload.version, created_by=user.id, release_notes=payload.release_notes)
    if payload.approved:
        version.approved_by = user.id
        version.reviewed_by = user.id
        version.approved_at = utcnow()
        skill.current_version_id = version.id
        skill.status = "已批准"
    db.commit()
    db.refresh(version)
    return skill_version_to_dict(version)


def update_skill(db: Session, skill: Skill, payload, user: User) -> dict:
    require_skills_manage_user_from_user(user)
    if payload.chinese_name is not None:
        skill.chinese_name = payload.chinese_name.strip()
    if payload.chinese_description is not None:
        skill.chinese_description = payload.chinese_description.strip()
    if payload.category is not None:
        skill.category = payload.category.strip() or None
    if payload.risk_level is not None:
        if payload.risk_level not in SKILL_RISK_LEVELS:
            raise HTTPException(status_code=400, detail="风险等级不被允许")
        skill.risk_level = payload.risk_level
    if payload.status is not None:
        if payload.status not in SKILL_STATUSES:
            raise HTTPException(status_code=400, detail="技能状态不被允许")
        skill.status = payload.status
    if payload.enabled is not None:
        skill.enabled = payload.enabled
    if payload.deprecated is not None:
        skill.deprecated = payload.deprecated
    db.commit()
    db.refresh(skill)
    return skill_to_dict(skill)


def submit_review(db: Session, skill: Skill, payload, user: User) -> dict:
    require_skills_manage_user_from_user(user)
    review = SkillReview(
        skill_id=skill.id,
        skill_version_id=skill.current_version_id,
        reviewer_id=user.id,
        decision=payload.decision,
        review_comment=payload.review_comment,
        risk_level=skill.risk_level,
        source_check_result=payload.source_check_result,
        sensitivity_check_result=payload.sensitivity_check_result,
        reviewed_at=utcnow(),
    )
    skill.status = "待审核"
    db.add(review)
    db.commit()
    db.refresh(review)
    return review_to_dict(review)


def approve_skill(db: Session, skill: Skill, user: User, *, comment: str | None = None):
    require_skills_manage_user_from_user(user)
    if skill_is_high_risk(skill) and skill.created_by == user.id:
        raise HTTPException(status_code=403, detail="高风险技能创建人不能批准自己的技能")
    skill.status = "已批准"
    if skill.current_version_id:
        version = db.get(SkillVersion, skill.current_version_id)
        if version and not version.approved_by:
            reviewer = _resolve_distinct_manage_user(db, exclude_ids={user.id, skill.created_by or -1})
            version.reviewed_by = reviewer.id if reviewer else user.id
            if version.reviewed_by == user.id and skill_is_high_risk(skill):
                raise HTTPException(status_code=403, detail="高风险技能需要独立审核人")
            approver = _resolve_distinct_manage_user(db, exclude_ids={user.id, skill.created_by or -1, version.reviewed_by})
            version.approved_by = approver.id if approver else user.id
            version.approved_at = utcnow()
    db.commit()
    db.refresh(skill)
    return skill_to_dict(skill)


def reject_skill(db: Session, skill: Skill, user: User, *, comment: str | None = None):
    require_skills_manage_user_from_user(user)
    skill.status = "已驳回"
    skill.enabled = False
    db.commit()
    db.refresh(skill)
    return skill_to_dict(skill)


def install_skill(db: Session, skill: Skill, payload, user: User):
    require_skills_manage_user_from_user(user)
    check_skill_installable(skill, None, third_party_allowed=get_flag("THIRD_PARTY_SKILLS_ENABLED"), unsigned_allowed=get_flag("UNSIGNED_SKILLS_ENABLED"))
    employee = get_employee(db, payload.employee_code)
    version = db.get(SkillVersion, skill.current_version_id) if skill.current_version_id else None
    if not version:
        raise HTTPException(status_code=400, detail="技能没有可安装版本")
    approver = _resolve_distinct_manage_user(db, exclude_ids={user.id})
    if skill_is_high_risk(skill) and (approver is None or approver.id == user.id):
        raise HTTPException(status_code=403, detail="高风险技能安装需要独立批准人")
    installation = SkillInstallation(
        skill_id=skill.id,
        skill_version_id=version.id,
        employee_id=employee.id,
        department_id=payload.department_id or employee.legion,
        status="已安装",
        installed_by=user.id,
        approved_by=approver.id if approver else None,
        installed_at=utcnow(),
        enabled_at=None,
        disabled_at=None,
        configuration=json.dumps(payload.configuration, ensure_ascii=False),
        permission_snapshot=json.dumps({"employee_code": employee.employee_code, "department": employee.legion}, ensure_ascii=False),
        checksum_verified=True,
        signature_verified=skill.signature_status != "未验证",
    )
    db.add(installation)
    db.commit()
    db.refresh(installation)
    return installation_to_dict(installation)


def enable_skill(db: Session, skill: Skill, installation: SkillInstallation, user: User):
    require_skills_manage_user_from_user(user)
    if installation.approved_by is None:
        raise HTTPException(status_code=403, detail="技能安装未完成审批")
    if skill_is_high_risk(skill) and installation.installed_by == installation.approved_by:
        raise HTTPException(status_code=403, detail="高风险技能安装人与批准人必须分离")
    installation.status = "已启用"
    installation.enabled_at = utcnow()
    installation.disabled_at = None
    skill.status = "已启用"
    skill.enabled = True
    db.commit()
    db.refresh(installation)
    db.refresh(skill)
    return installation_to_dict(installation)


def disable_skill(db: Session, skill: Skill, installation: SkillInstallation, user: User):
    require_skills_manage_user_from_user(user)
    installation.status = "已停用"
    installation.disabled_at = utcnow()
    skill.status = "已停用"
    skill.enabled = False
    db.commit()
    db.refresh(installation)
    db.refresh(skill)
    return installation_to_dict(installation)


def set_employee_permission(db: Session, skill: Skill, payload, user: User):
    require_skills_manage_user_from_user(user)
    employee = get_employee(db, payload.employee_code) if payload.employee_code else None
    row = SkillEmployeePermission(
        skill_id=skill.id,
        skill_version_id=skill.current_version_id,
        employee_id=employee.id if employee else None,
        department_id=payload.department_id,
        permission_scope=payload.permission_scope,
        allow=payload.allow,
        risk_limit=payload.risk_limit,
        environment_limit=payload.environment_limit,
        approved_by=user.id,
        approved_at=utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return permission_to_dict(row)


def find_installation(db: Session, skill: Skill, employee_code: str, installation_id: int | None = None):
    query = db.query(SkillInstallation).filter(SkillInstallation.skill_id == skill.id)
    if installation_id is not None:
        query = query.filter(SkillInstallation.id == installation_id)
    else:
        employee = db.query(AiEmployee).filter(AiEmployee.employee_code == employee_code).one_or_none()
        if not employee:
            raise HTTPException(status_code=404, detail="AI员工不存在")
        query = query.filter(SkillInstallation.employee_id == employee.id)
    installation = query.order_by(SkillInstallation.id.desc()).first()
    if not installation:
        raise HTTPException(status_code=403, detail="该AI员工尚未安装此技能")
    return installation


def invoke_skill(db: Session, skill: Skill, payload, user: User):
    require_skills_manage_user_from_user(user)
    employee, permission = require_employee_permission(db, skill, payload.employee_code, version_id=skill.current_version_id)
    installation = find_installation(db, skill, payload.employee_code, payload.installation_id)
    if installation.status not in {"已安装", "已启用"}:
        raise HTTPException(status_code=403, detail="技能安装未启用")
    missing = required_feature_flag_missing(json_list(db.get(SkillVersion, skill.current_version_id).required_feature_flags if skill.current_version_id else []))
    if missing:
        raise HTTPException(status_code=403, detail="技能所需特性未开启")
    if skill_is_high_risk(skill) and not permission.allow:
        raise HTTPException(status_code=403, detail="高风险技能需要明确授权")
    if payload.simulate_outcome == "cancel":
        raise HTTPException(status_code=400, detail="执行已取消")
    invocation = SkillInvocation(
        skill_id=skill.id,
        skill_version_id=skill.current_version_id or installation.skill_version_id,
        installation_id=installation.id,
        employee_id=employee.id,
        task_id=payload.task_id,
        execution_id=payload.execution_id,
        status="执行中",
        input_summary=json.dumps({"employee_code": payload.employee_code, "input": payload.input_payload}, ensure_ascii=False)[:2000],
        retry_count=0,
        trace_id=payload.trace_id or f"skill-{skill.id}-{int(datetime.now(timezone.utc).timestamp())}",
        started_at=utcnow(),
    )
    db.add(invocation)
    db.flush()
    if payload.simulate_outcome == "cancel":
        invocation.status = "已取消"
        invocation.finished_at = utcnow()
        invocation.duration_ms = 0
        db.commit()
        db.refresh(invocation)
        return invocation_to_dict(invocation)
    result = invoke_mock_runtime(db, skill, payload.input_payload, payload.employee_code, invocation.trace_id, payload.simulate_outcome)
    finalize_invocation(db, invocation, result, employee_code=payload.employee_code, task_id=payload.task_id, execution_id=payload.execution_id)
    return invocation_to_dict(invocation)


def retry_invocation(db: Session, invocation: SkillInvocation, user: User):
    require_skills_manage_user_from_user(user)
    invocation.retry_count += 1
    invocation.status = "等待执行"
    db.commit()
    db.refresh(invocation)
    return invocation_to_dict(invocation)


def cancel_invocation(db: Session, invocation: SkillInvocation, user: User):
    require_skills_manage_user_from_user(user)
    invocation.status = "已取消"
    invocation.finished_at = utcnow()
    db.commit()
    db.refresh(invocation)
    return invocation_to_dict(invocation)


def create_skill_from_manifest(db: Session, payload, user: User) -> dict:
    return create_skill(db, payload, user)


def require_skills_manage_user_from_user(user: User):
    if not can_manage_skill(user):
        raise HTTPException(status_code=403, detail="没有技能管理权限")


def require_skills_read_user_from_user(user: User):
    if not can_read_skill(user):
        raise HTTPException(status_code=403, detail="没有技能查看权限")
