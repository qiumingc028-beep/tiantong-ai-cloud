"""v2 research topic index alignment

Revision ID: 0031_v2_research_topic_index
Revises: 0030_v2_knowledge_asset_center
Create Date: 2026-07-12
"""

from alembic import op


revision = "0031_v2_research_topic_index"
down_revision = "0030_v2_knowledge_asset_center"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_research_executions_research_topic", "research_executions", ["research_topic"])


def downgrade():
    op.drop_index("ix_research_executions_research_topic", table_name="research_executions")
