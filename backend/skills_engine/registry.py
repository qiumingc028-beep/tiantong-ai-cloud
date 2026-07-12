from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..ai_employees.registry import TIANCAI_DATA, TIANCE_STRATEGY, TIANSHU
from ..auth import current_user
from ..auth_data import normalize_role
from ..database import get_settings
from ..models import AiEmployee, EmployeeLog, TaskCenterResult, TaskCenterTask, User
from .constants import MOCK_SKILL_DEFINITIONS
from .models import Skill, SkillCapabilityRelation, SkillEmployeePermission, SkillInstallation, SkillReview, SkillVersion
from .schemas import SkillManifest


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def json_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def json_list(value) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return [part.strip() for part in value.split(",") if part.strip()]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def _resolve_distinct_user(db: Session, *, exclude_ids: set[int] | None = None) -> User | None:
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


def build_manifest(defn: dict) -> SkillManifest:
    return SkillManifest(
        skill_code=defn["skill_code"],
        version=defn.get("version", "1.0.0"),
        chinese_name=defn["skill_name"],
        chinese_description=defn["skill_description"],
        entrypoint=defn.get("entrypoint", "mock_executor"),
        skill_type=defn["skill_type"],
        risk_level=defn["risk_level"],
        required_capabilities=defn.get("required_capabilities", []),
        required_permissions=defn.get("required_permissions", []),
        allowed_employee_codes=defn.get("allowed_employee_codes", []),
        input_schema=defn.get("input_schema", {}),
        output_schema=defn.get("output_schema", {}),
        timeout_seconds=defn.get("timeout_seconds", 20),
        max_retries=defn.get("max_retries", 1),
        network_access=defn.get("network_access", False),
        filesystem_access=defn.get("filesystem_access", False),
        browser_access=defn.get("browser_access", False),
        computer_access=defn.get("computer_access", False),
        mobile_access=defn.get("mobile_access", False),
        shell_access=defn.get("shell_access", False),
        secrets_required=defn.get("secrets_required", False),
        audit_required=defn.get("audit_required", True),
        required_feature_flags=defn.get("required_feature_flags", []),
        min_runtime_version=defn.get("min_runtime_version"),
        max_runtime_version=defn.get("max_runtime_version"),
        license=defn.get("license"),
        checksum=defn.get("checksum"),
        signature_status=defn.get("signature_status"),
    )


def ensure_default_skills(db: Session, *, created_by: int | None = None) -> list[Skill]:
    rows = []
    for definition in MOCK_SKILL_DEFINITIONS:
        rows.append(ensure_skill(db, definition, created_by=created_by))
    return rows


def ensure_skill(db: Session, definition: dict, *, created_by: int | None = None) -> Skill:
    skill = db.query(Skill).filter(Skill.skill_code == definition["skill_code"]).one_or_none()
    manifest = build_manifest(definition)
    if not skill:
        reviewer = _resolve_distinct_user(db, exclude_ids={created_by} if created_by is not None else set())
        approver = _resolve_distinct_user(
            db,
            exclude_ids={item for item in {created_by, reviewer.id if reviewer else None} if item is not None},
        )
        skill = Skill(
            skill_code=definition["skill_code"],
            chinese_name=definition["skill_name"],
            chinese_description=definition["skill_description"],
            skill_type=definition["skill_type"],
            category=definition["category"],
            status=definition.get("status", "已批准"),
            risk_level=definition["risk_level"],
            publisher_type=definition["publisher_type"],
            publisher_name=definition["publisher_name"],
            source_type=definition["source_type"],
            source_url=definition["source_url"],
            license=definition["license"],
            checksum=definition["checksum"],
            signature_status=definition["signature_status"],
            enabled=definition.get("enabled", False),
            deprecated=definition.get("deprecated", False),
            created_by=created_by,
        )
        db.add(skill)
        db.flush()
        version = SkillVersion(
            skill_id=skill.id,
            version=manifest.version,
            manifest=json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False),
            input_schema=json_text(manifest.input_schema),
            output_schema=json_text(manifest.output_schema),
            required_capabilities=json_text(manifest.required_capabilities),
            required_permissions=json_text(manifest.required_permissions),
            required_feature_flags=json_text(manifest.required_feature_flags),
            min_runtime_version=manifest.min_runtime_version,
            max_runtime_version=manifest.max_runtime_version,
            checksum=definition["checksum"],
            signature=definition["signature_status"],
            release_notes="系统内置安全技能",
            created_by=created_by,
            reviewed_by=reviewer.id if reviewer else created_by,
            approved_by=approver.id if approver else (reviewer.id if reviewer else created_by),
            approved_at=utcnow(),
        )
        db.add(version)
        db.flush()
        skill.current_version_id = version.id
        for capability in definition.get("required_capabilities", []):
            db.add(
                SkillCapabilityRelation(
                    skill_id=skill.id,
                    skill_version_id=version.id,
                    capability_code=capability,
                )
            )
        for employee_code in definition.get("allowed_employee_codes", []):
            employee = db.query(AiEmployee).filter(AiEmployee.employee_code == employee_code).one_or_none()
            if employee:
                db.add(
                    SkillEmployeePermission(
                        skill_id=skill.id,
                        skill_version_id=version.id,
                        employee_id=employee.id,
                        permission_scope="employee",
                        allow=True,
                        risk_limit=definition["risk_level"],
                        environment_limit="test,development,staging,production",
                        approved_by=created_by,
                        approved_at=utcnow(),
                    )
                )
        db.commit()
        db.refresh(skill)
        return skill

    if skill.current_version_id is None:
        version = db.query(SkillVersion).filter(SkillVersion.skill_id == skill.id).order_by(SkillVersion.id.desc()).first()
        if version:
            skill.current_version_id = version.id
            db.commit()
            db.refresh(skill)
    return skill


