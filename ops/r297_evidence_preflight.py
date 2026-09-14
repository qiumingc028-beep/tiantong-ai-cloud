#!/usr/bin/env python3
"""Report controlled R297 evidence material readiness without exposing values."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import stat
import re
from urllib.parse import urlparse

from ops import r297_evidence_events


_KEYS = {
    "PAGE_EVENT_RECEIVER_PRIVATE_KEY": "R297_PAGE_EVENT_RECEIVER_PRIVATE_KEY_PATH",
    "OBSERVER_PRIVATE_KEY": "R297_OBSERVER_PRIVATE_KEY_PATH",
    "WINDOWS_RUNNER_PRIVATE_KEY": "R297_WINDOWS_RUNNER_PRIVATE_KEY_PATH",
}
_PAGEHIDE_BINDING = Path("/etc/tiantong/r297-pagehide-artifact-binding.json")
_RUN_BINDING = Path("/etc/tiantong/r297-acceptance-run-binding.json")


def _private_key_status(path_value: str, *, windows: bool = os.name == "nt") -> str | None:
    if not path_value:
        return "MISSING"
    path = Path(path_value)
    try:
        metadata = path.lstat()
        content = path.read_bytes()
    except OSError:
        return "INVALID_PRIVATE_KEY"
    permissions_invalid = (
        bool(metadata.st_mode & stat.S_IWRITE)
        if windows else metadata.st_uid not in {0, os.geteuid()} or bool(stat.S_IMODE(metadata.st_mode) & 0o077)
    )
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or permissions_invalid:
        return "INVALID_PRIVATE_KEY_PERMISSIONS"
    if b'"environment":"test"' in content.replace(b" ", b""):
        return "TEST_ONLY_PRIVATE_KEY"
    return None


def inspect_controlled_material(*, environment: str, role: str) -> dict:
    missing: list[str] = []
    invalid: list[str] = []
    roles = {"page_event_receiver", "authenticated_observer", "windows_runner", "verifier"}
    if environment not in {"acceptance", "production"}:
        return {"role": role, "result": "BLOCK", "missing": [], "invalid": ["ENVIRONMENT"]}
    if role not in roles:
        return {"role": role, "result": "BLOCK", "missing": [], "invalid": ["ROLE"]}
    if not re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", os.getenv("R297_ACCEPTANCE_RUN_ID", "")):
        missing.append("ACCEPTANCE_RUN_ID")
    if not re.fullmatch(r"[1-9][0-9]*", os.getenv("R297_ACCEPTANCE_RUN_ATTEMPT", "")):
        missing.append("ACCEPTANCE_RUN_ATTEMPT")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", os.getenv("R297_ACCEPTANCE_CHALLENGE", "")):
        missing.append("ACCEPTANCE_CHALLENGE")

    role_keys = {
        "page_event_receiver": ("PAGE_EVENT_RECEIVER_PRIVATE_KEY",),
        "authenticated_observer": ("OBSERVER_PRIVATE_KEY",),
        "windows_runner": ("WINDOWS_RUNNER_PRIVATE_KEY",),
        "verifier": (),
    }
    allowed_key_variables = {_KEYS[label] for label in role_keys[role]}
    if any(os.getenv(variable, "") for variable in set(_KEYS.values()) - allowed_key_variables):
        invalid.append("CROSS_ROLE_PRIVATE_KEY")
    for label in role_keys[role]:
        variable = _KEYS[label]
        status = _private_key_status(os.getenv(variable, ""))
        if status == "MISSING":
            missing.append(label)
        elif status:
            invalid.append(status)

    fixed_files = {
        "TRUST_MANIFEST": r297_evidence_events._PRODUCTION_TRUST_MANIFEST,
        "TRUST_MANIFEST_SIDECAR": r297_evidence_events._PRODUCTION_TRUST_MANIFEST_SIDECAR,
    }
    if role == "page_event_receiver":
        fixed_files.update({
            "PAGEHIDE_BINDING": _PAGEHIDE_BINDING,
            "PAGEHIDE_BINDING_SIDECAR": Path(f"{_PAGEHIDE_BINDING}.sha256"),
            "RUN_BINDING": _RUN_BINDING,
            "RUN_BINDING_SIDECAR": Path(f"{_RUN_BINDING}.sha256"),
        })
    for label, path in fixed_files.items():
        if not path.is_file():
            missing.append(label)

    if role == "authenticated_observer":
        database_url = os.getenv("R297_OBSERVER_DATABASE_URL", "")
        if not database_url:
            missing.append("READ_ONLY_DATABASE_URL")
        elif urlparse(database_url).scheme not in {"postgres", "postgresql"}:
            invalid.append("READ_ONLY_DATABASE_URL")

    if role == "verifier":
        if not os.getenv("R297_ACCEPTANCE_BROKER_SOCKET"):
            missing.append("BROKER_SOCKET")
        else:
            try:
                from ops.r297_broker_client import broker_request
                broker_request({"action": "validate", "scope": {
                    "namespace": os.environ["R297_EVIDENCE_NAMESPACE"],
                    "tenant_id": int(os.environ["R297_EVIDENCE_TENANT_ID"]),
                    "company_id": int(os.environ["R297_EVIDENCE_COMPANY_ID"]),
                    "store_id": int(os.environ["R297_EVIDENCE_STORE_ID"]),
                    "platform": os.getenv("R297_EVIDENCE_PLATFORM", "jd"),
                    "release_sha": os.environ["RELEASE_SOURCE_SHA"],
                    "run_id": os.environ["R297_ACCEPTANCE_RUN_ID"],
                    "run_attempt": int(os.environ["R297_ACCEPTANCE_RUN_ATTEMPT"]),
                    "challenge": os.environ["R297_ACCEPTANCE_CHALLENGE"],
                }, "source_workflow_run_id": int(os.environ["R297_SOURCE_PAGEHIDE_WORKFLOW_RUN_ID"]),
                   "transaction_sha256": os.getenv("R297_ACCEPTANCE_TRANSACTION_SHA256")})
            except (KeyError, OSError, RuntimeError, ValueError):
                invalid.append("BROKER_TRANSACTION")

    if role == "windows_runner":
        backend_url = os.getenv("R297_WINDOWS_CANARY_BACKEND_HTTPS_URL", "")
        parsed_backend = urlparse(backend_url)
        if not backend_url:
            missing.append("BACKEND_HTTPS_URL")
        elif parsed_backend.scheme != "https" or not parsed_backend.netloc:
            invalid.append("BACKEND_HTTPS_URL")
        if not os.getenv("R297_WINDOWS_CANARY_PAIRING_ISSUER_BEARER", ""):
            missing.append("PAIRING_ISSUER_AUTHORIZATION")
        certificate = os.getenv("R297_WINDOWS_CANARY_SERVER_CERTIFICATE_BASE64", "")
        if not certificate:
            missing.append("BACKEND_CERTIFICATE")
        else:
            try:
                if not base64.b64decode(certificate, validate=True):
                    raise ValueError
            except ValueError:
                invalid.append("BACKEND_CERTIFICATE")

    if not missing:
        try:
            r297_evidence_events.load_trust_manifest(environment=environment)
            if role == "page_event_receiver":
                from ops import r297_authenticated_observer

                r297_authenticated_observer.load_pagehide_artifact_binding(environment)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
            invalid.append("PROTECTED_BINDING_VALIDATION")
    return {
        "role": role,
        "result": "PASS" if not missing and not invalid else "BLOCK",
        "missing": sorted(set(missing)),
        "invalid": sorted(set(invalid)),
    }


def main() -> int:
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument(
        "--role", required=True,
        choices=("page_event_receiver", "authenticated_observer", "windows_runner", "verifier"),
    )
    args = parser.parse_args()
    result = inspect_controlled_material(
        environment=os.getenv("APP_ENV", "").strip().lower(), role=args.role,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
