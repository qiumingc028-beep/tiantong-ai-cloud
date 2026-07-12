"""Regression gate for the Alpha frontend's server-owned contract."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_HEAD = "04804fc62f57305b4bc3f45dbe7bc051bab0cfb4"
PR18_BASE = "eef1ed66638011503c7377d52104258b72ee80d0"
SOURCE_PATH = "frontend/alpha-workflow.js"
PR18_FILES = {
    "frontend/alpha-workflow.html",
    "frontend/alpha-workflow-detail.html",
    "frontend/alpha-workflow.css",
    "frontend/alpha-workflow.js",
}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True
    ).stdout


def frontend_source() -> str:
    """Read the reviewed PR #18 head without relying on an untracked file."""
    return git("show", f"{FRONTEND_HEAD}:{SOURCE_PATH}")


def function_body(source: str, name: str, next_name: str) -> str:
    match = re.search(
        rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{([\s\S]*?)\n\s*function\s+{re.escape(next_name)}\b",
        source,
    )
    assert match, f"无法定位函数：{name}"
    return match.group(1)


def test_deprecated_alpha_frontend_contract_tokens_are_absent():
    source = frontend_source()
    forbidden_identifiers = {
        "root_trace_id",
        "final_report",
        "approval_details",
        "verification_status",
        "audit_status",
        "recovery_checkpoint",
        "STAGES",
        "TERMINAL",
    }
    found = {
        token for token in forbidden_identifiers
        if re.search(rf"(?<![A-Za-z0-9_$]){re.escape(token)}(?![A-Za-z0-9_$])", source)
    }
    if re.search(r"\brun\s*\.\s*skill_version\b", source):
        found.add("run.skill_version")
    assert not found, f"发现废弃前端契约字段：{sorted(found)}"


def test_final_contract_fields_and_root_parent_label_are_present():
    source = frontend_source()
    for token in (
        "root_span_id",
        "skill_version_id",
        "report_content",
        "approval_ids",
        "available_actions",
        "根节点（无父级）",
    ):
        assert token in source
    assert re.search(r"parent_span_id\s*===\s*null\s*\?\s*['\"]根节点（无父级）", source)


def test_report_and_run_actions_are_owned_by_server_contract_fields():
    source = frontend_source()
    actions = function_body(source, "renderActions", "handleAction")
    summary = function_body(source, "renderSummary", "toggleReport")
    assert "detail.report?.report_content" in actions
    assert "run.available_actions" in actions
    assert "normalizeActions" in actions
    assert "report.report_content" in summary
    assert not re.search(r"\brun\s*\.\s*status\b", actions)
    assert not re.search(r"status\s*(?:===|!==|==|!=|\.includes)", actions)


def test_stage_order_comes_from_server_spans_or_events_only():
    source = frontend_source()
    stages = function_body(source, "renderStages", "renderExecution")
    assert "detail.stages?.spans" in stages
    assert "detail.stages?.events" in stages
    assert "rows.map" in stages
    assert not re.search(r"\bconst\s+(?:STAGES|TERMINAL)\b", source)
    assert re.search(r"\bconst\s+STAGE_LABELS\s*=", source)


def test_pr18_scope_is_exactly_four_alpha_frontend_files():
    changed = set(
        git("diff", "--name-only", f"{PR18_BASE}..{FRONTEND_HEAD}").splitlines()
    )
    assert changed == PR18_FILES

