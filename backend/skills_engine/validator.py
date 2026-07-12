from __future__ import annotations

from fastapi import HTTPException

from .schemas import SkillManifest


def validate_manifest(manifest: SkillManifest) -> SkillManifest:
    if not manifest.required_capabilities:
        raise HTTPException(status_code=400, detail="Skill 必须声明至少一个 Capability")
    if not manifest.required_permissions:
        raise HTTPException(status_code=400, detail="Skill 必须声明至少一个权限")
    if manifest.max_retries > 5:
        raise HTTPException(status_code=400, detail="最大重试次数超出限制")
    if manifest.timeout_seconds > 300:
        raise HTTPException(status_code=400, detail="超时时间超出限制")
    if manifest.shell_access or manifest.computer_access or manifest.mobile_access:
        raise HTTPException(status_code=400, detail="本 Sprint 不允许高风险执行器声明")
    if manifest.network_access and manifest.risk_level == "极高风险":
        raise HTTPException(status_code=400, detail="极高风险技能不能开放网络访问")
    return manifest
