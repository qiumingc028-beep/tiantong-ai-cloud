"""Offline contract checks for the ACR-native Python dependency base image."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "artifacts/wheelhouse/linux-amd64-cp312/requirements-linux-amd64-cp312.lock"
SUMS = ROOT / "artifacts/wheelhouse/linux-amd64-cp312/SHA256SUMS"
MANIFEST = ROOT / "artifacts/wheelhouse/linux-amd64-cp312/artifact-manifest.json"
DOCKERFILE = ROOT / "Dockerfile.python-deps"
APPLICATION_REQUIREMENTS = ROOT / "requirements.txt"
APPLICATION_DOCKERFILES = [ROOT / "Dockerfile.backend", ROOT / "Dockerfile.worker"]
BASE = (
    "tiantong-v2-prod-registry-vpc.cn-shenzhen.cr.aliyuncs.com/"
    "tiantong-v2/python-base@sha256:"
    "49f3bd3ed3a1c554a43f1e9d03ff303716afed6eda0f3e98c34cd976c8880cd6"
)
LOCK_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[A-Za-z0-9_.+-]+) "
    r"--hash=sha256:(?P<digest>[0-9a-f]{64})$"
)
SUM_LINE = re.compile(r"^(?P<digest>[0-9a-f]{64})  (?P<filename>[^/\\\x00]+\.whl)$")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def _parse_lock(text: str) -> list[dict[str, str]]:
    entries = []
    for raw in text.splitlines():
        if not raw or raw.startswith("#"):
            continue
        match = LOCK_LINE.fullmatch(raw)
        if match is None:
            raise ValueError("LOCK_ENTRY_INVALID")
        entries.append(match.groupdict())
    if len(entries) != 36:
        raise ValueError("LOCK_ENTRY_COUNT_INVALID")
    if len({entry["name"].lower().replace("_", "-") for entry in entries}) != 36:
        raise ValueError("LOCK_PACKAGE_DUPLICATE")
    return entries


def _parse_sums(text: str) -> dict[str, str]:
    entries = {}
    for raw in text.splitlines():
        match = SUM_LINE.fullmatch(raw)
        if match is None:
            raise ValueError("SUM_ENTRY_INVALID")
        filename = match.group("filename")
        if filename in entries:
            raise ValueError("SUM_FILENAME_DUPLICATE")
        if re.search(r"(?i)(arm64|aarch64)", filename):
            raise ValueError("ARM64_WHEEL_REJECTED")
        entries[filename] = match.group("digest")
    if len(entries) != 36:
        raise ValueError("SUM_ENTRY_COUNT_INVALID")
    return entries


def _verify(lock_text: str, sums_text: str, manifest: dict, dockerfile: str) -> dict:
    lock = _parse_lock(lock_text)
    sums = _parse_sums(sums_text)
    wheels = manifest.get("wheels")
    if (
        manifest.get("platform") != "amd64"
        or not isinstance(wheels, list)
        or len(wheels) != 36
    ):
        raise ValueError("MANIFEST_PLATFORM_OR_COUNT_INVALID")
    manifest_map = {item.get("filename"): item.get("local_sha256") for item in wheels}
    if manifest_map != sums:
        raise ValueError("MANIFEST_SUM_BINDING_INVALID")
    if {entry["digest"] for entry in lock} != set(sums.values()):
        raise ValueError("LOCK_SUM_BINDING_INVALID")
    for filename in sums:
        if "manylinux" in filename and "x86_64" not in filename:
            raise ValueError("NON_AMD64_BINARY_WHEEL_REJECTED")
    lines = [line.strip() for line in dockerfile.splitlines() if line.strip()]
    from_lines = [line for line in lines if line.startswith("FROM ")]
    if from_lines != ["FROM " + BASE]:
        raise ValueError("BASE_IMAGE_INVALID")
    required = [
        "ARG TARGETPLATFORM=linux/amd64",
        'RUN test "$TARGETPLATFORM" = "linux/amd64"',
        "--require-hashes",
        "--only-binary=:all:",
        "--no-cache-dir",
        "pip check",
    ]
    if any(value not in dockerfile for value in required):
        raise ValueError("PIP_OR_PLATFORM_CONTRACT_INVALID")
    forbidden = [
        "latest",
        "docker.io/",
        "--no-deps",
        "|| true",
        "ADD ",
        "COPY backend",
        "COPY frontend",
        "COPY . ",
        "ARG TOKEN",
        "ARG SECRET",
        "ARG PASSWORD",
    ]
    if any(value in dockerfile for value in forbidden):
        raise ValueError("FORBIDDEN_CAPABILITY_PRESENT")
    copy_lines = [line for line in lines if line.startswith("COPY ")]
    expected_copy = (
        "COPY artifacts/wheelhouse/linux-amd64-cp312/"
        "requirements-linux-amd64-cp312.lock /tmp/requirements.lock"
    )
    if copy_lines != [expected_copy]:
        raise ValueError("DEPENDENCY_ONLY_COPY_INVALID")
    return {"digest_count": len(lock), "lock_entry_count": len(lock), "wheel_metadata_count": len(sums)}


def _expect_rejected(lock_text: str, sums_text: str, manifest: dict, dockerfile: str) -> None:
    try:
        _verify(lock_text, sums_text, manifest, dockerfile)
    except (TypeError, ValueError):
        return
    raise AssertionError("failure injection was accepted")


def run_contract() -> dict:
    lock_text = LOCK.read_text(encoding="ascii")
    sums_text = SUMS.read_text(encoding="ascii")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dockerfile = DOCKERFILE.read_text(encoding="ascii")
    baseline = _verify(lock_text, sums_text, manifest, dockerfile)
    lock_lines = [line for line in lock_text.splitlines() if line and not line.startswith("#")]
    locked = {
        entry["name"].lower().replace("_", "-"): entry["version"]
        for entry in _parse_lock(lock_text)
    }
    application = {}
    for raw in APPLICATION_REQUIREMENTS.read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)", raw)
        if match is None:
            raise ValueError("APPLICATION_REQUIREMENT_INVALID")
        application[match.group(1).lower().replace("_", "-")] = match.group(2)
    if any(locked.get(name) != version for name, version in application.items()):
        raise ValueError("APPLICATION_LOCK_VERSION_MISMATCH")
    if set(locked) - set(application) != {"async-timeout"}:
        raise ValueError("APPLICATION_LOCK_SET_MISMATCH")
    lock_reference = "artifacts/wheelhouse/linux-amd64-cp312/requirements-linux-amd64-cp312.lock"
    for application_dockerfile in APPLICATION_DOCKERFILES:
        content = application_dockerfile.read_text(encoding="ascii")
        if (
            content.count(lock_reference) != 1
            or "--require-hashes" not in content
            or "--only-binary=:all:" not in content
        ):
            raise ValueError("APPLICATION_DOCKERFILE_LOCK_BINDING_INVALID")
    injections = [
        (lock_text.replace(" --hash=sha256:", " ", 1), sums_text, manifest, dockerfile),
        (lock_text.replace(lock_lines[0][-64:], "a" * 63, 1), sums_text, manifest, dockerfile),
        (lock_text.replace("alembic", "alembic\u200b", 1), sums_text, manifest, dockerfile),
        (lock_text.replace("alembic==1.16.5", "alembic>=1.16.5", 1), sums_text, manifest, dockerfile),
        (lock_text.replace(lock_lines[0][-64:], "0" * 64, 1), sums_text, manifest, dockerfile),
        (
            lock_text,
            sums_text.replace("py3-none-any.whl", "py3-none-aarch64.whl", 1),
            manifest,
            dockerfile,
        ),
        (lock_text, sums_text.replace(".whl", ".tar.gz", 1), manifest, dockerfile),
        (lock_text, sums_text, manifest, dockerfile.replace(BASE, "python:latest")),
        (
            lock_text,
            sums_text,
            manifest,
            dockerfile.replace(BASE, "docker.io/library/python:3.12-slim"),
        ),
        (lock_text, sums_text, manifest, dockerfile.replace(BASE[-64:], "0" * 64)),
        (lock_text + "extra==1 --hash=sha256:" + "1" * 64 + "\n", sums_text, manifest, dockerfile),
        ("\n".join(lock_text.splitlines()[:-1]) + "\n", sums_text, manifest, dockerfile),
        (lock_text, sums_text, manifest, dockerfile + "\nARG SECRET\n"),
        (lock_text, sums_text, manifest, dockerfile.replace("--require-hashes", "")),
        (lock_text, sums_text, manifest, dockerfile + "\nRUN false || true\n"),
        (
            lock_text,
            sums_text,
            manifest,
            dockerfile.replace("--only-binary=:all:", "--prefer-binary"),
        ),
        (lock_text, sums_text, manifest, dockerfile + "\nCOPY backend /app/backend\n"),
        (lock_text, sums_text, manifest, dockerfile.replace("linux/amd64", "linux/arm64")),
    ]
    for values in injections:
        _expect_rejected(*values)
    result = dict(baseline)
    result.update(
        {
            "backend_dependency_set_match": True,
            "failure_injection_pass": len(injections),
            "failure_injection_total": len(injections),
            "result": "PASS",
            "worker_dependency_set_match": True,
        }
    )
    result["result_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


def test_python_dependency_base_contract() -> None:
    result = run_contract()
    if result["result"] != "PASS":
        raise AssertionError("contract did not pass")


if __name__ == "__main__":
    print(_canonical(run_contract()).decode("ascii"))
