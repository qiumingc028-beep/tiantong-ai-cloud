#!/usr/bin/env python3
"""Observe a real Electron exit from fixed trusted code, then sign it."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import stat
import subprocess
import time
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from backend.services.jd_runtime_contract import NoCredentialRedirect

from ops.r297_windows_event_signer import produce_electron_exit_event, _process_is_running
from ops.r297_evidence_events import signed_event_sha256, verify_signed_event, write_sha256_bound_file


_SCOPE_FIELDS = {
    "namespace", "tenant_id", "company_id", "store_id", "platform", "release_sha",
    "run_id", "run_attempt", "challenge",
}
_REQUEST_FIELDS = _SCOPE_FIELDS | {
    "source_workflow_run_id", "process_id", "process_started_at", "executable_path", "executable_sha256",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_bound_json(path: Path) -> dict:
    read = _read_protected_bytes if os.name == "nt" else lambda item, label: item.read_bytes()
    content = read(path, "trusted observation request")
    digest = hashlib.sha256(content).hexdigest()
    if read(Path(f"{path}.sha256"), "trusted observation request sidecar").decode("ascii").strip().split() != [digest, path.name]:
        raise RuntimeError("trusted observation request binding invalid")
    return json.loads(content)


def _read_protected_bytes(path: Path, label: str) -> bytes:
    if os.name == "nt":
        from ops.r297_windows_file_security import read_protected
        return read_protected(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
            or (os.name != "nt" and (
                stat.S_IMODE(metadata.st_mode) & 0o222
                or metadata.st_uid not in {0, os.geteuid()}
            ))
        ):
            raise RuntimeError(f"{label} permissions invalid")
        with os.fdopen(os.dup(descriptor), "rb") as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def _read_protected_bound_json(path: Path, expected_digest: str, label: str) -> dict:
    content = _read_protected_bytes(path, label)
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_digest:
        raise RuntimeError(f"{label} approval mismatch")
    sidecar = Path(f"{path}.sha256")
    if (
        sidecar.is_symlink()
        or _read_protected_bytes(sidecar, f"{label} sidecar").decode("ascii").strip().split()
        != [digest, path.name]
    ):
        raise RuntimeError(f"{label} sidecar mismatch")
    return json.loads(content)


def _fixed_signer_checkout() -> str:
    expected = os.getenv("R297_TRUSTED_SIGNER_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise RuntimeError("trusted signer SHA missing")
    code_root = (
        Path(os.environ["R297_TEST_TRUSTED_CODE_ROOT"])
        if os.getenv("APP_ENV") == "test" and os.getenv("R297_TEST_TRUSTED_CODE_ROOT")
        else Path(__file__).resolve().parents[1]
    )
    install_root = code_root.parent
    read = (lambda path, label: path.read_bytes()) if os.getenv("APP_ENV") == "test" else _read_protected_bytes
    try:
        actual = read(install_root / "SIGNER_SHA", "trusted signer identity").decode("ascii").strip()
        manifest_bytes = read(install_root / "CODE_MANIFEST.json", "trusted signer manifest")
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("trusted signer manifest invalid") from exc
    if actual != expected:
        raise RuntimeError("trusted signer checkout mismatch")
    if not isinstance(manifest, list) or not manifest:
        raise RuntimeError("trusted signer manifest invalid")
    approved = {}
    for item in manifest:
        if (
            not isinstance(item, dict) or set(item) != {"path", "sha256"}
            or not isinstance(item["path"], str) or not re.fullmatch(r"[0-9a-f]{64}", str(item["sha256"]))
        ):
            raise RuntimeError("trusted signer manifest invalid")
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.as_posix() in approved:
            raise RuntimeError("trusted signer manifest invalid")
        approved[relative.as_posix()] = item["sha256"]
    actual_files = {
        path.relative_to(code_root).as_posix(): path
        for path in code_root.rglob("*") if path.is_file() and "__pycache__" not in path.parts
    }
    if set(actual_files) != set(approved):
        raise RuntimeError("trusted signer manifest mismatch")
    for relative, path in actual_files.items():
        if path.is_symlink() or hashlib.sha256(read(path, f"trusted signer code {relative}")).hexdigest() != approved[relative]:
            raise RuntimeError("trusted signer manifest mismatch")
    return actual


def _trusted_artifact_manifest() -> dict:
    default = Path(r"C:\ProgramData\TiantongAI\r297-windows-artifact-manifest.json")
    path = Path(os.getenv("R297_TEST_ARTIFACT_MANIFEST", "")) if os.getenv("APP_ENV") == "test" else default
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("trusted Windows artifact manifest missing")
    expected = os.getenv("R297_TRUSTED_WINDOWS_ARTIFACT_MANIFEST_SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("trusted Windows artifact manifest approval mismatch")
    return _read_protected_bound_json(path, expected, "trusted Windows artifact manifest")


def _trusted_run_binding() -> dict:
    default = Path(r"C:\ProgramData\TiantongAI\r297-acceptance-run-binding.json")
    path = Path(os.getenv("R297_TEST_RUN_BINDING", "")) if os.getenv("APP_ENV") == "test" else default
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("trusted acceptance run binding missing")
    expected = os.getenv("R297_TRUSTED_ACCEPTANCE_RUN_BINDING_SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("trusted acceptance run approval mismatch")
    return _read_protected_bound_json(path, expected, "trusted acceptance run")


def _trusted_page_observer_ack() -> dict:
    default = Path(r"C:\ProgramData\TiantongAI\R297TrustedWindowsObserver\protected\page-observer-ack.json")
    path = Path(os.getenv("R297_TEST_PAGE_OBSERVER_ACK", "")) if os.getenv("APP_ENV") == "test" else default
    expected = os.getenv("R297_TRUSTED_PAGE_OBSERVER_ACK_SHA256", "")
    if not path.is_file() or path.is_symlink() or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("trusted page Observer ACK missing")
    return _read_protected_bound_json(path, expected, "trusted page Observer ACK")


def _trusted_windows_relay_receipt() -> dict | None:
    default = Path(r"C:\ProgramData\TiantongAI\R297TrustedWindowsObserver\protected\windows-relay-receipt.json")
    path = Path(os.getenv("R297_TEST_WINDOWS_RELAY_RECEIPT", "")) if os.getenv("APP_ENV") == "test" else default
    if not path.is_file():
        return None
    if path.is_symlink():
        raise RuntimeError("trusted Windows relay receipt invalid")
    if os.getenv("APP_ENV") == "test":
        expected = os.getenv("R297_TRUSTED_WINDOWS_RELAY_RECEIPT_SHA256", "")
    else:
        approval = _read_protected_bytes(Path(f"{path}.sha256"), "trusted Windows relay receipt sidecar")
        fields = approval.decode("ascii").strip().split()
        expected = fields[0] if len(fields) == 2 and fields[1] == path.name else ""
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RuntimeError("trusted Windows relay receipt invalid")
    return _read_protected_bound_json(path, expected, "trusted Windows relay receipt")


def _relay_receipt_time(receipt: dict | None, event: dict, request: dict, current: datetime) -> datetime:
    if receipt is None:
        raise RuntimeError("trusted Windows relay receipt missing")
    expected_scope = {field: request[field] for field in _SCOPE_FIELDS}
    required = {
        "schema_version", "verifier_id", "source_workflow_run_id", "event_sha256",
        "sequence", "received_at", *expected_scope,
    }
    try:
        received_at = datetime.fromisoformat(str(receipt["received_at"]).replace("Z", "+00:00"))
        observed_at = datetime.fromisoformat(str(event["observed_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("trusted Windows relay receipt invalid") from None
    if (
        set(receipt) != required
        or type(receipt["schema_version"]) is not int
        or receipt["schema_version"] != 1
        or receipt["verifier_id"] != "tiantong-r297-receipt-broker-v1"
        or type(receipt["source_workflow_run_id"]) is not int
        or receipt["source_workflow_run_id"] != request["source_workflow_run_id"]
        or type(receipt["sequence"]) is not int
        or receipt["sequence"] != 3
        or receipt["event_sha256"] != signed_event_sha256(event)
        or any(type(receipt.get(field)) is not type(value) or receipt.get(field) != value
               for field, value in expected_scope.items())
        or received_at.tzinfo is None or observed_at.tzinfo is None
        or received_at < observed_at or received_at - observed_at > timedelta(minutes=5)
        or received_at > current + timedelta(seconds=30)
        or current - received_at > timedelta(hours=12)
    ):
        raise RuntimeError("trusted Windows relay receipt invalid")
    return received_at


def _windows_process_probe(process_id: int) -> dict:
    if os.name != "nt":
        raise RuntimeError("trusted Windows observer requires Windows")
    command = (
        "$p=Get-Process -Id " + str(process_id) + " -ErrorAction Stop;"
        "@{path=$p.Path;started_at=$p.StartTime.ToUniversalTime().ToString('o')}|ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError("Electron process cannot be independently observed")
    return json.loads(result.stdout)


def _backend_reader(url: str, bearer: str, certificate: Path, store_id: int) -> dict:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or type(store_id) is not int or store_id <= 0):
        raise RuntimeError("trusted Backend observer destination invalid")
    context = ssl.create_default_context(cafile=str(certificate))
    request = Request(
        f"{url.rstrip('/')}/api/jd-workbench/stores/{store_id}/acceptance-status",
        headers={"authorization": f"Bearer {bearer}"},
    )
    opener = build_opener(ProxyHandler({}), NoCredentialRedirect, HTTPSHandler(context=context))
    with opener.open(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError("trusted Backend observation rejected")
        return json.loads(response.read())


def _validate_request_approvals(
    request: dict, *, current: datetime, artifact_manifest: dict, run_binding: dict,
    page_observer_ack: dict | None = None,
) -> dict:
    if set(request) != _REQUEST_FIELDS:
        raise ValueError("trusted Windows observation request schema invalid")
    if (
        any(type(request[field]) is not int or request[field] <= 0 for field in
            ("store_id", "run_attempt", "source_workflow_run_id", "process_id"))
        or any(not (type(request[field]) is int and request[field] > 0 or
                    type(request[field]) is str and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request[field]))
               for field in ("tenant_id", "company_id"))
        or any(type(request[field]) is not str or re.fullmatch(pattern, request[field]) is None
               for field, pattern in {
                   "namespace": r"[A-Za-z0-9._:-]{1,128}", "run_id": r"[A-Za-z0-9._:-]{1,128}",
                   "platform": r"[a-z0-9_-]{1,32}", "release_sha": r"[0-9a-f]{40}",
                   "challenge": r"[A-Za-z0-9_-]{16,128}", "executable_sha256": r"[0-9a-f]{64}",
               }.items())
        or type(request["executable_path"]) is not str or not request["executable_path"]
        or type(request["process_started_at"]) is not str
    ):
        raise ValueError("trusted Windows observation request types invalid")
    try:
        started = datetime.fromisoformat(request["process_started_at"].replace("Z", "+00:00"))
        if started.tzinfo is None or started > current:
            raise ValueError
    except ValueError:
        raise ValueError("trusted Windows process start time invalid") from None
    scope = {field: request[field] for field in _SCOPE_FIELDS}
    expected_run = {**scope, "source_workflow_run_id": request["source_workflow_run_id"]}
    try:
        issued_at = datetime.fromisoformat(str(run_binding["issued_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        raise RuntimeError("trusted acceptance run issue time invalid") from None
    binding_matches = (
        set(run_binding) != set(expected_run) | {"issued_at", "state", "consumed_at", "event_receipts"}
        or any(type(run_binding.get(key)) is not type(value) or run_binding.get(key) != value for key, value in expected_run.items())
        or run_binding.get("state") != "issued" or run_binding.get("consumed_at") is not None
        or run_binding.get("event_receipts") != []
        or issued_at.tzinfo is None or issued_at > current + timedelta(seconds=30)
    )
    if binding_matches:
        raise RuntimeError("trusted acceptance run binding mismatch")
    age = current - issued_at
    if age > timedelta(minutes=5):
        try:
            verified_at = datetime.fromisoformat(str(page_observer_ack["verified_at"]).replace("Z", "+00:00"))
            expected_binding = os.environ["R297_TRUSTED_ACCEPTANCE_RUN_BINDING_SHA256"]
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("trusted page Observer ACK invalid") from None
        if (
            set(page_observer_ack) != {
                "schema_version", "verifier_id", "result", "verified_at", "binding_file_sha256",
                "receiver_ack_file_sha256", "observer_ack_file_sha256", "raw_event_sha256",
                "receiver_event_sha256", "observer_event_sha256",
            }
            or type(page_observer_ack["schema_version"]) is not int
            or page_observer_ack["schema_version"] != 1
            or page_observer_ack["verifier_id"] != "tiantong-r297-ack-broker-v1"
            or page_observer_ack["result"] != "VERIFIED"
            or page_observer_ack["binding_file_sha256"] != expected_binding
            or verified_at.tzinfo is None or verified_at < issued_at
            or verified_at > current + timedelta(seconds=30) or current - verified_at > timedelta(hours=12)
        ):
            raise RuntimeError("trusted page Observer ACK invalid")
    if (
        set(artifact_manifest) != {"release_sha", "workbench_executable_sha256"}
        or artifact_manifest["release_sha"] != scope["release_sha"]
        or artifact_manifest["workbench_executable_sha256"] != request["executable_sha256"]
    ):
        raise RuntimeError("Electron executable is not in trusted build manifest")
    return scope


def _validate_recovered_event(content, *, request, signer_sha, scope, relay_receipt, current):
    wrapper = json.loads(content)
    if set(wrapper) != {"signer_sha", "event"} or wrapper["signer_sha"] != signer_sha:
        raise RuntimeError("trusted Windows output binding mismatch")
    event = wrapper["event"]
    try:
        observed_at = datetime.fromisoformat(str(event["observed_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("trusted Windows output binding mismatch") from None
    verification_time = (
        _relay_receipt_time(relay_receipt, event, request, current)
        if observed_at.tzinfo is None or current - observed_at > timedelta(minutes=5)
        else current
    )
    verify_signed_event(
        event, event_type="electron_exit", issuer="windows_runner",
        environment=os.getenv("APP_ENV", "").strip().lower(), now=verification_time,
    )
    try:
        requested_started_at = datetime.fromisoformat(
            str(request["process_started_at"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc).isoformat()
    except (ValueError, AttributeError):
        raise RuntimeError("trusted Windows output binding mismatch") from None
    if (
        any(type(event.get(field)) is not type(value) or event.get(field) != value
            for field, value in scope.items())
        or event.get("payload", {}).get("exited") is not True
        or event.get("payload", {}).get("process_id") != request["process_id"]
        or event.get("payload", {}).get("process_started_at") != requested_started_at
    ):
        raise RuntimeError("trusted Windows output binding mismatch")


def recover_trusted_output(
    path: Path, *, request: dict, signer_sha: str,
    artifact_manifest: dict, run_binding: dict, page_observer_ack: dict | None = None,
    relay_receipt: dict | None = None,
    now: datetime | None = None,
) -> bool:
    """Recover only an already signed event bound to the current protected inputs."""
    if not path.exists():
        return False
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    scope = _validate_request_approvals(
        request, current=current, artifact_manifest=artifact_manifest, run_binding=run_binding,
        page_observer_ack=page_observer_ack,
    )
    def validate(content):
        _validate_recovered_event(content, request=request, signer_sha=signer_sha,
                                  scope=scope, relay_receipt=relay_receipt, current=current)
    if os.name == "nt":
        from ops.r297_windows_file_security import recover_bound_file
        recover_bound_file(path, validate=validate)
        return True
    metadata = path.lstat()
    if (path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink not in {1, 2}
            or metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o600):
        raise RuntimeError("trusted Windows output metadata invalid")
    content = path.read_bytes()
    validate(content)
    sidecar = Path(f"{path}.sha256")
    if sidecar.exists():
        digest = hashlib.sha256(content).hexdigest()
        sidecar_metadata = sidecar.lstat()
        if (
            metadata.st_nlink != 1 or sidecar.is_symlink()
            or not stat.S_ISREG(sidecar_metadata.st_mode) or sidecar_metadata.st_nlink != 1
            or (os.name != "nt" and (
                sidecar_metadata.st_uid != os.geteuid()
                or stat.S_IMODE(sidecar_metadata.st_mode) != 0o600
            ))
            or sidecar.read_text(encoding="ascii").strip().split() != [digest, path.name]
        ):
            raise RuntimeError("trusted Windows output sidecar mismatch")
    else:
        write_sha256_bound_file(path, content)
    return True


def observe_and_sign(
    request: dict, *, process_probe=_windows_process_probe,
    process_is_running=_process_is_running, backend_reader=_backend_reader,
    now=lambda: datetime.now(timezone.utc), sleep=time.sleep,
    artifact_manifest=None, run_binding=None, monotonic=time.monotonic,
    page_observer_ack=None,
) -> dict:
    approved_run = run_binding or _trusted_run_binding()
    current = now().astimezone(timezone.utc)
    manifest = artifact_manifest or _trusted_artifact_manifest()
    scope = _validate_request_approvals(
        request, current=current, artifact_manifest=manifest, run_binding=approved_run,
        page_observer_ack=page_observer_ack,
    )
    process_id = request["process_id"]
    if type(process_id) is not int or process_id <= 0 or not process_is_running(process_id):
        raise RuntimeError("Electron process was not live when trusted observation began")
    probe = process_probe(process_id)
    executable = Path(probe.get("path", "")).resolve()
    if (
        executable != Path(request["executable_path"]).resolve()
        or not re.fullmatch(r"[0-9a-f]{64}", str(request["executable_sha256"]))
        or _sha256(executable) != request["executable_sha256"]
    ):
        raise RuntimeError("Electron executable identity mismatch")
    started_at = datetime.fromisoformat(str(probe.get("started_at", "")).replace("Z", "+00:00"))
    requested_start = datetime.fromisoformat(str(request["process_started_at"]).replace("Z", "+00:00"))
    if started_at.tzinfo is None or requested_start.tzinfo is None or abs(started_at - requested_start) > timedelta(seconds=2):
        raise RuntimeError("Electron process start identity mismatch")

    deadline = monotonic() + 240
    while process_is_running(process_id):
        if monotonic() >= deadline:
            raise RuntimeError("Electron exit observation timed out")
        sleep(0.25)
    exited_at = now().astimezone(timezone.utc)

    backend_url = os.getenv("R297_TRUSTED_OBSERVER_BACKEND_HTTPS_URL", "")
    bearer = os.getenv("R297_TRUSTED_OBSERVER_BEARER", "")
    certificate = Path(os.getenv("R297_TRUSTED_OBSERVER_CA_PATH", ""))
    if not backend_url.startswith("https://") or not bearer or not certificate.is_file():
        raise RuntimeError("trusted Backend observer configuration missing")
    while True:
        status = backend_reader(backend_url, bearer, certificate, scope["store_id"])
        completed_value = status.get("latest_completed_at")
        completed = datetime.fromisoformat(str(completed_value).replace("Z", "+00:00")) if completed_value is not None else None
        if (
            status.get("release_sha") == scope["release_sha"]
            and all(status.get(field) == scope[field] for field in (
                "namespace", "tenant_id", "company_id", "store_id", "platform", "run_id",
            ))
            and completed is not None and completed.tzinfo is not None and completed > exited_at
        ):
            break
        if monotonic() >= deadline:
            raise RuntimeError("post-exit scheduler observation timed out")
        sleep(1)
    return produce_electron_exit_event(
        scope=scope, process_id=process_id, process_started_at=started_at,
        observed_at=exited_at, process_is_running=lambda _pid: False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    signer_sha = _fixed_signer_checkout()
    request = _read_bound_json(args.request)
    artifact_manifest = _trusted_artifact_manifest()
    run_binding = _trusted_run_binding()
    issued_at = datetime.fromisoformat(str(run_binding.get("issued_at", "")).replace("Z", "+00:00"))
    page_observer_ack = (
        _trusted_page_observer_ack()
        if issued_at.tzinfo is None or datetime.now(timezone.utc) - issued_at > timedelta(minutes=5)
        else None
    )
    if recover_trusted_output(
        args.output, request=request, signer_sha=signer_sha,
        artifact_manifest=artifact_manifest, run_binding=run_binding,
        page_observer_ack=page_observer_ack,
        relay_receipt=_trusted_windows_relay_receipt(),
    ):
        print(f"R297_TRUSTED_WINDOWS_EVENT={args.output}")
        print(f"R297_TRUSTED_SIGNER_SHA={signer_sha}")
        print("R297_TRUSTED_WINDOWS_EVENT_RECOVERY=PASS")
        return 0
    event = observe_and_sign(
        request, artifact_manifest=artifact_manifest, run_binding=run_binding,
        page_observer_ack=page_observer_ack,
    )
    content = (json.dumps({"signer_sha": signer_sha, "event": event}, sort_keys=True) + "\n").encode()
    write_sha256_bound_file(args.output, content)
    print(f"R297_TRUSTED_WINDOWS_EVENT={args.output}")
    print(f"R297_TRUSTED_SIGNER_SHA={signer_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