def skill_to_dict(skill: Skill, *, include_relations: bool = True) -> dict:
    current_version = next((version for version in skill.versions if version.id == skill.current_version_id), None)
    return {
        "skill_id": skill.id,
        "skill_code": skill.skill_code,
        "chinese_name": skill.chinese_name,
        "chinese_description": skill.chinese_description,
        "skill_type": skill.skill_type,
        "category": skill.category,
        "status": skill.status,
        "risk_level": skill.risk_level,
        "current_version_id": skill.current_version_id,
        "publisher_type": skill.publisher_type,
        "publisher_name": skill.publisher_name,
        "source_type": skill.source_type,
        "source_url": skill.source_url,
        "license": skill.license,
        "checksum": skill.checksum,
        "signature_status": skill.signature_status,
        "enabled": bool(skill.enabled),
        "deprecated": bool(skill.deprecated),
        "created_by": skill.created_by,
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
        "current_version": skill_version_to_dict(current_version) if current_version and include_relations else None,
        "installed_count": len([item for item in skill.installations if item.status in {"已安装", "已启用"}]),
        "enabled_count": len([item for item in skill.installations if item.status == "已启用"]),
        "permission_count": len(skill.permissions),
        "capability_codes": [row.capability_code for row in skill.capability_relations],
    }


def skill_version_to_dict(version: SkillVersion | None) -> dict | None:
    if not version:
        return None
    return {
        "skill_version_id": version.id,
        "skill_id": version.skill_id,
        "version": version.version,
        "manifest": json.loads(version.manifest) if version.manifest else None,
        "input_schema": json.loads(version.input_schema) if version.input_schema else None,
        "output_schema": json.loads(version.output_schema) if version.output_schema else None,
        "required_capabilities": json_list(version.required_capabilities),
        "required_permissions": json_list(version.required_permissions),
        "required_feature_flags": json_list(version.required_feature_flags),
        "min_runtime_version": version.min_runtime_version,
        "max_runtime_version": version.max_runtime_version,
        "checksum": version.checksum,
        "signature": version.signature,
        "release_notes": version.release_notes,
        "created_by": version.created_by,
        "reviewed_by": version.reviewed_by,
        "approved_by": version.approved_by,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "approved_at": version.approved_at.isoformat() if version.approved_at else None,
    }


def installation_to_dict(installation: SkillInstallation) -> dict:
    return {
        "installation_id": installation.id,
        "skill_id": installation.skill_id,
        "skill_version_id": installation.skill_version_id,
        "employee_id": installation.employee_id,
        "department_id": installation.department_id,
        "status": installation.status,
        "installed_by": installation.installed_by,
        "approved_by": installation.approved_by,
        "installed_at": installation.installed_at.isoformat() if installation.installed_at else None,
        "enabled_at": installation.enabled_at.isoformat() if installation.enabled_at else None,
        "disabled_at": installation.disabled_at.isoformat() if installation.disabled_at else None,
        "configuration": json.loads(installation.configuration) if installation.configuration else {},
        "permission_snapshot": json.loads(installation.permission_snapshot) if installation.permission_snapshot else {},
        "checksum_verified": bool(installation.checksum_verified),
        "signature_verified": bool(installation.signature_verified),
        "created_at": installation.created_at.isoformat() if installation.created_at else None,
        "updated_at": installation.updated_at.isoformat() if installation.updated_at else None,
    }


