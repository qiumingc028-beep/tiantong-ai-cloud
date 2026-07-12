from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class DeviceRuntimeMetric(Base):
    __tablename__ = "device_runtime_metrics"

    metric_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.device_id", ondelete="SET NULL"), index=True)
    online_status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    agent_version: Mapped[str | None] = mapped_column(String(50), index=True)
    operating_system: Mapped[str | None] = mapped_column(String(80), index=True)
    cpu_usage_percent: Mapped[int | None] = mapped_column(Integer)
    memory_usage_percent: Mapped[int | None] = mapped_column(Integer)
    disk_free_bytes: Mapped[int | None] = mapped_column(Integer)
    agent_process_status: Mapped[str | None] = mapped_column(String(40), index=True)
    current_session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_workflow_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recent_error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recent_screenshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    network_latency_ms: Mapped[int | None] = mapped_column(Integer)
    request_failure_rate: Mapped[int | None] = mapped_column(Integer)
    auth_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replay_block_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    emergency_stop_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)


class ExecutionRuntimeMetric(Base):
    __tablename__ = "execution_runtime_metrics"

    metric_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    execution_id: Mapped[str | None] = mapped_column(String(120), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("ai_employees.id", ondelete="SET NULL"), index=True)
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), index=True)
    workflow_id: Mapped[str | None] = mapped_column(ForeignKey("computer_workflows.workflow_id", ondelete="SET NULL"), index=True)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    canceled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timeout_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_duration_ms: Mapped[int | None] = mapped_column(Integer)
    p50_duration_ms: Mapped[int | None] = mapped_column(Integer)
    p95_duration_ms: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approval_wait_ms: Mapped[int | None] = mapped_column(Integer)
    checkpoint_wait_ms: Mapped[int | None] = mapped_column(Integer)
    verification_fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_change_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_change_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sensitive_block_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    emergency_stop_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    takeover_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    budget_exceeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    single_step_failure_rate: Mapped[int | None] = mapped_column(Integer)
    workflow_completion_rate: Mapped[int | None] = mapped_column(Integer)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    __table_args__ = (UniqueConstraint("scope_type", "scope_id", "captured_at", name="uq_execution_runtime_metrics_scope_capture"),)


class ExecutionQualityScore(Base):
    __tablename__ = "execution_quality_scores"

    score_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    execution_id: Mapped[str | None] = mapped_column(String(120), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("ai_employees.id", ondelete="SET NULL"), index=True)
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"), index=True)
    workflow_id: Mapped[str | None] = mapped_column(ForeignKey("computer_workflows.workflow_id", ondelete="SET NULL"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    grade: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    dimension_scores_json: Mapped[str] = mapped_column(Text, nullable=False)
    deduction_reasons_json: Mapped[str] = mapped_column(Text, nullable=False)
    improvement_suggestions_json: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    __table_args__ = (UniqueConstraint("scope_type", "scope_id", name="uq_execution_quality_scores_scope"),)


class ExecutionRiskScore(Base):
    __tablename__ = "execution_risk_scores"

    score_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    execution_id: Mapped[str | None] = mapped_column(String(120), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("ai_employees.id", ondelete="SET NULL"), index=True)
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"), index=True)
    workflow_id: Mapped[str | None] = mapped_column(ForeignKey("computer_workflows.workflow_id", ondelete="SET NULL"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), index=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    grade: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    dimension_scores_json: Mapped[str] = mapped_column(Text, nullable=False)
    deduction_reasons_json: Mapped[str] = mapped_column(Text, nullable=False)
    improvement_suggestions_json: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    __table_args__ = (UniqueConstraint("scope_type", "scope_id", name="uq_execution_risk_scores_scope"),)


class AnomalyEvent(Base):
    __tablename__ = "anomaly_events"

    anomaly_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    metric_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    rule_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="新发现", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    evidence_references_json: Mapped[str | None] = mapped_column(Text)


class SecurityIncident(Base):
    __tablename__ = "security_incidents"

    incident_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    incident_code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    incident_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="新发现", index=True)
    device_id: Mapped[str | None] = mapped_column(ForeignKey("devices.device_id", ondelete="SET NULL"), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("ai_employees.id", ondelete="SET NULL"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), index=True)
    execution_id: Mapped[str | None] = mapped_column(String(120), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), index=True)
    workflow_id: Mapped[str | None] = mapped_column(ForeignKey("computer_workflows.workflow_id", ondelete="SET NULL"), index=True)
    action_id: Mapped[str | None] = mapped_column(ForeignKey("computer_actions.action_id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    detected_by: Mapped[str | None] = mapped_column(String(80))
    evidence_references_json: Mapped[str | None] = mapped_column(Text)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    automatic_action: Mapped[str | None] = mapped_column(String(80))
    assigned_to: Mapped[str | None] = mapped_column(String(80))
    acknowledged_by: Mapped[str | None] = mapped_column(String(80))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(String(80))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_summary: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)


class AlertRule(Base):
    __tablename__ = "alert_rules"

    rule_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chinese_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    rule_code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    metric_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    condition: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    threshold: Mapped[str] = mapped_column(String(120), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    environment: Mapped[str] = mapped_column(String(40), nullable=False, default="test", index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)


class AlertEvent(Base):
    __tablename__ = "alert_events"

    alert_event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    rule_id: Mapped[str | None] = mapped_column(ForeignKey("alert_rules.rule_id", ondelete="SET NULL"), index=True)
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("security_incidents.incident_id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="已触发", index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    action: Mapped[str | None] = mapped_column(String(80), index=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)


class CircuitBreaker(Base):
    __tablename__ = "circuit_breakers"

    breaker_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    breaker_scope: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    breaker_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="正常", index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    manual_reset_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)

    __table_args__ = (UniqueConstraint("breaker_scope", "breaker_key", name="uq_circuit_breakers_scope_key"),)


class ExecutionReplayIndex(Base):
    __tablename__ = "execution_replay_indexes"

    replay_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("computer_workflows.workflow_id", ondelete="CASCADE"), nullable=False, unique=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("task_center_tasks.id", ondelete="SET NULL"), index=True)
    execution_id: Mapped[str | None] = mapped_column(String(120), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), index=True)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    goal: Mapped[str | None] = mapped_column(Text)
    summary_json: Mapped[str | None] = mapped_column(Text)
    available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)


class EmployeeExecutionMetric(Base):
    __tablename__ = "employee_execution_metrics"

    metric_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    employee_code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    employee_name: Mapped[str | None] = mapped_column(String(120), index=True)
    total_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    success_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    avg_quality_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    avg_risk_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    avg_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    verification_fail_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    takeover_rate: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    security_incident_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    budget_exceeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    canceled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    last_execution_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)


class DeviceHealthScore(Base):
    __tablename__ = "device_health_scores"

    health_score_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False, unique=True)
    score: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    grade: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    dimension_scores_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason_summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(120), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now(), index=True)
