"""Regression gates for secure, reproducible application images."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
COPY_RULE = "COPY --chown=0:0 device_agents ./device_agents"
PINNED_PYTHON = "FROM python@sha256:"
RUNTIME_USER = "USER 10001:10001"


@pytest.mark.parametrize("dockerfile", ["Dockerfile.backend", "Dockerfile.worker"])
def test_application_dockerfile_copies_device_agents(dockerfile: str) -> None:
    content = (ROOT / dockerfile).read_text(encoding="utf-8")
    matching_rules = [
        line.strip() for line in content.splitlines() if line.strip() == COPY_RULE
    ]
    assert matching_rules == [COPY_RULE]


def test_device_agents_source_package_is_complete() -> None:
    required_files = {
        "device_agents/__init__.py",
        "device_agents/macos_observer/__init__.py",
        "device_agents/macos_observer/sanitizer.py",
        "device_agents/macos_observer/window_provider.py",
    }
    assert all((ROOT / relative_path).is_file() for relative_path in required_files)


@pytest.mark.parametrize("dockerfile", ["Dockerfile.backend", "Dockerfile.worker"])
def test_application_image_security_and_offline_contract(dockerfile: str) -> None:
    content = (ROOT / dockerfile).read_text(encoding="utf-8")
    first_from = next(
        line.strip() for line in content.splitlines() if line.startswith("FROM ")
    )
    assert first_from.startswith(PINNED_PYTHON)
    assert ":latest" not in first_from
    assert "ARG SOURCE_DATE_EPOCH" in content
    assert "ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}" in content
    assert "--no-index" in content
    assert "COPY artifacts/wheelhouse/linux-amd64-cp312/*.whl /wheelhouse/" in content
    assert "groupadd --gid 10001 tiantong" in content
    assert "useradd --uid 10001 --gid 10001" in content
    assert "chmod -R a-w /app" in content
    assert RUNTIME_USER in content


def test_reproducible_build_command_contract() -> None:
    content = (
        ROOT / "scripts" / "build_reproducible_application_image.sh"
    ).read_text(encoding="utf-8")
    assert "show -s --format=%ct" in content
    assert "--network=none" in content
    assert "--no-cache" in content
    assert "--provenance=false" in content
    assert "--sbom=false" in content
    assert "rewrite-timestamp=true" in content


def _run_image_import(image_env: str, import_statement: str) -> None:
    image = os.environ.get(image_env)
    if not image:
        pytest.skip(f"{image_env} is required for the image-level import gate")

    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
    ]
    runtime_env_file = os.environ.get("S12_RUNTIME_ENV_FILE")
    if runtime_env_file:
        command.extend(["--env-file", runtime_env_file])
    for name in (
        "AGENT_RUNTIME_ENABLED",
        "ALPHA_WORKFLOW_ENABLED",
        "ALPHA_SCENARIO_ENABLED",
        "ALPHA_WORKFLOW_DASHBOARD_ENABLED",
        "ALPHA_DASHBOARD_ENABLED",
    ):
        command.extend(["--env", f"{name}=false"])
    command.extend([image, "python", "-c", import_statement])

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr


def test_backend_image_imports_device_agents_and_backend_main() -> None:
    _run_image_import(
        "S12_BACKEND_IMAGE",
        "import device_agents; import backend.main",
    )


def test_worker_image_imports_device_agents_and_worker_entrypoint() -> None:
    _run_image_import(
        "S12_WORKER_IMAGE",
        "import device_agents; import backend.worker",
    )
