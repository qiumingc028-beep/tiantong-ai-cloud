from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import current_user
from ..auth_data import normalize_role
from ..models import AiEmployee, User
from .constants import DEFAULT_AGENT_FEATURES, DEFAULT_SKILL_ENGINE_FEATURES, SKILL_RISK_LEVELS
from .models import Skill, SkillEmployeePermission, SkillInstallation
def get_flag(name: str) -> bool:
    from ..config import get_settings

    settings = get_settings()
    if hasattr(settings, name):
        return bool(getattr(settings, name))
    if name in DEFAULT_SKILL_ENGINE_FEATURES:
        return bool(DEFAULT_SKILL_ENGINE_FEATURES[name])
    if name in DEFAULT_AGENT_FEATURES:
        return bool(DEFAULT_AGENT_FEATURES[name])
    return False


def require_skills_user(request: Request, db: Session):
    user = current_user(request, db)
    role = normalize_role(user.role)
    if role not in {"owner", "admin", "operator"}:
        raise HTTPException(status_code=403, detail="没有技能中心访问权限")
    return user


def require_skills_manage_user(request: Request, db: Session):
    user = current_user(request, db)
    if normalize_role(user.role) not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="没有技能管理权限")
    return user


def require_feature_enabled(name: str):
    if not get_flag(name):
        raise HTTPException(status_code=403, detail="技能功能当前未开启")


def get_employee(db: Session, employee_code: str) -> AiEmployee:
    employee = db.query(AiEmployee).filter(AiEmployee.employee_code == employee_code).one_or_none()
    if not employee:
        raise HTTPException(status_code=404, detail="AI员工不存在")
    return employee


def require_employee_permission(db: Session, skill: Skill, employee_code: str, *, version_id: int | None = None):
    employee = get_employee(db, employee_code)
    if employee.status != "active":
        raise HTTPException(status_code=403, detail="AI员工未启用，无法调用技能")
    permissions = (
        db.query(SkillEmployeePermission)
        .filter(SkillEmployeePermission.skill_id == skill.id)
        .all()
    )
    if not permissions:
        raise HTTPException(status_code=403, detail="该技能尚未授权给任何AI员工")
    current = next((row for row in permissions if permission_scope_allows(row, employee)), None)
    if not current:
        raise HTTPException(status_code=403, detail="当前AI员工未获得该技能授权")
    if current.expires_at and current.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=403, detail="技能授权已过期")
    if version_id is not None and current.skill_version_id not in {None, version_id}:
        raise HTTPException(status_code=403, detail="当前授权版本不兼容")
    return employee, current


def check_skill_installable(skill: Skill, installation: SkillInstallation | None, *, third_party_allowed: bool = False, unsigned_allowed: bool = False):
    if not get_flag("SKILL_INSTALLATION_ENABLED"):
        raise HTTPException(status_code=403, detail="技能安装功能当前未开启")
    if not skill.enabled and skill.status not in {"已批准", "已发布", "已安装", "已启用"}:
        raise HTTPException(status_code=403, detail="技能尚未批准，不能安装")
    if skill.signature_status == "未验证" and not unsigned_allowed:
        raise HTTPException(status_code=403, detail="未签名技能默认禁止启用")
    if skill.publisher_type == "第三方" and not third_party_allowed:
        raise HTTPException(status_code=403, detail="第三方技能默认禁止")
    if installation and installation.status in {"已撤销", "已卸载"}:
        raise HTTPException(status_code=403, detail="安装记录已失效")


def check_skill_invokable(db: Session, skill: Skill, employee_code: str, *, installation: SkillInstallation | None = None):
    require_feature_enabled("SKILL_INVOCATION_ENABLED")
    if skill.deprecated:
        raise HTTPException(status_code=403, detail="已废弃技能不可调用")
    if skill.status not in {"已安装", "已启用", "已发布", "已批准"} and not skill.enabled:
        raise HTTPException(status_code=403, detail="技能未启用")
    if installation and installation.status not in {"已安装", "已启用"}:
        raise HTTPException(status_code=403, detail="当前安装未启用")
    return require_employee_permission(db, skill, employee_code, version_id=skill.current_version_id)


def normalize_risk_level(value: str | None) -> str:
    value = (value or "").strip()
    if value in SKILL_RISK_LEVELS:
        return value
    return "低风险"


def skill_is_high_risk(skill: Skill) -> bool:
    return normalize_risk_level(skill.risk_level) in {"高风险", "极高风险"}


def can_manage_skill(user: User) -> bool:
    return normalize_role(user.role) in {"owner", "admin"}


def can_read_skill(user: User) -> bool:
    return normalize_role(user.role) in {"owner", "admin", "operator"}


def permission_scope_allows(permission: SkillEmployeePermission, employee: AiEmployee) -> bool:
    if not permission.allow:
        return False
    scope = (permission.permission_scope or "").strip().lower()
    if scope in {"global", "all"}:
        return True
    if permission.employee_id and permission.employee_id != employee.id:
        return False
    if permission.department_id and permission.department_id != (employee.legion or ""):
        return False
    return True


def required_feature_flag_missing(skill_feature_flags: list[str]) -> list[str]:
    return [flag for flag in skill_feature_flags if not get_flag(flag)]
