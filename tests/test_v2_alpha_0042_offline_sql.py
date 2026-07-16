"""Regression coverage for PostgreSQL offline SQL generation through 0042."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
START_REVISION = "0027_v1_schema_alignment"
FINAL_REVISION = "0042_v2_alpha_workflow_unique_constraints"
REQUIRED_UNIQUES = {
    "uq_alpha_workflow_runs_root_span_id",
    "uq_alpha_workflow_runs_workflow_id",
    "uq_alpha_workflow_runs_orchestrator_run_id",
    "uq_alpha_workflow_runs_research_report_id",
    "uq_alpha_workflow_runs_skill_invocation_id",
}


def test_0027_to_0042_offline_sql_is_complete_and_guarded():
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql://offline:offline@127.0.0.1/offline"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "alembic.ini",
            "upgrade",
            f"{START_REVISION}:{FINAL_REVISION}",
            "--sql",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    combined = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, combined
    assert "NoInspectionAvailable" not in combined
    assert "MockConnection" not in combined
    assert "HAVING COUNT(*) > 1" in result.stdout
    assert "pg_constraint" in result.stdout
    assert "pg_index" in result.stdout
    assert "uq_alpha_workflow_runs_knowledge_asset_id" in result.stdout
    assert "ix_alpha_workflow_runs_knowledge_asset_id" in result.stdout
    for constraint_name in REQUIRED_UNIQUES:
        assert constraint_name in result.stdout


def test_0042_offline_sql_keeps_revision_and_constraint_contract():
    migration = (ROOT / "alembic/versions/0042_v2_alpha_workflow_unique_constraints.py").read_text()
    assert f'revision = "{FINAL_REVISION}"' in migration
    assert 'down_revision = "0041_v2_alpha_migration_history_repair"' in migration
    assert "context.is_offline_mode()" in migration
    assert "_offline_upgrade()" in migration
    assert "_offline_downgrade()" in migration
    assert "_duplicates_for(column_name)" in migration
