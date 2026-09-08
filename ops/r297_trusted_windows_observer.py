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
from ops.r297_evidence_events import verify_signed_event, write_sha256_bound_file


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
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if Path(f"{path}.sha256").read_text(encoding="ascii").strip().split() != [digest, path.name]:
        raise RuntimeError("trusted observation request binding invalid")
    return json.loads(content)


def _windows_acl_is_protected(path: Path) -> bool:
    script = r'''
$acl = Get-Acl -LiteralPath $args[0]
$allowed = @('S-1-5-18', 'S-1-5-32-544')
$owner = $acl.Owner
try { $owner = ([System.Security.Principal.NTAccount]$owner).Translate([System.Security.Principal.SecurityIdentifier]).Value } catch {}
if ($allowed -notcontains $owner) { exit 3 }
$write = [int]([System.Security.AccessControl.FileSystemRights]::Write -bor [System.Security.AccessControl.FileSystemRights]::Modify -bor [System.Security.AccessControl.FileSystemRights]::FullControl)
foreach ($entry in $acl.Access) {
  if ($entry.AccessControlType -ne 'Allow') { continue }
  try { $sid = $entry.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value } catch { exit 4 }
  if (([int]$entry.FileSystemRights -band $write) -ne 0 -and $allowed -notcontains $sid) { exit 5 }
}
'''
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script, str(path)],
        capture_output=True, check=False,
    ).returncode == 0


def _read_protected_bytes(path: Path, label: str) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
            or (os.name != "nt" and (
                stat.S_IMODE(metadata.st_mode) & 0o222
                or metadata.st_uid not in {0, os.geteuid()}
            ))
            or (os.name == "nt" and not _windows_acl_is_protected(path))
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
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1],
        text=True, capture_output=True, check=True,
    ).stdout.strip()
    if actual != expected:
        raise RuntimeError("trusted signer checkout mismatch")
    dirty = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True, check=True,
    ).stdout
    if dirty:
        raise RuntimeError("trusted signer checkout is not immutable")
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
) -> dict:
    if set(request) != _REQUEST_FIELDS:
        raise ValueError("trusted Windows observation request schema invalid")
    scope = {field: request[field] for field in _SCOPE_FIELDS}
    expected_run = {**scope, "source_workflow_run_id": request["source_workflow_run_id"]}
    try:
        issued_at = datetime.fromisoformat(str(run_binding["issued_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        raise RuntimeError("trusted acceptance run issue time invalid") from None
    if (
        {key: value for key, value in run_binding.items() if key != "issued_at"} != expected_run
        or issued_at.tzinfo is None or issued_at > current + timedelta(seconds=30)
        or current - issued_at > timedelta(minutes=5)
    ):
        raise RuntimeError("trusted acceptance run binding mismatch")
    if (
        set(artifact_manifest) != {"release_sha", "workbench_executable_sha256"}
        or artifact_manifest["release_sha"] != scope["release_sha"]
        or artifact_manifest["workbench_executable_sha256"] != request["executable_sha256"]
    ):
        raise RuntimeError("Electron executable is not in trusted build manifest")
    return scope


def recover_trusted_output(
    path: Path, *, request: dict, signer_sha: str,
    artifact_manifest: dict, run_binding: dict, now: datetime | None = None,
) -> bool:
    """Recover only an already signed event bound to the current protected inputs."""
    if not path.exists():
        return False
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    scope = _validate_request_approvals(
        request, current=current, artifact_manifest=artifact_manifest, run_binding=run_binding,
    )
    metadata = path.lstat()
    if (
        path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink not in {1, 2}
        or (os.name != "nt" and (
            metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o600
        ))
    ):
        raise RuntimeError("trusted Windows output metadata invalid")
    content = path.read_bytes()
    wrapper = json.loads(content)
    if set(wrapper) != {"signer_sha", "event"} or wrapper["signer_sha"] != signer_sha:
        raise RuntimeError("trusted Windows output binding mismatch")
    event = wrapper["event"]
    verify_signed_event(
        event, event_type="electron_exit", issuer="windows_runner",
        environment=os.getenv("APP_ENV", "").strip().lower(), now=current,
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
) -> dict:
    approved_run = run_binding or _trusted_run_binding()
    current = now().astimezone(timezone.utc)
    manifest = artifact_manifest or _trusted_artifact_manifest()
    scope = _validate_request_approvals(
        request, current=current, artifact_manifest=manifest, run_binding=approved_run,
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
    if recover_trusted_output(
        args.output, request=request, signer_sha=signer_sha,
        artifact_manifest=artifact_manifest, run_binding=run_binding,
    ):
        print(f"R297_TRUSTED_WINDOWS_EVENT={args.output}")
        print(f"R297_TRUSTED_SIGNER_SHA={signer_sha}")
        print("R297_TRUSTED_WINDOWS_EVENT_RECOVERY=PASS")
        return 0
    event = observe_and_sign(
        request, artifact_manifest=artifact_manifest, run_binding=run_binding,
    )
    content = (json.dumps({"signer_sha": signer_sha, "event": event}, sort_keys=True) + "\n").encode()
    write_sha256_bound_file(args.output, content)
    print(f"R297_TRUSTED_WINDOWS_EVENT={args.output}")
    print(f"R297_TRUSTED_SIGNER_SHA={signer_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
