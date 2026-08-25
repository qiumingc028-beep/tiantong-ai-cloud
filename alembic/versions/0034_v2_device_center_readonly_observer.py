"""V2 device center readonly observer

Revision ID: 0034_v2_device_center_readonly_observer
Revises: 0033_v2_computer_executor_foundation
Create Date: 2026-07-12 15:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0034_v2_device_center_readonly_observer"
down_revision = "0033_v2_computer_executor_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "device_registration_tokens",
        sa.Column("token_id", sa.String(length=36), primary_key=True),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("device_type", sa.String(length=50), nullable=False),
        sa.Column("environment_type", sa.String(length=40), nullable=False, server_default=sa.text("'test'")),
        sa.Column("allowed_capabilities_json", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, cols in [
        ("ix_device_registration_tokens_token_hash", ["token_hash"]),
        ("ix_device_registration_tokens_device_type", ["device_type"]),
        ("ix_device_registration_tokens_environment_type", ["environment_type"]),
        ("ix_device_registration_tokens_expires_at", ["expires_at"]),
        ("ix_device_registration_tokens_used_at", ["used_at"]),
        ("ix_device_registration_tokens_revoked_at", ["revoked_at"]),
        ("ix_device_registration_tokens_created_by", ["created_by"]),
        ("ix_device_registration_tokens_created_at", ["created_at"]),
    ]:
        op.create_index(name, "device_registration_tokens", cols)

    op.create_table(
        "devices",
        sa.Column("device_id", sa.String(length=36), primary_key=True),
        sa.Column("device_code", sa.String(length=80), nullable=False),
        sa.Column("chinese_name", sa.String(length=200), nullable=False),
        sa.Column("device_type", sa.String(length=50), nullable=False),
        sa.Column("operating_system", sa.String(length=80), nullable=False),
        sa.Column("architecture", sa.String(length=40), nullable=False),
        sa.Column("agent_version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'待注册'")),
        sa.Column("trust_level", sa.String(length=40), nullable=False, server_default=sa.text("'测试'")),
        sa.Column("environment_type", sa.String(length=40), nullable=False, server_default=sa.text("'test'")),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("registered_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ip_hash", sa.String(length=128), nullable=True),
        sa.Column("certificate_fingerprint", sa.String(length=255), nullable=True),
        sa.Column("capabilities_json", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("device_code", name="uq_devices_device_code"),
    )
    for name, cols in [
        ("ix_devices_device_code", ["device_code"]),
        ("ix_devices_chinese_name", ["chinese_name"]),
        ("ix_devices_device_type", ["device_type"]),
        ("ix_devices_operating_system", ["operating_system"]),
        ("ix_devices_architecture", ["architecture"]),
        ("ix_devices_agent_version", ["agent_version"]),
        ("ix_devices_status", ["status"]),
        ("ix_devices_trust_level", ["trust_level"]),
        ("ix_devices_environment_type", ["environment_type"]),
        ("ix_devices_owner_id", ["owner_id"]),
        ("ix_devices_registered_by", ["registered_by"]),
        ("ix_devices_approved_by", ["approved_by"]),
        ("ix_devices_last_seen_at", ["last_seen_at"]),
        ("ix_devices_last_ip_hash", ["last_ip_hash"]),
        ("ix_devices_certificate_fingerprint", ["certificate_fingerprint"]),
        ("ix_devices_enabled", ["enabled"]),
        ("ix_devices_revoked_at", ["revoked_at"]),
        ("ix_devices_approved_at", ["approved_at"]),
        ("ix_devices_created_at", ["created_at"]),
        ("ix_devices_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "devices", cols)

    op.create_table(
        "device_credentials",
        sa.Column("credential_id", sa.String(length=36), primary_key=True),
        sa.Column("device_id", sa.String(length=36), sa.ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False),
        sa.Column("credential_type", sa.String(length=40), nullable=False, server_default=sa.text("'signature'")),
        sa.Column("credential_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'有效'")),
        sa.Column("public_key_fingerprint", sa.String(length=255), nullable=True),
        sa.Column("last_nonce", sa.String(length=255), nullable=True),
        sa.Column("last_request_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("device_id", "credential_fingerprint", name="uq_device_credentials_device_fingerprint"),
    )
    for name, cols in [
        ("ix_device_credentials_device_id", ["device_id"]),
        ("ix_device_credentials_credential_type", ["credential_type"]),
        ("ix_device_credentials_credential_fingerprint", ["credential_fingerprint"]),
        ("ix_device_credentials_status", ["status"]),
        ("ix_device_credentials_public_key_fingerprint", ["public_key_fingerprint"]),
        ("ix_device_credentials_last_nonce", ["last_nonce"]),
        ("ix_device_credentials_last_request_at", ["last_request_at"]),
        ("ix_device_credentials_revoked_at", ["revoked_at"]),
        ("ix_device_credentials_created_at", ["created_at"]),
        ("ix_device_credentials_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "device_credentials", cols)

    op.create_table(
        "device_observation_sessions",
        sa.Column("observation_id", sa.String(length=36), primary_key=True),
        sa.Column("device_id", sa.String(length=36), sa.ForeignKey("devices.device_id", ondelete="CASCADE"), nullable=False),
        sa.Column("computer_session_id", sa.String(length=36), sa.ForeignKey("computer_sessions.session_id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default=sa.text("'等待设备'")),
        sa.Column("allowed_applications_json", sa.Text(), nullable=True),
        sa.Column("allowed_windows_json", sa.Text(), nullable=True),
        sa.Column("observation_goal", sa.Text(), nullable=True),
        sa.Column("screenshot_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_screenshots", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, cols in [
        ("ix_device_observation_sessions_device_id", ["device_id"]),
        ("ix_device_observation_sessions_computer_session_id", ["computer_session_id"]),
        ("ix_device_observation_sessions_task_id", ["task_id"]),
        ("ix_device_observation_sessions_employee_id", ["employee_id"]),
        ("ix_device_observation_sessions_skill_id", ["skill_id"]),
        ("ix_device_observation_sessions_status", ["status"]),
        ("ix_device_observation_sessions_started_at", ["started_at"]),
        ("ix_device_observation_sessions_expires_at", ["expires_at"]),
        ("ix_device_observation_sessions_finished_at", ["finished_at"]),
        ("ix_device_observation_sessions_trace_id", ["trace_id"]),
        ("ix_device_observation_sessions_created_at", ["created_at"]),
        ("ix_device_observation_sessions_updated_at", ["updated_at"]),
    ]:
        op.create_index(name, "device_observation_sessions", cols)

    op.create_table(
        "device_observation_events",
        sa.Column("observation_event_id", sa.String(length=36), primary_key=True),
        sa.Column("observation_id", sa.String(length=36), sa.ForeignKey("device_observation_sessions.observation_id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("application_name", sa.String(length=120), nullable=True),
        sa.Column("bundle_id", sa.String(length=180), nullable=True),
        sa.Column("window_title", sa.Text(), nullable=True),
        sa.Column("screenshot_reference", sa.Text(), nullable=True),
        sa.Column("screenshot_hash", sa.String(length=128), nullable=True),
        sa.Column("screen_state", sa.Text(), nullable=True),
        sa.Column("risk_flags", sa.Text(), nullable=True),
        sa.Column("suggested_next_step", sa.Text(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.UniqueConstraint("observation_id", "sequence_number", name="uq_device_observation_events_sequence"),
    )
    for name, cols in [
        ("ix_device_observation_events_observation_id", ["observation_id"]),
        ("ix_device_observation_events_sequence_number", ["sequence_number"]),
        ("ix_device_observation_events_application_name", ["application_name"]),
        ("ix_device_observation_events_bundle_id", ["bundle_id"]),
        ("ix_device_observation_events_screenshot_hash", ["screenshot_hash"]),
        ("ix_device_observation_events_captured_at", ["captured_at"]),
        ("ix_device_observation_events_trace_id", ["trace_id"]),
    ]:
        op.create_index(name, "device_observation_events", cols)

    op.create_table(
        "device_security_events",
        sa.Column("security_event_id", sa.String(length=36), primary_key=True),
        sa.Column("device_id", sa.String(length=36), sa.ForeignKey("devices.device_id", ondelete="SET NULL"), nullable=True),
        sa.Column("observation_id", sa.String(length=36), sa.ForeignKey("device_observation_sessions.observation_id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_code", sa.String(length=80), nullable=False),
        sa.Column("event_message", sa.Text(), nullable=True),
        sa.Column("risk_level", sa.String(length=40), nullable=False),
        sa.Column("sensitive_data_involved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    for name, cols in [
        ("ix_device_security_events_device_id", ["device_id"]),
        ("ix_device_security_events_observation_id", ["observation_id"]),
        ("ix_device_security_events_event_code", ["event_code"]),
        ("ix_device_security_events_risk_level", ["risk_level"]),
        ("ix_device_security_events_sensitive_data_involved", ["sensitive_data_involved"]),
        ("ix_device_security_events_trace_id", ["trace_id"]),
        ("ix_device_security_events_created_at", ["created_at"]),
    ]:
        op.create_index(name, "device_security_events", cols)


def downgrade():
    for table in [
        "device_security_events",
        "device_observation_events",
        "device_observation_sessions",
        "device_credentials",
        "devices",
        "device_registration_tokens",
    ]:
        op.drop_table(table)
