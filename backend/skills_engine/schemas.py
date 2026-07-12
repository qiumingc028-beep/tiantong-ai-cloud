from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from .constants import INSTALLATION_STATUSES, INVOCATION_STATUSES, SKILL_RISK_LEVELS, SKILL_STATUSES, SKILL_TYPES


def _clean_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


class SkillManifest(BaseModel):
    skill_code: str = Field(min_length=2, max_length=120)
    version: str = Field(min_length=1, max_length=50)
    chinese_name: str = Field(min_length=1, max_length=200)
    chinese_description: str = Field(min_length=1, max_length=2000)
    entrypoint: str = Field(min_length=1, max_length=200)
    skill_type: str
    risk_level: str
    required_capabilities: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    allowed_employee_codes: list[str] = Field(default_factory=list)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    timeout_seconds: int = Field(default=20, ge=1, le=300)
    max_retries: int = Field(default=0, ge=0, le=5)
    network_access: bool = False
    filesystem_access: bool = False
    browser_access: bool = False
    computer_access: bool = False
    mobile_access: bool = False
    shell_access: bool = False
    secrets_required: bool = False
    audit_required: bool = True
    required_feature_flags: list[str] = Field(default_factory=list)
    min_runtime_version: str | None = None
    max_runtime_version: str | None = None
    license: str | None = None
    checksum: str | None = None
    signature_status: str | None = None

    @field_validator("skill_type")
    @classmethod
    def validate_skill_type(cls, value: str) -> str:
        if value not in SKILL_TYPES:
            raise ValueError("技能类型不被允许")
        return value

    @field_validator("risk_level")
    @classmethod
    def validate_risk_level(cls, value: str) -> str:
        if value not in SKILL_RISK_LEVELS:
            raise ValueError("风险等级不被允许")
        return value

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str) -> str:
        forbidden = {"shell", "os.system", "subprocess", "playwright", "openclaw", "computer", "mobile"}
        lowered = value.lower()
        if any(word in lowered for word in forbidden):
            raise ValueError("入口必须是安全声明的适配器名称")
        return value

    @field_validator("required_capabilities", "required_permissions", "allowed_employee_codes", "required_feature_flags", mode="before")
    @classmethod
    def normalize_lists(cls, value):
        return _clean_list(value)

    @model_validator(mode="after")
    def validate_access_flags(self):
        if self.shell_access or self.computer_access or self.mobile_access:
            raise ValueError("本 Sprint 禁止声明高风险执行器访问")
        if self.network_access and self.risk_level == "极高风险":
            raise ValueError("极高风险技能不得声明网络访问")
        return self


class SkillCreatePayload(BaseModel):
    skill_code: str
    chinese_name: str
    chinese_description: str | None = None
    skill_type: str
    category: str | None = None
    risk_level: str = "低风险"
    publisher_type: str | None = "内部"
    publisher_name: str | None = "天统AI云中台"
    source_type: str | None = "内部定义"
    source_url: str | None = None
    license: str | None = None
    checksum: str | None = None
    signature_status: str = "未验证"
    enabled: bool = False
    deprecated: bool = False
    manifest: SkillManifest
    status: str = "草稿"


class SkillVersionCreatePayload(BaseModel):
    version: str
    manifest: SkillManifest
    release_notes: str | None = None
    approved: bool = False


class SkillInstallPayload(BaseModel):
    employee_code: str
    department_id: str | None = None
    configuration: dict = Field(default_factory=dict)


class SkillPermissionPayload(BaseModel):
    employee_code: str | None = None
    department_id: str | None = None
    permission_scope: str = "employee"
    allow: bool = True
    risk_limit: str | None = None
    environment_limit: str | None = None
    expires_at: datetime | None = None


class SkillInvokePayload(BaseModel):
    employee_code: str
    input_payload: dict = Field(default_factory=dict)
    task_id: int | None = None
    execution_id: int | None = None
    installation_id: int | None = None
    trace_id: str | None = None
    simulate_outcome: str | None = None
    timeout_seconds: int | None = None


class SkillReviewPayload(BaseModel):
    decision: str
    review_comment: str | None = None
    source_check_result: str | None = None
    sensitivity_check_result: str | None = None


class SkillUpdatePayload(BaseModel):
    chinese_name: str | None = None
    chinese_description: str | None = None
    category: str | None = None
    risk_level: str | None = None
    status: str | None = None
    enabled: bool | None = None
    deprecated: bool | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None):
        if value is not None and value not in SKILL_STATUSES:
            raise ValueError("技能状态不被允许")
        return value

    @field_validator("risk_level")
    @classmethod
    def validate_risk_level(cls, value: str | None):
        if value is not None and value not in SKILL_RISK_LEVELS:
            raise ValueError("风险等级不被允许")
        return value


class SkillStatusUpdatePayload(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str):
        if value not in INSTALLATION_STATUSES and value not in INVOCATION_STATUSES and value not in SKILL_STATUSES:
            raise ValueError("状态不被允许")
        return value
