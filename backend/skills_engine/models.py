from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("skill_code", name="uq_skills_skill_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    chinese_name: Mapped[str] = mapped_column(String(200), nullable=False)
    chinese_description: Mapped[str | None] = mapped_column(Text)
    skill_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True, default="草稿")
    risk_level: Mapped[str] = mapped_column(String(50), nullable=False, index=True, default="低风险")
    current_version_id: Mapped[int | None] = mapped_column(Integer, index=True)
    publisher_type: Mapped[str | None] = mapped_column(String(50))
    publisher_name: Mapped[str | None] = mapped_column(String(100))
    source_type: Mapped[str | None] = mapped_column(String(80))
    source_url: Mapped[str | None] = mapped_column(Text)
    license: Mapped[str | None] = mapped_column(String(200))
    checksum: Mapped[str | None] = mapped_column(String(255))
    signature_status: Mapped[str] = mapped_column(String(50), nullable=False, default="未验证")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    versions: Mapped[list["SkillVersion"]] = relationship(back_populates="skill", cascade="all, delete-orphan")
    installations: Mapped[list["SkillInstallation"]] = relationship(back_populates="skill")
    permissions: Mapped[list["SkillEmployeePermission"]] = relationship(back_populates="skill")
    invocations: Mapped[list["SkillInvocation"]] = relationship(back_populates="skill")
    reviews: Mapped[list["SkillReview"]] = relationship(back_populates="skill")
    capability_relations: Mapped[list["SkillCapabilityRelation"]] = relationship(back_populates="skill")


class SkillVersion(Base):
    __tablename__ = "skill_versions"
    __table_args__ = (UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    manifest: Mapped[str | None] = mapped_column(Text)
    input_schema: Mapped[str | None] = mapped_column(Text)
    output_schema: Mapped[str | None] = mapped_column(Text)
    required_capabilities: Mapped[str | None] = mapped_column(Text)
    required_permissions: Mapped[str | None] = mapped_column(Text)
    required_feature_flags: Mapped[str | None] = mapped_column(Text)
    min_runtime_version: Mapped[str | None] = mapped_column(String(50))
    max_runtime_version: Mapped[str | None] = mapped_column(String(50))
    checksum: Mapped[str | None] = mapped_column(String(255))
    signature: Mapped[str | None] = mapped_column(Text)
    release_notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    skill: Mapped[Skill] = relationship(back_populates="versions")


class SkillInstallation(Base):
    __tablename__ = "skill_installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_version_id: Mapped[int] = mapped_column(ForeignKey("skill_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("ai_employees.id", ondelete="SET NULL"), index=True)
    department_id: Mapped[str | None] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="待校验", index=True)
    installed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    configuration: Mapped[str | None] = mapped_column(Text)
    permission_snapshot: Mapped[str | None] = mapped_column(Text)
    checksum_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    skill: Mapped[Skill] = relationship(back_populates="installations")


class SkillEmployeePermission(Base):
    __tablename__ = "skill_employee_permissions"
    __table_args__ = (UniqueConstraint("skill_id", "employee_id", "permission_scope", name="uq_skill_employee_permissions"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_version_id: Mapped[int | None] = mapped_column(ForeignKey("skill_versions.id", ondelete="SET NULL"), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("ai_employees.id", ondelete="SET NULL"), index=True)
    department_id: Mapped[str | None] = mapped_column(String(100), index=True)
    permission_scope: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    allow: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    risk_limit: Mapped[str | None] = mapped_column(String(50), index=True)
    environment_limit: Mapped[str | None] = mapped_column(String(50), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    skill: Mapped[Skill] = relationship(back_populates="permissions")


class SkillInvocation(Base):
    __tablename__ = "skill_invocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_version_id: Mapped[int] = mapped_column(ForeignKey("skill_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    installation_id: Mapped[int | None] = mapped_column(ForeignKey("skill_installations.id", ondelete="SET NULL"), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("ai_employees.id", ondelete="SET NULL"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), index=True)
    execution_id: Mapped[int | None] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="待校验", index=True)
    input_summary: Mapped[str | None] = mapped_column(Text)
    output_summary: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    skill: Mapped[Skill] = relationship(back_populates="invocations")


class SkillReview(Base):
    __tablename__ = "skill_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_version_id: Mapped[int | None] = mapped_column(ForeignKey("skill_versions.id", ondelete="SET NULL"), index=True)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    decision: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    review_comment: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str | None] = mapped_column(String(50), index=True)
    source_check_result: Mapped[str | None] = mapped_column(Text)
    sensitivity_check_result: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    skill: Mapped[Skill] = relationship(back_populates="reviews")


class SkillCapabilityRelation(Base):
    __tablename__ = "skill_capability_relations"
    __table_args__ = (UniqueConstraint("skill_id", "skill_version_id", "capability_code", name="uq_skill_capability_relations"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_version_id: Mapped[int | None] = mapped_column(ForeignKey("skill_versions.id", ondelete="SET NULL"), index=True)
    capability_code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    skill: Mapped[Skill] = relationship(back_populates="capability_relations")