def permission_to_dict(permission: SkillEmployeePermission) -> dict:
    return {
        "permission_id": permission.id,
        "skill_id": permission.skill_id,
        "skill_version_id": permission.skill_version_id,
        "employee_id": permission.employee_id,
        "department_id": permission.department_id,
        "permission_scope": permission.permission_scope,
        "allow": bool(permission.allow),
        "risk_limit": permission.risk_limit,
        "environment_limit": permission.environment_limit,
        "expires_at": permission.expires_at.isoformat() if permission.expires_at else None,
        "approved_by": permission.approved_by,
        "approved_at": permission.approved_at.isoformat() if permission.approved_at else None,
        "created_at": permission.created_at.isoformat() if permission.created_at else None,
        "updated_at": permission.updated_at.isoformat() if permission.updated_at else None,
    }


def invocation_to_dict(invocation: SkillInvocation) -> dict:
    return {
        "invocation_id": invocation.id,
        "skill_id": invocation.skill_id,
        "skill_code": invocation.skill.skill_code if invocation.skill else None,
        "skill_version_id": invocation.skill_version_id,
        "installation_id": invocation.installation_id,
        "employee_id": invocation.employee_id,
        "task_id": invocation.task_id,
        "execution_id": invocation.execution_id,
        "status": invocation.status,
        "input_summary": invocation.input_summary,
        "output_summary": invocation.output_summary,
        "error_code": invocation.error_code,
        "error_message": invocation.error_message,
        "retry_count": invocation.retry_count,
        "started_at": invocation.started_at.isoformat() if invocation.started_at else None,
        "finished_at": invocation.finished_at.isoformat() if invocation.finished_at else None,
        "duration_ms": invocation.duration_ms,
        "trace_id": invocation.trace_id,
        "created_at": invocation.created_at.isoformat() if invocation.created_at else None,
    }


def review_to_dict(review: SkillReview) -> dict:
    return {
        "review_id": review.id,
        "skill_id": review.skill_id,
        "skill_version_id": review.skill_version_id,
        "reviewer_id": review.reviewer_id,
        "decision": review.decision,
        "review_comment": review.review_comment,
        "risk_level": review.risk_level,
        "source_check_result": review.source_check_result,
        "sensitivity_check_result": review.sensitivity_check_result,
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }


def audit_employee_log(db: Session, *, user_id: int | None, action: str, detail: str, skill_id: int | None = None, ip_address: str | None = None):
    if skill_id is not None:
        detail = f"[skill_id={skill_id}] {detail}"
    log = EmployeeLog(user_id=user_id, action=action, detail=detail, ip_address=ip_address)
    db.add(log)
    return log


def resolve_manager_user(db: Session) -> User | None:
    for role in ("owner", "admin"):
        user = db.query(User).filter(User.role == role).order_by(User.id.asc()).first()
        if user:
            return user
    return db.query(User).order_by(User.id.asc()).first()


def list_employee_skill_cards(db: Session, employee_code: str) -> list[dict]:
    employee = db.query(AiEmployee).filter(AiEmployee.employee_code == employee_code).one_or_none()
    if not employee:
        return []
    rows = (
        db.query(Skill)
        .join(SkillEmployeePermission, SkillEmployeePermission.skill_id == Skill.id)
        .join(AiEmployee, AiEmployee.id == SkillEmployeePermission.employee_id)
        .filter(AiEmployee.employee_code == employee_code)
        .order_by(Skill.id.asc())
        .all()
    )
    return [skill_to_employee_card(row, employee_code) for row in rows]


def skill_to_employee_card(skill: Skill, employee_code: str) -> dict:
    return {
        "skill_id": skill.id,
        "skill_code": skill.skill_code,
        "skill_name": skill.chinese_name,
        "skill_type": skill.skill_type,
        "category": skill.category,
        "risk_level": skill.risk_level,
        "status": skill.status,
        "enabled": bool(skill.enabled),
        "current_version": skill.current_version_id,
        "employee_code": employee_code,
        "source": "skills_engine",
        "last_used_at": None,
    }
