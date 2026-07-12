"""V2 Alpha Sprint 11.1 cross-module release-quality gates.

These tests intentionally exercise the committed implementation as a black/grey box.
They never patch a successful result into every module: the main E2E uses the real
SQLite persistence layer and the real Task/Research/Knowledge/Skills/Agent services.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from backend.alpha_workflow.models import AlphaWorkflowEvent, AlphaWorkflowRun
from backend.alpha_workflow.exceptions import AlphaWorkflowValidationError
from backend.alpha_workflow.service import start_alpha_workflow
from backend.config import get_settings
from backend.knowledge_center.models import KnowledgeAsset
from backend.models import User
from backend.skills_engine.models import Skill, SkillInstallation, SkillInvocation, SkillVersion
from backend.skills_engine.registry import ensure_default_skills
from backend.skills_engine.service import approve_skill


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_CONTRACT = ROOT / "docs/contracts/V2_ALPHA_WORKFLOW_CONTEXT.md"
API_CONTRACT = ROOT / "docs/contracts/V2_ALPHA_WORKFLOW_API.md"

FLAGS = {
    "ALPHA_WORKFLOW_ENABLED": "true",
    "ALPHA_WORKFLOW_DASHBOARD_ENABLED": "true",
    "PUBLIC_RESEARCH_ENABLED": "true",
    "PUBLIC_SEARCH_ENABLED": "true",
    "PUBLIC_SEARCH_PROVIDER": "mock",
    "KNOWLEDGE_CENTER_ENABLED": "true",
    "KNOWLEDGE_SUBMISSION_ENABLED": "true",
    "KNOWLEDGE_LOCAL_SEARCH_ENABLED": "true",
    "SKILLS_ENGINE_ENABLED": "true",
    "SKILL_INSTALLATION_ENABLED": "true",
    "SKILL_INVOCATION_ENABLED": "true",
}


@pytest.fixture()
def alpha_enabled(monkeypatch):
    for key, value in FLAGS.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def completed_run(client, boss_headers, alpha_enabled):
    response = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "研究 Apple 最新 AI 战略"},
    )
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["status"] == "已完成"
    return run


def test_real_cross_module_e2e_persists_every_alpha_stage(client, boss_headers, completed_run):
    """Real integration: HTTP + SQLAlchemy + all module services, no service mocks."""
    run = completed_run
    checks = [
        client.get(f"/api/task-center/tasks/{run['task_id']}", headers=boss_headers),
        client.get(f"/api/v2/research/executions/{run['research_execution_id']}", headers=boss_headers),
        client.get(f"/api/v2/knowledge/{run['knowledge_asset_id']}", headers=boss_headers),
        client.get("/api/v2/skills/invocations", headers=boss_headers),
        client.get(f"/api/v2/alpha-workflows/runs/{run['run_id']}/trace", headers=boss_headers),
        client.get(f"/api/v2/alpha-workflows/runs/{run['run_id']}/audit", headers=boss_headers),
        client.get(f"/api/v2/alpha-workflows/runs/{run['run_id']}/report", headers=boss_headers),
        client.get("/api/v2/alpha-workflows/dashboard", headers=boss_headers),
    ]
    assert all(item.status_code == 200 for item in checks)
    context = run["workflow_context"]
    assert all(context[key] for key in (
        "task_id", "orchestrator_run_id", "research_execution_id",
        "knowledge_asset_id", "knowledge_version_id", "skill_id",
        "skill_version_id", "skill_invocation_id", "agent_execution_id",
        "verification_id", "trace_id", "root_span_id",
    ))


def test_orchestrator_is_only_public_alpha_start_entry_and_bypass_is_rejected(client, boss_headers, alpha_enabled):
    alpha_posts = {
        route.path
        for route in client.app.routes
        if "POST" in getattr(route, "methods", set()) and "alpha" in route.path
    }
    assert "/api/v2/alpha-workflows/demo" in alpha_posts
    assert not any(re.search(r"/(research|knowledge|skills|execution)/start$", path) for path in alpha_posts)
    for bypass in (
        "/api/v2/alpha-workflows/research/start",
        "/api/v2/alpha-workflows/knowledge/start",
        "/api/v2/alpha-workflows/skills/start",
    ):
        assert client.post(bypass, headers=boss_headers, json={}).status_code in {404, 405}


def test_alpha_service_direct_start_without_orchestrator_context_is_rejected(test_db, alpha_enabled):
    db = test_db()
    try:
        user = db.query(User).filter(User.username == "boss").one()
        with pytest.raises(AlphaWorkflowValidationError, match="Orchestrator|入口"):
            start_alpha_workflow(db, user=user, input_text="绕过 Orchestrator 直接启动")
    finally:
        db.close()


def test_duplicate_start_is_idempotent_or_explicitly_rejected(client, boss_headers, alpha_enabled):
    payload = {"input_text": "研究 Apple 最新 AI 战略", "trace_id": "sprint11-idempotency-key"}
    first = client.post("/api/v2/alpha-workflows/demo", headers=boss_headers, json=payload)
    second = client.post("/api/v2/alpha-workflows/demo", headers=boss_headers, json=payload)
    assert first.status_code == 200
    assert second.status_code in {200, 400, 409}
    if second.status_code == 200:
        assert second.json()["run"]["run_id"] == first.json()["run"]["run_id"]


def test_workflow_context_contract_ids_trace_and_sensitive_data(completed_run):
    context = completed_run["workflow_context"]
    required = {
        "workflow_id", "tenant_id", "user_id", "task_id", "orchestrator_run_id",
        "research_execution_id", "research_report_id", "knowledge_asset_id",
        "knowledge_version_id", "skill_id", "skill_version_id", "skill_invocation_id",
        "agent_execution_id", "verification_id", "trace_id", "root_span_id",
        "approval_ids", "risk_score", "quality_score", "current_stage", "status",
        "created_at", "updated_at",
    }
    assert required <= context.keys()
    assert context["trace_id"] == completed_run["trace_id"]
    assert context["workflow_id"] == completed_run["workflow_id"]
    assert context["task_id"] == completed_run["task_id"]
    serialized = json.dumps(context, ensure_ascii=False).lower()
    assert not re.search(r'"(?:secret|token|cookie|password|密码)"\s*:', serialized)
    assert context["current_stage"] == "dashboard"
    assert context["status"] == "已完成"


def test_trace_has_one_root_and_all_children_attach_to_it(client, boss_headers, completed_run):
    trace = client.get(
        f"/api/v2/alpha-workflows/runs/{completed_run['run_id']}/trace",
        headers=boss_headers,
    ).json()
    roots = [event for event in trace["events"] if event["span_kind"] == "root"]
    assert len(roots) == 1
    assert roots[0]["span_id"] == trace["root_span_id"]
    assert roots[0]["parent_span_id"] is None
    assert all(span["parent_span_id"] == trace["root_span_id"] for span in trace["spans"])
    assert all(event["trace_id"] == trace["trace_id"] for event in trace["events"])


def test_module_spans_are_native_and_not_synthesized_by_one_terminal_loop(client, boss_headers, completed_run):
    trace = client.get(
        f"/api/v2/alpha-workflows/runs/{completed_run['run_id']}/trace",
        headers=boss_headers,
    ).json()
    module_stages = {"research", "knowledge", "skills", "verification", "audit", "feedback", "dashboard"}
    event_spans = {(event["stage"], event["span_id"]) for event in trace["events"]}
    context_spans = {(span["stage"], span["span_id"]) for span in trace["spans"]}
    observed = {stage for stage, _ in event_spans | context_spans}
    assert module_stages <= observed
    for stage in module_stages:
        native_ids = {span_id for span_stage, span_id in event_spans if span_stage == stage}
        context_ids = {span_id for span_stage, span_id in context_spans if span_stage == stage}
        assert native_ids & context_ids, f"{stage} Span 未由模块事件产生，而是在终态统一合成"


def test_audit_timeline_is_ordered_and_append_only(client, boss_headers, completed_run, test_db):
    response = client.get(
        f"/api/v2/alpha-workflows/runs/{completed_run['run_id']}/audit",
        headers=boss_headers,
    )
    timeline = response.json()["timeline"]
    timestamps = [item["created_at"] for item in timeline]
    assert timestamps == sorted(timestamps)
    original = timeline[0]["message"]
    db = test_db()
    try:
        event = db.get(AlphaWorkflowEvent, timeline[0]["event_id"])
        event.message = "覆盖后的审计内容"
        with pytest.raises((ValueError, IntegrityError), match="append-only|不可"):
            db.commit()
        db.rollback()
    finally:
        db.close()
    refreshed = client.get(
        f"/api/v2/alpha-workflows/runs/{completed_run['run_id']}/audit",
        headers=boss_headers,
    ).json()["timeline"]
    assert refreshed[0]["message"] == original, "审计事件当前可被原地 UPDATE，未实现不可覆盖约束"


def test_audit_events_cannot_be_cascade_deleted_with_run(completed_run, test_db):
    db = test_db()
    try:
        event_ids = [row.event_id for row in db.query(AlphaWorkflowEvent).filter(AlphaWorkflowEvent.run_id == completed_run["run_id"]).all()]
        assert event_ids
        run = db.get(AlphaWorkflowRun, completed_run["run_id"])
        db.delete(run)
        try:
            db.commit()
        except (ValueError, IntegrityError):
            db.rollback()
        assert db.query(AlphaWorkflowEvent).filter(AlphaWorkflowEvent.event_id.in_(event_ids)).count() == len(event_ids)
    finally:
        db.close()


def test_knowledge_is_single_source_and_skill_version_is_traceable(completed_run, test_db):
    db = test_db()
    try:
        assert db.query(KnowledgeAsset).count() == 1
        invocation = db.get(SkillInvocation, completed_run["skill_invocation_id"])
        assert invocation is not None
        assert str(invocation.skill_version_id) == completed_run["skill_version_id"]
        assert invocation.trace_id == completed_run["trace_id"]
        assert completed_run["knowledge_asset_id"] in json.dumps(completed_run["workflow_context"], ensure_ascii=False)
    finally:
        db.close()


def test_installer_reviewer_and_approver_are_separate_roles(completed_run, test_db):
    db = test_db()
    try:
        installation = db.query(SkillInstallation).filter(SkillInstallation.id == db.get(SkillInvocation, completed_run["skill_invocation_id"]).installation_id).one()
        version = db.get(SkillVersion, installation.skill_version_id)
        actors = {installation.installed_by, version.reviewed_by, version.approved_by}
        assert None not in actors
        assert len(actors) == 3, "安装人、审核人、批准人必须职责分离"
        assert installation.approved_by != installation.installed_by
        assert installation.enabled_at is None, "安装流程不得代替独立启用动作"
    finally:
        db.close()


def test_high_risk_skill_creator_cannot_self_approve(test_db, alpha_enabled):
    db = test_db()
    try:
        owner = db.query(User).filter(User.username == "owner").one()
        ensure_default_skills(db, created_by=owner.id)
        skill = db.query(Skill).first()
        skill.risk_level = "高风险"
        skill.created_by = owner.id
        db.commit()
        with pytest.raises(HTTPException) as exc:
            approve_skill(db, skill, owner)
        assert exc.value.status_code == 403
    finally:
        db.close()


@pytest.mark.parametrize(
    ("target", "message"),
    [
        ("backend.alpha_workflow.service.execute_research_workflow", "Research 失败"),
        ("backend.alpha_workflow.service.submit_research_report", "Knowledge 提交失败"),
        ("backend.alpha_workflow.service.invoke_skill", "Skill 调用失败"),
        ("backend.alpha_workflow.service._score_quality", "Verification 失败"),
        ("backend.alpha_workflow.service.write_audit_log", "Audit 写入失败"),
    ],
)
def test_stage_failures_are_recorded_and_recoverable(client, boss_headers, alpha_enabled, monkeypatch, target, message):
    def fail(*args, **kwargs):
        raise RuntimeError(message)

    monkeypatch.setattr(target, fail)
    response = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "研究 Apple 最新 AI 战略"},
    )
    assert response.status_code == 200
    run = response.json()["run"]
    assert run["status"] == "已失败"
    assert run["recovery_status"] == "待恢复"
    assert message in run["failure_reason"]


def test_recovery_is_idempotent_and_does_not_duplicate_formal_results(client, boss_headers, completed_run, test_db):
    db = test_db()
    try:
        row = db.get(AlphaWorkflowRun, completed_run["run_id"])
        row.status = "已失败"
        row.recovery_status = "待恢复"
        db.commit()
    finally:
        db.close()
    first = client.post(
        f"/api/v2/alpha-workflows/runs/{completed_run['run_id']}/recover",
        headers=boss_headers,
        json={"reason": "安全检查点恢复"},
    )
    db = test_db()
    try:
        after_first = (db.query(KnowledgeAsset).count(), db.query(SkillInvocation).count(), db.query(AlphaWorkflowEvent).count())
    finally:
        db.close()
    second = client.post(
        f"/api/v2/alpha-workflows/runs/{completed_run['run_id']}/recover",
        headers=boss_headers,
        json={"reason": "重复恢复"},
    )
    assert first.status_code == 200
    assert second.status_code in {400, 409}
    db = test_db()
    try:
        after = (db.query(KnowledgeAsset).count(), db.query(SkillInvocation).count(), db.query(AlphaWorkflowEvent).count())
    finally:
        db.close()
    assert after == after_first


@pytest.mark.parametrize("model", [KnowledgeAsset, SkillInvocation, AlphaWorkflowEvent])
def test_repeated_recovery_does_not_duplicate_each_formal_record(client, boss_headers, completed_run, test_db, model):
    db = test_db()
    try:
        row = db.get(AlphaWorkflowRun, completed_run["run_id"])
        row.status = "已失败"
        row.recovery_status = "待恢复"
        db.commit()
    finally:
        db.close()
    client.post(
        f"/api/v2/alpha-workflows/runs/{completed_run['run_id']}/recover",
        headers=boss_headers,
        json={"reason": "首次安全恢复"},
    )
    db = test_db()
    try:
        after_first = db.query(model).count()
    finally:
        db.close()
    client.post(
        f"/api/v2/alpha-workflows/runs/{completed_run['run_id']}/recover",
        headers=boss_headers,
        json={"reason": "重复请求恢复"},
    )
    db = test_db()
    try:
        assert db.query(model).count() == after_first
    finally:
        db.close()


def test_recovery_creates_new_trace_without_duplicate_business_results(client, boss_headers, completed_run, test_db):
    db = test_db()
    try:
        row = db.get(AlphaWorkflowRun, completed_run["run_id"])
        row.status = "已失败"
        row.recovery_status = "待恢复"
        db.commit()
    finally:
        db.close()
    recovered = client.post(
        f"/api/v2/alpha-workflows/runs/{completed_run['run_id']}/recover",
        headers=boss_headers,
        json={"reason": "从检查点恢复"},
    ).json()["run"]
    assert recovered["workflow_id"] == completed_run["workflow_id"]
    assert recovered["task_id"] == completed_run["task_id"]
    assert recovered["trace_id"] != completed_run["trace_id"]
    assert recovered["root_span_id"] != completed_run["root_span_id"]
    assert recovered["recovered_from_run_id"] == completed_run["run_id"]
    assert any(span["stage"] == "recovery" for span in recovered["workflow_context"]["step_trace"])


def test_feature_flag_defaults_off_and_v1_remains_available(client, boss_headers, monkeypatch):
    for key in FLAGS:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    blocked = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": "研究 Apple 最新 AI 战略"},
    )
    assert blocked.status_code == 403
    assert client.post("/api/login", json={"username": "boss", "password": "password"}).status_code == 200
    assert client.get("/api/task-center/tasks", headers=boss_headers).status_code == 200
    assert client.get("/api/owner/dashboard", headers=boss_headers).status_code == 200
    assert client.get("/api/health").status_code == 200


def test_api_contract_paths_fields_statuses_and_errors(client, boss_headers, completed_run):
    contract = API_CONTRACT.read_text(encoding="utf-8")
    documented = set(re.findall(r"(?:GET|POST) (`?/api/v2/alpha-workflows[^`\s：]*`?)", contract))
    documented = {item.strip("`") for item in documented}
    actual = {
        route.path
        for route in client.app.routes
        if route.path.startswith("/api/v2/alpha-workflows")
    }
    normalize = lambda value: re.sub(r"\{[^}]+\}", "{id}", value)
    assert {normalize(path) for path in documented} <= {normalize(path) for path in actual}
    context_contract = CONTEXT_CONTRACT.read_text(encoding="utf-8")
    field_section = context_contract.split("## 唯一上下文结构", 1)[1].split("## 约束", 1)[0]
    context_fields = set(re.findall(r"^- `([a-z_]+)`$", field_section, re.MULTILINE))
    assert context_fields <= completed_run["workflow_context"].keys()
    assert completed_run["status"] in set(re.findall(r'^   - `([^`]+)`$', context_contract, re.MULTILINE))
    missing = client.get("/api/v2/alpha-workflows/runs/not-found", headers=boss_headers)
    assert missing.status_code == 404


def test_api_contract_error_codes_are_exact(client, boss_headers, viewer_headers, alpha_enabled):
    client.cookies.clear()
    invalid = client.post(
        "/api/v2/alpha-workflows/demo",
        headers=boss_headers,
        json={"input_text": ""},
    )
    missing = client.get("/api/v2/alpha-workflows/runs/does-not-exist", headers=boss_headers)
    client.cookies.clear()
    forbidden = client.get("/api/v2/alpha-workflows/runs", headers=viewer_headers)
    assert invalid.status_code == 400
    assert missing.status_code == 404
    assert forbidden.status_code == 403


def test_migration_graph_is_single_head_and_core_tables_are_not_duplicated():
    versions = ROOT / "alembic/versions"
    revisions = {}
    referenced = set()
    table_creators: dict[str, list[str]] = {}
    for path in versions.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        revision = re.search(r'^revision\s*=\s*["\']([^"\']+)', text, re.MULTILINE)
        down = re.search(r'^down_revision\s*=\s*["\']([^"\']+)', text, re.MULTILINE)
        if revision:
            revisions[revision.group(1)] = path.name
        if down:
            referenced.add(down.group(1))
        for table in re.findall(r'op\.create_table\(\s*["\']([^"\']+)', text):
            table_creators.setdefault(table, []).append(path.name)
    heads = set(revisions) - referenced
    assert len(heads) == 1, f"Alembic 必须单 Head，实际为 {sorted(heads)}"
    core = {name: files for name, files in table_creators.items() if any(key in name for key in ("knowledge", "skill", "trace"))}
    duplicates = {name: files for name, files in core.items() if len(files) > 1}
    assert not duplicates, f"核心表被重复创建：{duplicates}"
    head_file = revisions[heads.pop()]
    expected_head = next((path.name for path in versions.glob("0040*.py")), "0039_v2_alpha_workflow_unified_contract.py")
    assert head_file == expected_head


def test_migrations_0039_and_0040_form_one_constrained_head():
    versions = ROOT / "alembic/versions"
    migration_0039 = versions / "0039_v2_alpha_workflow_unified_contract.py"
    candidates_0040 = list(versions.glob("0040*.py"))
    assert migration_0039.exists()
    assert len(candidates_0040) == 1, "必须存在且只能存在一个 0040 Migration"
    migration_corpus = "\n".join(path.read_text(encoding="utf-8") for path in versions.glob("*.py"))
    text_0040 = candidates_0040[0].read_text(encoding="utf-8")
    assert re.search(r'^down_revision\s*=\s*["\']0039_v2_alpha_workflow_unified_contract["\']', text_0040, re.MULTILINE)
    required_constraints = ("trace_id", "root_span_id", "parent_span_id", "knowledge_asset_id", "skill_invocation_id")
    assert all(field in migration_corpus for field in required_constraints)


def test_alpha_does_not_expand_browser_computer_or_shell_permissions():
    sources = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "backend/alpha_workflow").glob("*.py"))
    forbidden = ("subprocess", "os.system", "shell=True", "computer_executor", "device_control", "browser.write")
    assert not any(token in sources for token in forbidden)
