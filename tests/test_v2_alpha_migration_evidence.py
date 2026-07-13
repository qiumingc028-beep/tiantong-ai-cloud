"""Strict, read-only release gate for PostgreSQL migration evidence."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "artifacts/alpha-migration-evidence"
FINAL_REVISION = "0042_v2_alpha_workflow_unique_constraints"
FEATURE_REF = "origin/feature/v2-alpha-workflow-engine"
V1_TAG = "v1.0.1"
CODE_FREEZE_COMMIT = "8d9b5f2890545f1f08d05b9b1618f71ff82d6621"
PATH_B_START_COMMIT = "85586868bad3dd5d0fecba5f840383feccdc1c78"
PATH_B_START_REVISION = "0041_v2_alpha_migration_history_repair"
KNOWN_BROKEN_HISTORICAL_BASELINE = "2ca1a2579569324ce3ca82f68332fb7f96be004d"

REQUIRED_FILES = {
    "path_a": EVIDENCE_DIR / "path_a_current.log",
    "path_b": EVIDENCE_DIR / "path_b_current.log",
    "alembic_evidence": EVIDENCE_DIR / "alembic-evidence.txt",
    "checksums": EVIDENCE_DIR / "checksums.sha256",
    "evidence_document": ROOT / "docs/V2_ALPHA_MIGRATION_EVIDENCE.md",
    "freeze_policy": ROOT / "docs/V2_MIGRATION_FREEZE_POLICY.md",
    "validation_manifest": EVIDENCE_DIR / "validation-manifest.json",
}
PATH_FIELDS = {
    "evidence_format_version",
    "path_id",
    "database_id",
    "database_engine",
    "postgresql_version",
    "validated_code_commit",
    "start_commit",
    "start_revision",
    "final_revision",
    "alembic_heads_result",
    "alembic_current_result",
    "alembic_check_result",
    "repeat_upgrade_result",
    "downgrade_reupgrade_result",
    "constraint_query_result",
    "secret_scan_result",
}
RESULT_FIELDS = {
    "alembic_heads_result": {"PASS"},
    "alembic_current_result": {"PASS"},
    "alembic_check_result": {"PASS"},
    "repeat_upgrade_result": {"NO_OP"},
    "downgrade_reupgrade_result": {"PASS"},
    "constraint_query_result": {"PASS"},
    "secret_scan_result": {"PASS"},
}
RAW_RESULT_COMMANDS = {
    "alembic_heads_result": "alembic heads",
    "alembic_current_result": "alembic current",
    "alembic_check_result": "alembic check",
    "constraint_query_result": "constraint query",
}
DISCLOSURE_FIELDS = {
    "0037_baseline_commit_or_hash",
    "0037_modified_hash",
    "0037_change",
    "0037_reason",
    "0037_production_deployed",
    "0037_exception_decision",
    "0037_approved_role",
    "0037_post_sprint_freeze_rule",
}
MIGRATION_0037 = "alembic/versions/0037_v2_execution_observability_security_ops.py"
EVIDENCE_ONLY_PATHS = (
    "artifacts/alpha-migration-evidence/",
    "docs/V2_ALPHA_MIGRATION_EVIDENCE.md",
    "docs/V2_MIGRATION_FREEZE_POLICY.md",
)
MANIFEST_FIELDS = {
    "evidence_format_version",
    "validated_code_commit",
    "final_revision",
    "checksum_algorithm",
    "required_files",
    "path_a",
    "path_b",
}


@dataclass(frozen=True)
class PathEvidence:
    fields: dict[str, str]
    raw_output: str


def read(path: Path) -> str:
    assert path.is_file(), f"缺少正式证据文件：{path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def git(*args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=check, text=True, capture_output=True
    ).stdout.strip()


def parse_key_values(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in content.splitlines():
        match = re.fullmatch(r"\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*", line)
        if match:
            key, value = match.groups()
            assert key not in fields, f"重复结构字段：{key}"
            assert value, f"结构字段为空：{key}"
            fields[key] = value
    return fields


def parse_path_evidence(path: Path, expected_path_id: str) -> PathEvidence:
    content = read(path)
    parts = re.split(r"(?im)^---\s*raw[_ ]output\s*---\s*$", content, maxsplit=1)
    assert len(parts) == 2, "日志必须包含独立的 --- RAW OUTPUT --- 区域"
    fields = parse_key_values(parts[0])
    missing = sorted(PATH_FIELDS - fields.keys())
    assert not missing, f"缺少结构字段：{missing}"
    assert fields["path_id"] == expected_path_id
    assert fields["database_engine"].casefold() == "postgresql"
    assert fields["postgresql_version"].strip()
    assert fields["final_revision"] == FINAL_REVISION
    for field, allowed in RESULT_FIELDS.items():
        assert fields[field] in allowed, f"{field} 必须为 {sorted(allowed)}"
    raw = parts[1]
    for field, command in RAW_RESULT_COMMANDS.items():
        assert re.search(rf"(?im)^\s*\$?\s*{re.escape(command)}\b", raw), f"原始输出缺少 {command}"
        assert re.search(rf"(?im)^\s*{re.escape(field)}\s*=\s*{re.escape(fields[field])}\s*$", raw), f"原始输出与 {field} 不一致"
    assert FINAL_REVISION in raw
    return PathEvidence(fields, raw)


def test_required_migration_evidence_files_exist():
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_FILES.values() if not path.is_file()]
    assert not missing, f"缺少Migration正式证据文件：{missing}"


@pytest.mark.parametrize(("key", "path_id"), [("path_a", "A"), ("path_b", "B")])
def test_each_postgresql_path_has_complete_structured_evidence(key, path_id):
    parse_path_evidence(REQUIRED_FILES[key], path_id)


def test_path_a_and_b_are_independent_and_validate_same_code():
    path_a = parse_path_evidence(REQUIRED_FILES["path_a"], "A").fields
    path_b = parse_path_evidence(REQUIRED_FILES["path_b"], "B").fields
    assert path_a["database_id"] != path_b["database_id"], "Path A/B必须使用不同数据库标识"
    assert (path_a["start_commit"], path_a["start_revision"]) != (
        path_b["start_commit"], path_b["start_revision"]
    ), "Path A/B起点不得完全相同"
    assert path_a["validated_code_commit"] == path_b["validated_code_commit"]


def test_path_a_and_b_start_points_are_real_git_baselines():
    path_a = parse_path_evidence(REQUIRED_FILES["path_a"], "A").fields
    path_b = parse_path_evidence(REQUIRED_FILES["path_b"], "B").fields
    v1_commit = git("rev-parse", f"{V1_TAG}^{{commit}}")
    assert path_a["start_commit"] == v1_commit, "Path A起点必须是v1.0.1 Tag指向的Commit"
    assert path_a["start_revision"] == "0027_v1_schema_alignment"
    assert path_b["start_commit"] == PATH_B_START_COMMIT, "Path B必须使用冻结可运行基线Commit"
    assert path_b["start_revision"] == PATH_B_START_REVISION, "Path B必须从冻结可运行的0041 Revision开始"
    assert path_b["start_commit"] != KNOWN_BROKEN_HISTORICAL_BASELINE, (
        "Path B不得使用真实旧merge-base；该Commit只能标记为KNOWN_BROKEN_HISTORICAL_BASELINE"
    )
    commit_check = subprocess.run(
        ["git", "cat-file", "-e", f"{path_b['start_commit']}^{{commit}}"], cwd=ROOT, capture_output=True
    )
    assert commit_check.returncode == 0


def test_old_merge_base_is_only_documented_as_known_broken_historical_baseline():
    corpus = "\n".join(read(path) for path in REQUIRED_FILES.values() if path.suffix != ".sha256")
    for line in corpus.splitlines():
        if KNOWN_BROKEN_HISTORICAL_BASELINE in line:
            assert "KNOWN_BROKEN_HISTORICAL_BASELINE" in line, (
                "真实旧merge-base只能以KNOWN_BROKEN_HISTORICAL_BASELINE分类出现"
            )


def test_validation_manifest_has_hardened_commit_and_path_model():
    manifest = json.loads(read(REQUIRED_FILES["validation_manifest"]))
    missing = sorted(MANIFEST_FIELDS - manifest.keys())
    assert not missing, f"Manifest缺少字段：{missing}"
    assert manifest["evidence_format_version"]
    assert manifest["final_revision"] == FINAL_REVISION
    assert manifest["checksum_algorithm"].casefold() == "sha256"
    assert isinstance(manifest["required_files"], list) and manifest["required_files"]
    for path_id, key in (("A", "path_a"), ("B", "path_b")):
        entry = manifest[key]
        assert entry["path_id"] == path_id
        for field in ("database_id", "start_commit", "start_revision", "validated_code_commit"):
            assert entry.get(field), f"Manifest {key}缺少{field}"
    assert manifest["path_a"]["validated_code_commit"] == manifest["validated_code_commit"]
    assert manifest["path_b"]["validated_code_commit"] == manifest["validated_code_commit"]
    assert manifest["validated_code_commit"] == CODE_FREEZE_COMMIT
    assert manifest["path_a"]["start_commit"] == git("rev-parse", f"{V1_TAG}^{{commit}}")
    assert manifest["path_a"]["start_revision"] == "0027_v1_schema_alignment"
    assert manifest["path_b"]["start_commit"] == PATH_B_START_COMMIT
    assert manifest["path_b"]["start_revision"] == PATH_B_START_REVISION


def test_validated_code_commit_and_evidence_only_commit_interval():
    path_a = parse_path_evidence(REQUIRED_FILES["path_a"], "A").fields
    path_b = parse_path_evidence(REQUIRED_FILES["path_b"], "B").fields
    validated = path_a["validated_code_commit"]
    assert validated == path_b["validated_code_commit"]
    assert validated == CODE_FREEZE_COMMIT, "正式证据必须验证Sprint 11.1代码冻结Commit"
    commit_check = subprocess.run(
        ["git", "cat-file", "-e", f"{validated}^{{commit}}"], cwd=ROOT, capture_output=True
    )
    assert commit_check.returncode == 0, "validated_code_commit不是有效Git Commit"
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", validated, FEATURE_REF], cwd=ROOT
    )
    assert ancestor.returncode == 0, "validated_code_commit不是主功能分支证据Head的祖先"
    changed = git("diff", "--name-only", f"{validated}..{FEATURE_REF}").splitlines()
    disallowed = [path for path in changed if not path.startswith(EVIDENCE_ONLY_PATHS)]
    assert not disallowed, f"validated code之后存在非证据变化，必须重测：{disallowed}"


def test_all_evidence_agrees_on_0042_and_has_no_skip_or_sqlite_claims():
    evidence = "\n".join(read(path) for path in REQUIRED_FILES.values() if path.suffix != ".sha256")
    assert "ALEMBIC_SKIP_SQLITE_DRIFT" not in evidence
    for key in ("path_a", "path_b"):
        path_log = read(REQUIRED_FILES[key])
        assert not re.search(r"(?im)^\s*database_engine\s*=\s*sqlite\s*$", path_log)
        assert not re.search(r"(?im)^\s*sqlite(?:_version)?\s*=", path_log)
    assert not re.search(r"(?im)^\s*(?:final_revision|final_head|current_final)\s*[:=]\s*004[01]\b", evidence)
    assert not re.search(r"(?im)^\s*(?:最终\s*(?:revision|head)|最终版本)\s*[:：]\s*004[01]\b", evidence)
    for key in ("path_a", "path_b", "alembic_evidence"):
        assert FINAL_REVISION in read(REQUIRED_FILES[key]), f"{key} 最终Head不是0042"


def test_checksums_are_strict_relative_paths_and_recompute_all_required_files():
    checksum_file = REQUIRED_FILES["checksums"]
    lines = [line.strip() for line in read(checksum_file).splitlines() if line.strip() and not line.startswith("#")]
    assert lines
    covered: set[Path] = set()
    root = ROOT.resolve()
    for line in lines:
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+[* ]?(.+)", line)
        assert match, f"非法SHA256行：{line}"
        expected, raw_path = match.groups()
        candidate = Path(raw_path)
        assert not candidate.is_absolute(), f"Checksum路径必须相对仓库根目录：{raw_path}"
        assert ".." not in candidate.parts, f"Checksum路径禁止..逃逸：{raw_path}"
        path = (ROOT / candidate).resolve()
        assert path == root or root in path.parents, f"Checksum路径逃逸仓库：{raw_path}"
        assert path.is_file(), f"Checksum目标不存在：{raw_path}"
        assert path != checksum_file.resolve(), "checksums.sha256不得校验自身"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected.lower(), f"Checksum不匹配：{raw_path}"
        covered.add(path)
    required = {path.resolve() for key, path in REQUIRED_FILES.items() if key != "checksums"}
    assert covered == required, "Checksums必须且只能覆盖全部Required Files（自身除外）"


def test_v1_0001_through_0027_are_byte_identical_to_v1_0_1():
    paths = [line for line in git("ls-tree", "-r", "--name-only", V1_TAG, "--", "alembic/versions").splitlines() if re.search(r"/(?:00(?:0[1-9]|1[0-9]|2[0-7]))[^/]*\.py$", line)]
    assert paths
    changed = []
    for relative in paths:
        tagged = subprocess.run(["git", "show", f"{V1_TAG}:{relative}"], cwd=ROOT, check=True, capture_output=True).stdout
        if hashlib.sha256(tagged).digest() != hashlib.sha256((ROOT / relative).read_bytes()).digest():
            changed.append(relative)
    assert not changed, f"V1 Migration历史被改写：{changed}"


def test_migration_0005_matches_v1_0_1_independently():
    paths = [line for line in git("ls-tree", "-r", "--name-only", V1_TAG, "--", "alembic/versions").splitlines() if Path(line).name.startswith("0005")]
    assert paths
    for relative in paths:
        tagged = subprocess.run(["git", "show", f"{V1_TAG}:{relative}"], cwd=ROOT, check=True, capture_output=True).stdout
        assert hashlib.sha256(tagged).hexdigest() == hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), relative


def test_0037_change_has_complete_consistent_disclosure():
    documents = {
        "freeze_policy": read(REQUIRED_FILES["freeze_policy"]),
        "evidence_document": read(REQUIRED_FILES["evidence_document"]),
    }
    parsed = {}
    for name, content in documents.items():
        assert MIGRATION_0037 in content, f"{name}缺少0037完整路径"
        fields = parse_key_values(content)
        missing = sorted(DISCLOSURE_FIELDS - fields.keys())
        assert not missing, f"{name}缺少0037披露字段：{missing}"
        assert re.fullmatch(r"[0-9a-fA-F]{7,64}", fields["0037_baseline_commit_or_hash"])
        assert re.fullmatch(r"[0-9a-fA-F]{64}", fields["0037_modified_hash"])
        assert re.search(r"boolean\s+server_default", fields["0037_change"], re.IGNORECASE)
        assert fields["0037_reason"].strip()
        assert fields["0037_production_deployed"].casefold() in {"no", "false", "否", "未部署"}
        assert re.search(r"预发布|pre[- ]release", fields["0037_exception_decision"], re.IGNORECASE)
        assert fields["0037_approved_role"].strip()
        assert re.search(r"sprint\s*11\.1|冻结|freeze", fields["0037_post_sprint_freeze_rule"], re.IGNORECASE)
        parsed[name] = {field: fields[field].strip() for field in DISCLOSURE_FIELDS}
    assert parsed["freeze_policy"] == parsed["evidence_document"], "Freeze Policy与Evidence Document的0037披露矛盾"


def test_evidence_contains_no_secrets_connections_or_production_data():
    findings = []
    assignment = re.compile(r"(?i)(password|passwd|pwd|token|secret|api[_-]?key)\s*[:=]\s*([^\s,;]+)")
    credential_url = re.compile(r"(?i)(?:postgres(?:ql)?|redis|mysql)://[^\s/@:]+:[^\s/@]+@")
    for key, path in REQUIRED_FILES.items():
        content = read(path)
        for match in assignment.finditer(content):
            value = match.group(2).strip("'\"")
            if value.lower() not in {"<redacted>", "redacted", "***", "none", "null"}:
                findings.append(f"{key}:{match.group(1)}")
        if credential_url.search(content):
            findings.append(f"{key}:完整数据库连接串")
        if re.search(r"(?i)(真实生产数据|real production data)\s*[:=]\s*(?!无|none|false)", content):
            findings.append(f"{key}:生产数据")
    assert not findings, f"证据敏感信息扫描失败：{findings}"
