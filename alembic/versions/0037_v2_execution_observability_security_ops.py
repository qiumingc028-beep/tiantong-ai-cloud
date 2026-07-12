"""V2 execution observability and security operations center

Revision ID: 0037_v2_execution_observability_security_ops
Revises: 0036_v2_safe_multi_step_workflow
Create Date: 2026-07-12 20:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0037_v2_execution_observability_security_ops"
down_revision = "0036_v2_safe_multi_step_workflow"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "device_runtime_metrics",
        sa.Column("metric_id", sa.String(length=36), primary_key=True),
        sa.Column("device_id", sa.String(length=36), sa.ForeignKey("devices.device_id", ondelete="SET NULL"), nullable=True),
        sa.Column("online_status", sa.String(length=40), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agent_version", sa.String(length=50), nullable=True),
        sa.Column("operating_system", sa.String(length=80), nullable=True),
        sa.Column("cpu_usage_percent", sa.Integer(), nullable=True),
        sa.Column("memory_usage_percent", sa.Integer(), nullable=True),
        sa.Column("disk_free_bytes", sa.Integer(), nullable=True),
        sa.Column("agent_process_status", sa.String(length=40), nullable=True),
        sa.Column("current_session_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("current_workflow_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("recent_error_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("recent_screenshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("network_latency_ms", sa.Integer(), nullable=True),
        sa.Column("request_failure_rate", sa.Integer(), nullable=True),
        sa.Column("auth_failure_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("replay_block_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("emergency_stop_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_device_runtime_metrics_device_id", "device_runtime_metrics", ["device_id"])
    op.create_index("ix_device_runtime_metrics_online_status", "device_runtime_metrics", ["online_status"])
    op.create_index("ix_device_runtime_metrics_last_heartbeat_at", "device_runtime_metrics", ["last_heartbeat_at"])
    op.create_index("ix_device_runtime_metrics_agent_version", "device_runtime_metrics", ["agent_version"])
    op.create_index("ix_device_runtime_metrics_operating_system", "device_runtime_metrics", ["operating_system"])
    op.create_index("ix_device_runtime_metrics_agent_process_status", "device_runtime_metrics", ["agent_process_status"])
    op.create_index("ix_device_runtime_metrics_recent_screenshot_at", "device_runtime_metrics", ["recent_screenshot_at"])
    op.create_index("ix_device_runtime_metrics_trace_id", "device_runtime_metrics", ["trace_id"])
    op.create_index("ix_device_runtime_metrics_captured_at", "device_runtime_metrics", ["captured_at"])
    op.create_index("ix_device_runtime_metrics_created_at", "device_runtime_metrics", ["created_at"])

    op.create_table(
        "execution_runtime_metrics",
        sa.Column("metric_id", sa.String(length=36), primary_key=True),
        sa.Column("scope_type", sa.String(length=40), nullable=False),
        sa.Column("scope_id", sa.String(length=120), nullable=False),
        sa.Column("execution_id", sa.String(length=120), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), nullable=True),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("computer_workflows.workflow_id", ondelete="SET NULL"), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("canceled_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("timeout_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_duration_ms", sa.Integer(), nullable=True),
        sa.Column("p50_duration_ms", sa.Integer(), nullable=True),
        sa.Column("p95_duration_ms", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("approval_wait_ms", sa.Integer(), nullable=True),
        sa.Column("checkpoint_wait_ms", sa.Integer(), nullable=True),
        sa.Column("verification_fail_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("page_change_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("window_change_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("sensitive_block_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("emergency_stop_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("takeover_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("budget_exceeded_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("single_step_failure_rate", sa.Integer(), nullable=True),
        sa.Column("workflow_completion_rate", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("scope_type", "scope_id", "captured_at", name="uq_execution_runtime_metrics_scope_capture"),
    )
    for name, cols in [
        ("ix_execution_runtime_metrics_scope_type", ["scope_type"]),
        ("ix_execution_runtime_metrics_scope_id", ["scope_id"]),
        ("ix_execution_runtime_metrics_execution_id", ["execution_id"]),
        ("ix_execution_runtime_metrics_task_id", ["task_id"]),
        ("ix_execution_runtime_metrics_employee_id", ["employee_id"]),
        ("ix_execution_runtime_metrics_skill_id", ["skill_id"]),
        ("ix_execution_runtime_metrics_session_id", ["session_id"]),
        ("ix_execution_runtime_metrics_workflow_id", ["workflow_id"]),
        ("ix_execution_runtime_metrics_captured_at", ["captured_at"]),
        ("ix_execution_runtime_metrics_trace_id", ["trace_id"]),
        ("ix_execution_runtime_metrics_created_at", ["created_at"]),
        ("ix_execution_runtime_metrics_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "execution_runtime_metrics", cols)

    op.create_table(
        "execution_quality_scores",
        sa.Column("score_id", sa.String(length=36), primary_key=True),
        sa.Column("scope_type", sa.String(length=40), nullable=False),
        sa.Column("scope_id", sa.String(length=120), nullable=False),
        sa.Column("execution_id", sa.String(length=120), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("computer_workflows.workflow_id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("grade", sa.String(length=20), nullable=False),
        sa.Column("dimension_scores_json", sa.Text(), nullable=False),
        sa.Column("deduction_reasons_json", sa.Text(), nullable=False),
        sa.Column("improvement_suggestions_json", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("scope_type", "scope_id", name="uq_execution_quality_scores_scope"),
    )
    for name, cols in [
        ("ix_execution_quality_scores_scope_type", ["scope_type"]),
        ("ix_execution_quality_scores_scope_id", ["scope_id"]),
        ("ix_execution_quality_scores_execution_id", ["execution_id"]),
        ("ix_execution_quality_scores_task_id", ["task_id"]),
        ("ix_execution_quality_scores_employee_id", ["employee_id"]),
        ("ix_execution_quality_scores_skill_id", ["skill_id"]),
        ("ix_execution_quality_scores_workflow_id", ["workflow_id"]),
        ("ix_execution_quality_scores_session_id", ["session_id"]),
        ("ix_execution_quality_scores_score", ["score"]),
        ("ix_execution_quality_scores_grade", ["grade"]),
        ("ix_execution_quality_scores_trace_id", ["trace_id"]),
        ("ix_execution_quality_scores_created_at", ["created_at"]),
        ("ix_execution_quality_scores_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "execution_quality_scores", cols)

    op.create_table(
        "execution_risk_scores",
        sa.Column("score_id", sa.String(length=36), primary_key=True),
        sa.Column("scope_type", sa.String(length=40), nullable=False),
        sa.Column("scope_id", sa.String(length=120), nullable=False),
        sa.Column("execution_id", sa.String(length=120), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("computer_workflows.workflow_id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), nullable=True),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("grade", sa.String(length=20), nullable=False),
        sa.Column("dimension_scores_json", sa.Text(), nullable=False),
        sa.Column("deduction_reasons_json", sa.Text(), nullable=False),
        sa.Column("improvement_suggestions_json", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("scope_type", "scope_id", name="uq_execution_risk_scores_scope"),
    )
    for name, cols in [
        ("ix_execution_risk_scores_scope_type", ["scope_type"]),
        ("ix_execution_risk_scores_scope_id", ["scope_id"]),
        ("ix_execution_risk_scores_execution_id", ["execution_id"]),
        ("ix_execution_risk_scores_task_id", ["task_id"]),
        ("ix_execution_risk_scores_employee_id", ["employee_id"]),
        ("ix_execution_risk_scores_skill_id", ["skill_id"]),
        ("ix_execution_risk_scores_workflow_id", ["workflow_id"]),
        ("ix_execution_risk_scores_session_id", ["session_id"]),
        ("ix_execution_risk_scores_score", ["score"]),
        ("ix_execution_risk_scores_grade", ["grade"]),
        ("ix_execution_risk_scores_trace_id", ["trace_id"]),
        ("ix_execution_risk_scores_created_at", ["created_at"]),
        ("ix_execution_risk_scores_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "execution_risk_scores", cols)

    op.create_table(
        "anomaly_events",
        sa.Column("anomaly_id", sa.String(length=36), primary_key=True),
        sa.Column("metric_name", sa.String(length=120), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.String(length=120), nullable=False),
        sa.Column("rule_code", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'新发现'")),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("evidence_references_json", sa.Text(), nullable=True),
    )
    for name, cols in [
        ("ix_anomaly_events_metric_name", ["metric_name"]),
        ("ix_anomaly_events_entity_type", ["entity_type"]),
        ("ix_anomaly_events_entity_id", ["entity_id"]),
        ("ix_anomaly_events_rule_code", ["rule_code"]),
        ("ix_anomaly_events_severity", ["severity"]),
        ("ix_anomaly_events_status", ["status"]),
        ("ix_anomaly_events_detected_at", ["detected_at"]),
        ("ix_anomaly_events_trace_id", ["trace_id"]),
    ]:
        op.create_index(name, "anomaly_events", cols)

    op.create_table(
        "security_incidents",
        sa.Column("incident_id", sa.String(length=36), primary_key=True),
        sa.Column("incident_code", sa.String(length=80), nullable=False),
        sa.Column("incident_type", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'新发现'")),
        sa.Column("device_id", sa.String(length=36), sa.ForeignKey("devices.device_id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("execution_id", sa.String(length=120), nullable=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), nullable=True),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("computer_workflows.workflow_id", ondelete="SET NULL"), nullable=True),
        sa.Column("action_id", sa.String(length=36), sa.ForeignKey("computer_actions.action_id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("detected_by", sa.String(length=80), nullable=True),
        sa.Column("evidence_references_json", sa.Text(), nullable=True),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("automatic_action", sa.String(length=80), nullable=True),
        sa.Column("assigned_to", sa.String(length=80), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=80), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=80), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_summary", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("incident_code", name="uq_security_incidents_incident_code"),
    )
    for name, cols in [
        ("ix_security_incidents_incident_type", ["incident_type"]),
        ("ix_security_incidents_severity", ["severity"]),
        ("ix_security_incidents_status", ["status"]),
        ("ix_security_incidents_device_id", ["device_id"]),
        ("ix_security_incidents_employee_id", ["employee_id"]),
        ("ix_security_incidents_task_id", ["task_id"]),
        ("ix_security_incidents_execution_id", ["execution_id"]),
        ("ix_security_incidents_session_id", ["session_id"]),
        ("ix_security_incidents_workflow_id", ["workflow_id"]),
        ("ix_security_incidents_action_id", ["action_id"]),
        ("ix_security_incidents_detected_at", ["detected_at"]),
        ("ix_security_incidents_trace_id", ["trace_id"]),
        ("ix_security_incidents_created_at", ["created_at"]),
        ("ix_security_incidents_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "security_incidents", cols)

    op.create_table(
        "alert_rules",
        sa.Column("rule_id", sa.String(length=36), primary_key=True),
        sa.Column("chinese_name", sa.String(length=120), nullable=False),
        sa.Column("rule_code", sa.String(length=80), nullable=False),
        sa.Column("metric_name", sa.String(length=120), nullable=False),
        sa.Column("condition", sa.String(length=40), nullable=False),
        sa.Column("threshold", sa.String(length=120), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("environment", sa.String(length=40), nullable=False, server_default=sa.text("'test'")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("rule_code", name="uq_alert_rules_rule_code"),
    )
    for name, cols in [
        ("ix_alert_rules_chinese_name", ["chinese_name"]),
        ("ix_alert_rules_metric_name", ["metric_name"]),
        ("ix_alert_rules_condition", ["condition"]),
        ("ix_alert_rules_severity", ["severity"]),
        ("ix_alert_rules_action", ["action"]),
        ("ix_alert_rules_enabled", ["enabled"]),
        ("ix_alert_rules_environment", ["environment"]),
        ("ix_alert_rules_created_by", ["created_by"]),
        ("ix_alert_rules_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "alert_rules", cols)

    op.create_table(
        "alert_events",
        sa.Column("alert_event_id", sa.String(length=36), primary_key=True),
        sa.Column("rule_id", sa.String(length=36), sa.ForeignKey("alert_rules.rule_id", ondelete="SET NULL"), nullable=True),
        sa.Column("incident_id", sa.String(length=36), sa.ForeignKey("security_incidents.incident_id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'已触发'")),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
    )
    for name, cols in [
        ("ix_alert_events_rule_id", ["rule_id"]),
        ("ix_alert_events_incident_id", ["incident_id"]),
        ("ix_alert_events_status", ["status"]),
        ("ix_alert_events_severity", ["severity"]),
        ("ix_alert_events_action", ["action"]),
        ("ix_alert_events_triggered_at", ["triggered_at"]),
        ("ix_alert_events_trace_id", ["trace_id"]),
    ]:
        op.create_index(name, "alert_events", cols)

    op.create_table(
        "circuit_breakers",
        sa.Column("breaker_id", sa.String(length=36), primary_key=True),
        sa.Column("breaker_scope", sa.String(length=80), nullable=False),
        sa.Column("breaker_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'正常'")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("trigger_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("risk_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manual_reset_required", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("breaker_scope", "breaker_key", name="uq_circuit_breakers_scope_key"),
    )
    for name, cols in [
        ("ix_circuit_breakers_breaker_scope", ["breaker_scope"]),
        ("ix_circuit_breakers_breaker_key", ["breaker_key"]),
        ("ix_circuit_breakers_status", ["status"]),
        ("ix_circuit_breakers_risk_score", ["risk_score"]),
        ("ix_circuit_breakers_triggered_at", ["triggered_at"]),
        ("ix_circuit_breakers_reset_at", ["reset_at"]),
        ("ix_circuit_breakers_manual_reset_required", ["manual_reset_required"]),
        ("ix_circuit_breakers_trace_id", ["trace_id"]),
        ("ix_circuit_breakers_created_at", ["created_at"]),
        ("ix_circuit_breakers_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "circuit_breakers", cols)

    op.create_table(
        "execution_replay_indexes",
        sa.Column("replay_id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_id", sa.String(length=36), sa.ForeignKey("computer_workflows.workflow_id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("execution_id", sa.String(length=120), nullable=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), nullable=True),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("summary_json", sa.Text(), nullable=True),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("workflow_id", name="uq_execution_replay_indexes_workflow"),
    )
    for name, cols in [
        ("ix_execution_replay_indexes_task_id", ["task_id"]),
        ("ix_execution_replay_indexes_execution_id", ["execution_id"]),
        ("ix_execution_replay_indexes_session_id", ["session_id"]),
        ("ix_execution_replay_indexes_step_count", ["step_count"]),
        ("ix_execution_replay_indexes_available", ["available"]),
        ("ix_execution_replay_indexes_trace_id", ["trace_id"]),
        ("ix_execution_replay_indexes_created_at", ["created_at"]),
        ("ix_execution_replay_indexes_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "execution_replay_indexes", cols)

    op.create_table(
        "employee_execution_metrics",
        sa.Column("metric_id", sa.String(length=36), primary_key=True),
        sa.Column("employee_code", sa.String(length=80), nullable=False),
        sa.Column("employee_name", sa.String(length=120), nullable=True),
        sa.Column("total_tasks", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success_rate", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_quality_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_risk_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_duration_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("verification_fail_rate", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("takeover_rate", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("security_incident_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("budget_exceeded_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("canceled_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_execution_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("employee_code", name="uq_employee_execution_metrics_employee_code"),
    )
    for name, cols in [
        ("ix_employee_execution_metrics_employee_name", ["employee_name"]),
        ("ix_employee_execution_metrics_total_tasks", ["total_tasks"]),
        ("ix_employee_execution_metrics_success_count", ["success_count"]),
        ("ix_employee_execution_metrics_success_rate", ["success_rate"]),
        ("ix_employee_execution_metrics_avg_quality_score", ["avg_quality_score"]),
        ("ix_employee_execution_metrics_avg_risk_score", ["avg_risk_score"]),
        ("ix_employee_execution_metrics_avg_duration_ms", ["avg_duration_ms"]),
        ("ix_employee_execution_metrics_verification_fail_rate", ["verification_fail_rate"]),
        ("ix_employee_execution_metrics_takeover_rate", ["takeover_rate"]),
        ("ix_employee_execution_metrics_security_incident_count", ["security_incident_count"]),
        ("ix_employee_execution_metrics_budget_exceeded_count", ["budget_exceeded_count"]),
        ("ix_employee_execution_metrics_canceled_count", ["canceled_count"]),
        ("ix_employee_execution_metrics_consecutive_failures", ["consecutive_failures"]),
        ("ix_employee_execution_metrics_last_execution_at", ["last_execution_at"]),
        ("ix_employee_execution_metrics_trace_id", ["trace_id"]),
        ("ix_employee_execution_metrics_created_at", ["created_at"]),
        ("ix_employee_execution_metrics_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "employee_execution_metrics", cols)

    op.create_table(
        "device_health_scores",
        sa.Column("health_score_id", sa.String(length=36), primary_key=True),
        sa.Column("device_id", sa.String(length=36), sa.ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("grade", sa.String(length=20), nullable=False),
        sa.Column("dimension_scores_json", sa.Text(), nullable=False),
        sa.Column("reason_summary_json", sa.Text(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("device_id", name="uq_device_health_scores_device_id"),
    )
    for name, cols in [
        ("ix_device_health_scores_score", ["score"]),
        ("ix_device_health_scores_grade", ["grade"]),
        ("ix_device_health_scores_computed_at", ["computed_at"]),
        ("ix_device_health_scores_trace_id", ["trace_id"]),
        ("ix_device_health_scores_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "device_health_scores", cols)


def downgrade():
    for table in [
        "device_health_scores",
        "employee_execution_metrics",
        "execution_replay_indexes",
        "circuit_breakers",
        "alert_events",
        "alert_rules",
        "security_incidents",
        "anomaly_events",
        "execution_risk_scores",
        "execution_quality_scores",
        "execution_runtime_metrics",
        "device_runtime_metrics",
    ]:
        op.drop_table(table)

