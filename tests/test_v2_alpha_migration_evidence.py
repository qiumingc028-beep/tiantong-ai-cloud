"""Automated release gate for V2 Alpha PostgreSQL migration evidence.

The gate is deliberately strict: missing or contradictory evidence is a test
failure.  It only reads repository files and Git objects; it never connects to
a database or executes Alembic migrations.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "artifacts/alpha-migration-evidence"
FINAL_REVISION = "0041_v2_alpha_migration_history_repair"
V1_TAG = "v1.0.1"

REQUIRED_FILES = {
    "path_a": EVIDENCE_DIR / "path_a_current.log",
    "path_b": EVIDENCE_DIR / "path_b_current.log",
    "alembic_evidence": EVIDENCE_DIR / "alembic-evidence.txt",
    "checksums": EVIDENCE_DIR / "checksums.sha256",
    "evidence_document": ROOT / "docs/V2_ALPHA_MIGRATION_EVIDENCE.md",
    "freeze_policy": ROOT / "docs/V2_MIGRATION_FREEZE_POLICY.md",
}

PATH_REQUIRED_CONCEPTS = {
    "postgres_version": (r"postgres(?:ql)?\s+(?:version|版本)", r"server_version"),
    "start_commit": (r"start(?:ing)?[_ ]commit", r"起始\s*commit"),
    "start_revision": (r"start(?:ing)?[_ ]revision", r"起始\s*revision"),
    "final_commit": (r"final[_ ]commit", r"最终\s*commit"),
    "final_revision": (r"final[_ ]revision", r"最终\s*revision"),
    "current": (r"alembic\s+current",),
    "heads": (r"alembic\s+heads",),
    "check": (r"alembic\s+check", r"no new upgrade operations detected"),
    "repeated_upgrade": (r"repeat(?:ed)?[_ ]upgrade", r"第二次.*upgrade\s+head", r"no[- ]op"),
    "downgrade_reupgrade": (r"downgrade.*re[- ]?upgrade", r"alembic\s+downgrade[\s\S]*alembic\s+upgrade"),
    "schema_constraints": (r"pg_constraint", r"information_schema", r"schema.*constraint", r"约束.*查询"),
}


def read(path: Path) -> str:
    assert path.is_file(), f"缺少正式证据文件：{path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True
    ).stdout


def test_required_migration_evidence_files_exist():
    missing = [str(path.relative_to(ROOT)) for path in REQUIRED_FILES.values() if not path.is_file()]
    assert not missing, f"缺少Migration正式证据文件：{missing}"


@pytest.mark.parametrize("key", ["path_a", "path_b"])
def test_each_postgresql_path_has_complete_machine_evidence(key):
    content = read(REQUIRED_FILES[key])
    lowered = content.lower()
    assert "postgresql" in lowered
    assert "sqlite" not in lowered
    assert FINAL_REVISION in content
    missing = [
        concept
        for concept, patterns in PATH_REQUIRED_CONCEPTS.items()
        if not any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns)
    ]
    assert not missing, f"{key} 缺少字段或命令输出：{missing}"


def test_all_evidence_agrees_on_0041_and_has_no_skip_or_sqlite_claims():
    evidence = "\n".join(read(path) for path in REQUIRED_FILES.values() if path.suffix != ".sha256")
    assert FINAL_REVISION in evidence
    assert "ALEMBIC_SKIP_SQLITE_DRIFT" not in evidence
    assert not re.search(r"sqlite.{0,40}(正式|formal|evidence|数据库)", evidence, re.IGNORECASE)
    assert not re.search(r"0040[^\n]{0,100}\((?:head|final)\)|(?:final|最终)[^\n]{0,50}0040", evidence, re.IGNORECASE)
    for key in ("path_a", "path_b", "alembic_evidence"):
        assert FINAL_REVISION in read(REQUIRED_FILES[key]), f"{key} 最终Head不是0041"


def test_checksums_file_recomputes_all_evidence_files():
    checksum_file = REQUIRED_FILES["checksums"]
    lines = [line.strip() for line in read(checksum_file).splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert lines
    covered: set[Path] = set()
    for line in lines:
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+[* ]?(.+)", line)
        assert match, f"非法SHA256行：{line}"
        expected, raw_path = match.groups()
        candidate = Path(raw_path)
        path = candidate if candidate.is_absolute() else (ROOT / candidate)
        if not path.is_file():
            path = EVIDENCE_DIR / candidate.name
        assert path.is_file(), f"Checksum目标不存在：{raw_path}"
        assert path.resolve() != checksum_file.resolve(), "checksums.sha256不得校验自身"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected.lower(), f"Checksum不匹配：{raw_path}"
        covered.add(path.resolve())
    required_covered = {path.resolve() for key, path in REQUIRED_FILES.items() if key != "checksums"}
    assert required_covered <= covered, "Checksums未覆盖全部正式证据和政策文件"


def test_v1_0001_through_0027_are_byte_identical_to_v1_0_1():
    paths = [
        line
        for line in git("ls-tree", "-r", "--name-only", V1_TAG, "--", "alembic/versions").splitlines()
        if re.search(r"/(?:00(?:0[1-9]|1[0-9]|2[0-7]))[^/]*\.py$", line)
    ]
    assert paths
    changed = []
    for relative in paths:
        tagged = subprocess.run(
            ["git", "show", f"{V1_TAG}:{relative}"], cwd=ROOT, check=True, capture_output=True
        ).stdout
        current = (ROOT / relative).read_bytes()
        if hashlib.sha256(tagged).digest() != hashlib.sha256(current).digest():
            changed.append(relative)
    assert not changed, f"V1 Migration历史被改写：{changed}"


def test_migration_0005_matches_v1_0_1_independently():
    paths = [
        line
        for line in git("ls-tree", "-r", "--name-only", V1_TAG, "--", "alembic/versions").splitlines()
        if Path(line).name.startswith("0005")
    ]
    assert paths
    for relative in paths:
        tagged = subprocess.run(
            ["git", "show", f"{V1_TAG}:{relative}"], cwd=ROOT, check=True, capture_output=True
        ).stdout
        assert hashlib.sha256(tagged).hexdigest() == hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), relative


def test_0037_change_is_disclosed_by_policy_and_evidence_document():
    policy = read(REQUIRED_FILES["freeze_policy"])
    evidence = read(REQUIRED_FILES["evidence_document"])
    for content in (policy, evidence):
        assert "0037_v2_execution_observability_security_ops" in content
        assert re.search(r"预发布|pre[- ]release|freeze|冻结", content, re.IGNORECASE)
        assert re.search(r"修改|changed|amend|改写", content, re.IGNORECASE)


def test_evidence_contains_no_secrets_connections_or_production_data():
    findings = []
    assignment = re.compile(
        r"(?i)(password|passwd|pwd|token|secret|api[_-]?key)\s*[:=]\s*([^\s,;]+)"
    )
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
