"""v2 public research workflow

Revision ID: 0029_v2_public_research_workflow
Revises: 0028_v2_agent_runtime_foundation
Create Date: 2026-07-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0029_v2_public_research_workflow"
down_revision = "0028_v2_agent_runtime_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "research_executions",
        sa.Column("execution_id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("ai_employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("capability_id", sa.String(length=120), sa.ForeignKey("agent_capabilities.capability_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="planned"),
        sa.Column("risk_level", sa.String(length=40), nullable=False, server_default="low"),
        sa.Column("approval_status", sa.String(length=40), nullable=False, server_default="not_required"),
        sa.Column("executor_type", sa.String(length=40), nullable=False, server_default="research"),
        sa.Column("research_topic", sa.String(length=300), nullable=False),
        sa.Column("research_goal", sa.Text(), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=True),
        sa.Column("query_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conclusion_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uncertainty_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("report_title", sa.String(length=200), nullable=True),
        sa.Column("report_content", sa.Text(), nullable=True),
        sa.Column("report_hash", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("trace_id", name="uq_research_executions_trace_id"),
    )
    op.create_index("ix_research_executions_task_id", "research_executions", ["task_id"])
    op.create_index("ix_research_executions_employee_id", "research_executions", ["employee_id"])
    op.create_index("ix_research_executions_capability_id", "research_executions", ["capability_id"])
    op.create_index("ix_research_executions_status", "research_executions", ["status"])
    op.create_index("ix_research_executions_risk_level", "research_executions", ["risk_level"])
    op.create_index("ix_research_executions_approval_status", "research_executions", ["approval_status"])
    op.create_index("ix_research_executions_executor_type", "research_executions", ["executor_type"])
    op.create_index("ix_research_executions_trace_id", "research_executions", ["trace_id"])
    op.create_index("ix_research_executions_created_by_id", "research_executions", ["created_by_id"])

    op.create_table(
        "research_queries",
        sa.Column("query_id", sa.String(length=36), primary_key=True),
        sa.Column("execution_id", sa.String(length=36), sa.ForeignKey("research_executions.execution_id", ondelete="CASCADE"), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=40), nullable=False, server_default="zh-CN"),
        sa.Column("time_range", sa.String(length=80), nullable=True),
        sa.Column("provider_name", sa.String(length=80), nullable=False),
        sa.Column("allow_domains_json", sa.Text(), nullable=True),
        sa.Column("blocked_domains_json", sa.Text(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="collected"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_research_queries_execution_id", "research_queries", ["execution_id"])
    op.create_index("ix_research_queries_status", "research_queries", ["status"])

    op.create_table(
        "research_sources",
        sa.Column("source_id", sa.String(length=36), primary_key=True),
        sa.Column("execution_id", sa.String(length=36), sa.ForeignKey("research_executions.execution_id", ondelete="CASCADE"), nullable=False),
        sa.Column("query_id", sa.String(length=36), sa.ForeignKey("research_queries.query_id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("redacted_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_domain", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=60), nullable=False),
        sa.Column("confidence_level", sa.String(length=40), nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence_reason", sa.Text(), nullable=True),
        sa.Column("publication_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("content_excerpt", sa.Text(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("duplicate_of_source_id", sa.String(length=36), nullable=True),
        sa.Column("provider_name", sa.String(length=80), nullable=False),
        sa.Column("validation_status", sa.String(length=40), nullable=False, server_default="已交叉验证"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_research_sources_execution_id", "research_sources", ["execution_id"])
    op.create_index("ix_research_sources_query_id", "research_sources", ["query_id"])
    op.create_index("ix_research_sources_normalized_url", "research_sources", ["normalized_url"])
    op.create_index("ix_research_sources_source_domain", "research_sources", ["source_domain"])
    op.create_index("ix_research_sources_source_type", "research_sources", ["source_type"])
    op.create_index("ix_research_sources_confidence_level", "research_sources", ["confidence_level"])
    op.create_index("ix_research_sources_content_hash", "research_sources", ["content_hash"])
    op.create_index("ix_research_sources_validation_status", "research_sources", ["validation_status"])

    op.create_table(
        "research_claims",
        sa.Column("claim_id", sa.String(length=36), primary_key=True),
        sa.Column("execution_id", sa.String(length=36), sa.ForeignKey("research_executions.execution_id", ondelete="CASCADE"), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("claim_status", sa.String(length=40), nullable=False, server_default="candidate"),
        sa.Column("validation_status", sa.String(length=40), nullable=False, server_default="单一来源"),
        sa.Column("confidence_level", sa.String(length=40), nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("support_source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conflict_source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("support_source_ids_json", sa.Text(), nullable=True),
        sa.Column("conflict_source_ids_json", sa.Text(), nullable=True),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_research_claims_execution_id", "research_claims", ["execution_id"])
    op.create_index("ix_research_claims_validation_status", "research_claims", ["validation_status"])
    op.create_index("ix_research_claims_confidence_level", "research_claims", ["confidence_level"])

    op.create_table(
        "research_evidence",
        sa.Column("evidence_id", sa.String(length=36), primary_key=True),
        sa.Column("execution_id", sa.String(length=36), sa.ForeignKey("research_executions.execution_id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_center_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_id", sa.String(length=36), sa.ForeignKey("research_sources.source_id", ondelete="CASCADE"), nullable=False),
        sa.Column("claim_id", sa.String(length=36), sa.ForeignKey("research_claims.claim_id", ondelete="SET NULL"), nullable=True),
        sa.Column("raw_url", sa.Text(), nullable=False),
        sa.Column("redacted_url", sa.Text(), nullable=False),
        sa.Column("page_title", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=60), nullable=False),
        sa.Column("confidence_level", sa.String(length=40), nullable=False),
        sa.Column("citation_summary", sa.Text(), nullable=True),
        sa.Column("evidence_content_hash", sa.String(length=128), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("relation_type", sa.String(length=30), nullable=False, server_default="support"),
        sa.Column("validation_status", sa.String(length=40), nullable=False, server_default="已交叉验证"),
        sa.Column("trace_id", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_research_evidence_execution_id", "research_evidence", ["execution_id"])
    op.create_index("ix_research_evidence_task_id", "research_evidence", ["task_id"])
    op.create_index("ix_research_evidence_source_id", "research_evidence", ["source_id"])
    op.create_index("ix_research_evidence_claim_id", "research_evidence", ["claim_id"])
    op.create_index("ix_research_evidence_source_type", "research_evidence", ["source_type"])
    op.create_index("ix_research_evidence_confidence_level", "research_evidence", ["confidence_level"])
    op.create_index("ix_research_evidence_evidence_content_hash", "research_evidence", ["evidence_content_hash"])
    op.create_index("ix_research_evidence_relation_type", "research_evidence", ["relation_type"])
    op.create_index("ix_research_evidence_validation_status", "research_evidence", ["validation_status"])
    op.create_index("ix_research_evidence_trace_id", "research_evidence", ["trace_id"])


def downgrade():
    op.drop_index("ix_research_evidence_trace_id", table_name="research_evidence")
    op.drop_index("ix_research_evidence_validation_status", table_name="research_evidence")
    op.drop_index("ix_research_evidence_relation_type", table_name="research_evidence")
    op.drop_index("ix_research_evidence_evidence_content_hash", table_name="research_evidence")
    op.drop_index("ix_research_evidence_confidence_level", table_name="research_evidence")
    op.drop_index("ix_research_evidence_source_type", table_name="research_evidence")
    op.drop_index("ix_research_evidence_claim_id", table_name="research_evidence")
    op.drop_index("ix_research_evidence_source_id", table_name="research_evidence")
    op.drop_index("ix_research_evidence_task_id", table_name="research_evidence")
    op.drop_index("ix_research_evidence_execution_id", table_name="research_evidence")
    op.drop_table("research_evidence")

    op.drop_index("ix_research_claims_confidence_level", table_name="research_claims")
    op.drop_index("ix_research_claims_validation_status", table_name="research_claims")
    op.drop_index("ix_research_claims_execution_id", table_name="research_claims")
    op.drop_table("research_claims")

    op.drop_index("ix_research_sources_validation_status", table_name="research_sources")
    op.drop_index("ix_research_sources_content_hash", table_name="research_sources")
    op.drop_index("ix_research_sources_confidence_level", table_name="research_sources")
    op.drop_index("ix_research_sources_source_type", table_name="research_sources")
    op.drop_index("ix_research_sources_source_domain", table_name="research_sources")
    op.drop_index("ix_research_sources_normalized_url", table_name="research_sources")
    op.drop_index("ix_research_sources_query_id", table_name="research_sources")
    op.drop_index("ix_research_sources_execution_id", table_name="research_sources")
    op.drop_table("research_sources")

    op.drop_index("ix_research_queries_status", table_name="research_queries")
    op.drop_index("ix_research_queries_execution_id", table_name="research_queries")
    op.drop_table("research_queries")

    op.drop_index("ix_research_executions_created_by_id", table_name="research_executions")
    op.drop_index("ix_research_executions_trace_id", table_name="research_executions")
    op.drop_index("ix_research_executions_executor_type", table_name="research_executions")
    op.drop_index("ix_research_executions_approval_status", table_name="research_executions")
    op.drop_index("ix_research_executions_risk_level", table_name="research_executions")
    op.drop_index("ix_research_executions_status", table_name="research_executions")
    op.drop_index("ix_research_executions_capability_id", table_name="research_executions")
    op.drop_index("ix_research_executions_employee_id", table_name="research_executions")
    op.drop_index("ix_research_executions_task_id", table_name="research_executions")
    op.drop_table("research_executions")
