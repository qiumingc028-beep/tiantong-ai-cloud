import json
import pytest

from backend.security.tian_brain.audit_analyzer import analyze_audit_records
from backend.security.tian_brain.policy_optimizer import build_policy_update, self_learning_loop
from backend.security.tian_brain.risk_predictor import predict_risk
from backend.security.tian_shen import APPROVAL_GREEN, APPROVAL_RED, APPROVAL_YELLOW, evaluate_command
from backend.security.tian_shen.audit import read_audit_records


def test_risk_history_excludes_foreign_scope_before_applying_window(monkeypatch, tmp_path):
    from backend.security.tian_shen.audit import record_audit

    monkeypatch.setenv("TIAN_SHEN_AUDIT_LOG", str(tmp_path / "scoped-audit.jsonl"))
    scope = {"tenant_id": 1, "company_id": 2, "requester_id": 3,
             "store_scope_key": "store:4", "ownership_scope_key": "owner:3"}
    event = {"source": "employee_organization", "action": "review_permission_change",
             "audit_scope": scope}
    for _ in range(2):
        record_audit(event, {"allowed": False})
    for _ in range(205):
        record_audit({**event, "audit_scope": {**scope, "tenant_id": 9}}, {"allowed": False})

    assert predict_risk(event)["historical_blocks"] == 2
    assert len(read_audit_records()) == 207


@pytest.mark.parametrize("field,value", [
    ("tenant_id", 9), ("company_id", 9), ("requester_id", 9),
    ("store_scope_key", "store:9"), ("ownership_scope_key", "owner:9"),
    ("tenant_id", True), ("company_id", "2"), ("store_scope_key", None),
])
def test_risk_history_requires_exact_complete_scope(monkeypatch, tmp_path, field, value):
    from backend.security.tian_shen.audit import record_audit

    monkeypatch.setenv("TIAN_SHEN_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    scope = {"tenant_id": 1, "company_id": 2, "requester_id": 3,
             "store_scope_key": "store:4", "ownership_scope_key": "owner:3"}
    event = {"source": "employee_organization", "action": "review_permission_change", "audit_scope": scope}
    record_audit({**event, "audit_scope": {**scope, field: value}}, {"allowed": False})
    record_audit({**event, "audit_scope": None}, {"allowed": False})
    assert predict_risk(event)["historical_blocks"] == 0
    assert predict_risk(event, audit_records=read_audit_records())["historical_blocks"] == 0


def test_risk_history_window_can_decrease_only_with_matching_decisions(monkeypatch, tmp_path):
    from backend.security.tian_shen.audit import record_audit

    monkeypatch.setenv("TIAN_SHEN_AUDIT_LOG", str(tmp_path / "audit.jsonl"))
    event = {"source": "employee_organization", "action": "review_permission_change", "audit_scope": {
        "tenant_id": 1, "company_id": 2, "requester_id": 3,
        "store_scope_key": "store:4", "ownership_scope_key": "owner:3",
    }}
    for index in range(200):
        record_audit(event, {"allowed": index >= 92})
    assert predict_risk(event)["historical_blocks"] == 92
    for unrelated in ({**event, "source": "other"}, {**event, "action": "other"}):
        record_audit(unrelated, {"allowed": False})
    assert predict_risk(event)["historical_blocks"] == 92
    for _ in range(2):
        record_audit(event, {"allowed": True})
    assert predict_risk(event)["historical_blocks"] == 90
    assert predict_risk(event, audit_records=read_audit_records())["historical_blocks"] == 90
    for _ in range(205):
        record_audit(event, {"allowed": False})
    assert predict_risk(event)["historical_blocks"] == 200
    assert predict_risk({**event, "audit_scope": None})["historical_blocks"] == 0
    assert len(read_audit_records()) == 409


def test_audit_analyzer_detects_repeated_yellow_candidates():
    records = [
        {"command": "review_code", "level": "YELLOW", "source": "codex", "allowed": True},
        {"command": "review_code", "level": "YELLOW", "source": "codex", "allowed": True},
        {"command": "review_code", "level": "YELLOW", "source": "codex", "allowed": True},
        {"command": "git push origin main", "level": "RED", "source": "cli", "allowed": False},
        {"command": "git push origin main", "level": "RED", "source": "cli", "allowed": False},
    ]

    analysis = analyze_audit_records(records)

    assert analysis["total"] == 5
    assert analysis["by_level"]["YELLOW"] == 3
    assert analysis["yellow_to_green_candidates"][0]["command"] == "review_code"
    assert analysis["red_reinforcement_candidates"][0]["command"] == "git push origin main"


def test_risk_predictor_predicts_red_before_execution():
    policy = {
        "red": {"keywords": ["git push"]},
        "yellow": {"keywords": ["codex"], "sources": ["codex"]},
    }

    prediction = predict_risk(
        {"source": "cli", "target": "tiandun_ops", "command": "git push origin main"},
        policy=policy,
        audit_records=[],
    )

    assert prediction["predicted_level"] == APPROVAL_RED
    assert prediction["risk_score"] >= 80
    assert "git push" in prediction["matched_red_keywords"]


def test_policy_optimizer_builds_green_allowlist_update():
    records = [
        {"command": "review_code", "level": "YELLOW", "source": "codex", "allowed": True},
        {"command": "review_code", "level": "YELLOW", "source": "codex", "allowed": True},
        {"command": "review_code", "level": "YELLOW", "source": "codex", "allowed": True},
    ]
    update = build_policy_update({"green": {}, "yellow": {}, "red": {}}, records)

    assert update["proposed_changes"]["green_allowlist_additions"] == ["review_code"]
    assert update["updated_policy"]["green"]["allowlist_commands"] == ["review_code"]
    assert update["updated_policy"]["tian_brain"]["mode"] == "self_learning_policy_optimizer"


def test_self_learning_loop_can_write_temp_policy(tmp_path):
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps({"green": {}, "yellow": {}, "red": {}}, ensure_ascii=False), encoding="utf-8")

    result = self_learning_loop(policy_path, dry_run=False)
    updated = json.loads(policy_path.read_text(encoding="utf-8"))

    assert result["applied"] is True
    assert updated["tian_brain"]["mode"] == "self_learning_policy_optimizer"


def test_tian_shen_tian_brain_loop_records_prediction(monkeypatch, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("TIAN_SHEN_AUDIT_LOG", str(audit_path))

    decision = evaluate_command({"source": "cli", "target": "tiandun_ops", "command": "git push origin main"})
    records = read_audit_records()

    assert decision["decision"] == APPROVAL_RED
    assert decision["tian_brain"]["predicted_level"] == APPROVAL_RED
    assert records[0]["tian_brain"]["predicted_level"] == APPROVAL_RED


def test_tian_brain_policy_allowlist_turns_repeated_yellow_green(monkeypatch):
    policy = {
        "green": {"allowlist_commands": ["review_code"]},
        "yellow": {"keywords": ["codex"], "sources": ["codex"]},
        "red": {"keywords": []},
    }
    monkeypatch.setattr("backend.security.tian_shen.approval_engine.load_policy", lambda path=None: policy)

    decision = evaluate_command({"source": "codex", "action": "review_code"})
    update = build_policy_update(policy, [])

    assert decision["decision"] == APPROVAL_GREEN
    assert "allowlist" in decision["reasons"][0]
    assert update["updated_policy"]["green"]["allowlist_commands"] == ["review_code"]
