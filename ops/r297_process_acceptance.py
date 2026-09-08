#!/usr/bin/env python3
"""Run the R297 process gate against isolated real processes and containers."""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError

try:
    from ops.r297_evidence_events import signed_event_sha256, verify_acceptance_event_bundle, write_sha256_bound_file
    from ops.r297_acceptance_run import (
        complete_acceptance_run, recover_staged_acceptance_output,
        reserve_acceptance_run, stage_acceptance_output,
    )
except ModuleNotFoundError as exc:
    if exc.name != "ops":
        raise
    from r297_evidence_events import signed_event_sha256, verify_acceptance_event_bundle, write_sha256_bound_file
    from r297_acceptance_run import (
        complete_acceptance_run, recover_staged_acceptance_output,
        reserve_acceptance_run, stage_acceptance_output,
    )


ROOT = Path(__file__).resolve().parents[1]


def run(*argv: str, env: dict[str, str] | None = None, capture: bool = True) -> str:
    result = subprocess.run(
        argv,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=capture,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"COMMAND_FAILED:{Path(argv[0]).name}:{result.returncode}")
    return result.stdout.strip()


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wait_http(url: str, headers: dict[str, str] | None = None, timeout: float = 60) -> dict:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            with urlopen(Request(url, headers=headers or {}), timeout=2) as response:
                if response.status == 200:
                    return json.loads(response.read())
        except Exception as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"HTTP_NOT_READY:{url}:{type(last_error).__name__}")


def post_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        raise RuntimeError(f"HTTP_POST_FAILED:{exc.code}") from exc


def device_post(url: str, path: str, payload: dict, token: str, private_key: Path) -> dict:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    canonical = "\n".join(("R291", timestamp, nonce, "POST", path, hashlib.sha256(body).hexdigest())).encode()
    signed = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", str(private_key)],
        input=canonical,
        capture_output=True,
        check=True,
    )
    signature = signed.stdout
    request = Request(
        url,
        data=body,
        headers={
            "content-type": "application/json",
            "authorization": f"Device {token}",
            "x-r291-timestamp": timestamp,
            "x-r291-nonce": nonce,
            "x-r291-signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode(),
        },
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read())


def wait_container(name: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = run("docker", "inspect", "--format", "{{.State.Status}}", name)
        if state == "running":
            return
        time.sleep(0.25)
    raise RuntimeError(f"CONTAINER_NOT_RUNNING:{name}")


def wait_command(*argv: str, timeout: float = 60) -> str:
    deadline = time.monotonic() + timeout
    last_stderr = ""
    while time.monotonic() < deadline:
        result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=False)
        if result.returncode == 0:
            return result.stdout.strip()
        last_stderr = result.stderr[-500:]
        time.sleep(0.25)
    raise RuntimeError(f"COMMAND_NOT_READY:{argv[0]}:{last_stderr}")


def wait_task(redis_client, task_id: str, status: str = "success", timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = redis_client.get(f"tiantong:task_status:{task_id}")
        if raw:
            value = json.loads(raw)
            if value["status"] == status:
                return value
            if value["status"] == "failed":
                raise RuntimeError(f"TASK_FAILED:{task_id}")
        time.sleep(0.1)
    raise RuntimeError(f"TASK_TIMEOUT:{task_id}:{status}")


def start_python(module: str, env: dict[str, str], log_path: Path) -> subprocess.Popen:
    handle = log_path.open("ab", buffering=0)
    process = subprocess.Popen(
        [sys.executable, "-m", module],
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    process._r297_log_handle = handle  # type: ignore[attr-defined]
    return process


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
    handle = getattr(process, "_r297_log_handle", None)
    if handle:
        handle.close()


def observe_stale_manual_claim(stale_task: dict, worker_id: str, *, probe_generation: int, resumed_generation: int) -> dict:
    """Observe the real database fence and Redis ACK after manual recovery."""
    from backend.database import SessionLocal
    from backend.queue import ack_task
    from backend.services.jd_collectors import JdCollectorError
    from backend.worker import _assert_jd_workbench_claim_owned, _finish_jd_workbench_task, reconcile_completed_jd_workbench_tasks

    db = SessionLocal()
    try:
        try:
            _assert_jd_workbench_claim_owned(db, stale_task, worker_id)
        except JdCollectorError:
            commit_rejected = True
        else:
            commit_rejected = False
    finally:
        db.rollback()
        db.close()
    finish_rejected = not _finish_jd_workbench_task(stale_task, worker_id, success=True, now=datetime.now(timezone.utc))
    reconcile_completed_jd_workbench_tasks()
    ack_rejected = not ack_task(stale_task, worker_id)
    result = {
        "stale_claim_generation": stale_task["db_claim_generation"],
        "probe_claim_generation": probe_generation,
        "resumed_claim_generation": resumed_generation,
        "stale_worker_commit_rejected": commit_rejected and finish_rejected,
        "stale_worker_ack_rejected_after_reconciliation": ack_rejected,
    }
    if not (
        stale_task["db_claim_generation"] <= probe_generation <= resumed_generation
        and stale_task["db_claim_generation"] < resumed_generation
        and commit_rejected and finish_rejected and ack_rejected
    ):
        raise RuntimeError("HUMAN_ACTION_STALE_WORKER_FENCE_FAILED")
    return result


def _validate_process_evidence(
    previous: dict, path: Path, verified_events: dict, *, head: str,
    transaction_sha256: str,
) -> None:
    result_sections = (
        "web_page_close", "electron_exit", "worker_restart", "multi_worker",
        "retry_schedule", "manual_resume", "human_action_detection", "service_restart",
        "two_cycle", "idempotent_write", "orphan_recovery", "runtime_restart",
        "explicit_ack",
    )
    if (
        previous.get("commit") != head
        or previous.get("acceptance_transaction_sha256") != transaction_sha256
        or previous.get("mode") != "real_process" or previous.get("mock_count") != 0
        or previous.get("controlled_canary") is not True
        or previous.get("data_source") != "CONTROLLED_CANARY"
        or previous.get("real_jd_acceptance") is not False
        or previous.get("source_code_write_count") != 0
        or previous.get("production_connection_count") != 0
        or previous.get("secret_exposure_count") != 0
        or any(previous.get(key) != value for key, value in verified_events.items())
    ):
        raise RuntimeError("RECOVERED_PROCESS_EVIDENCE_BINDING_MISMATCH")
    raw_log = Path(str(previous.get("raw_log_path", "")))
    fixture = Path(str(previous.get("sensitive_fixture_path", "")))
    for subordinate, digest_key in (
        (raw_log, "raw_log_sha256"), (fixture, "sensitive_fixture_sha256"),
    ):
        if (
            subordinate.parent.resolve() != path.parent.resolve() or not subordinate.is_file()
            or subordinate.is_symlink() or subordinate.stat().st_nlink != 1
            or sha256(subordinate) != previous.get(digest_key)
        ):
            raise RuntimeError("RECOVERED_PROCESS_EVIDENCE_SUBORDINATE_BINDING_INVALID")
    events = [json.loads(line) for line in raw_log.read_text(encoding="utf-8").splitlines() if line]
    commands = [event["command"] for event in events if event.get("event") == "command"]
    raw_results = {event["gate"]: event["result"] for event in events if event.get("event") == "gate_result"}
    if (
        not commands or commands != previous.get("exact_commands")
        or any("mock" in command.lower() for command in commands)
        or any(raw_results.get(section) != previous.get(section) for section in result_sections)
    ):
        raise RuntimeError("RECOVERED_PROCESS_EVIDENCE_RAW_GATE_INVALID")
    canaries = json.loads(fixture.read_text(encoding="utf-8"))
    injections = [event for event in events if event.get("event") == "sensitive_fixture_injected"]
    if (
        set(canaries) != {"buyer_name", "phone", "address", "cookie", "token", "password"}
        or injections != [{
            "event": "sensitive_fixture_injected",
            "fixture_sha256": previous["sensitive_fixture_sha256"],
            "fields": sorted(canaries),
        }]
        or any(value and value in raw_log.read_text(encoding="utf-8") for value in canaries.values())
    ):
        raise RuntimeError("RECOVERED_PROCESS_EVIDENCE_FIXTURE_INVALID")
    worker = previous["worker_restart"]
    multi = previous["multi_worker"]
    retry = previous["retry_schedule"]
    manual = previous["manual_resume"]
    service = previous["service_restart"]
    cycles = previous.get("two_cycle", [])
    idempotent = previous.get("idempotent_write", {})
    orphan = previous.get("orphan_recovery", {})
    runtime = previous.get("runtime_restart", {})
    ack = previous.get("explicit_ack", {})
    if (
        worker.get("pid_before") == worker.get("pid_after")
        or worker.get("recovered") is not True
        or len(set(multi.get("worker_pids", []))) < 2
        or multi.get("distinct_worker_pids") is not True
        or multi.get("status") != "success"
        or multi.get("claim_log_count") != 1
        or multi.get("database_log_count") != 1
        or multi.get("postgresql_store_claim_count") != 1
        or multi.get("same_store_claim_count") != 1
        or retry.get("expected_seconds") != [30, 120, 300, 900, 1800]
        or retry.get("observed_seconds") != retry.get("expected_seconds")
        or manual.get("before_status") != "HUMAN_ACTION_REQUIRED"
        or manual.get("recovery_probe_status") != "success"
        or manual.get("automatic_enqueue_count") != 1
        or manual.get("task_status") != "success"
        or manual.get("stale_worker_commit_rejected") is not True
        or manual.get("stale_worker_ack_rejected_after_reconciliation") is not True
        or not all(type(manual.get(field)) is int for field in (
            "stale_claim_generation", "probe_claim_generation", "resumed_claim_generation",
        ))
        or not manual["stale_claim_generation"] <= manual["probe_claim_generation"] <= manual["resumed_claim_generation"]
        or manual["stale_claim_generation"] >= manual["resumed_claim_generation"]
        or not manual.get("recovery_probe_task_id") or not manual.get("task_id")
        or previous["human_action_detection"] != {
            "detected_status": "HUMAN_ACTION_REQUIRED", "automatic_resume_status": "success",
        }
        or service.get("runtime_pid_before") == service.get("runtime_pid_after")
        or service.get("backend_pid_before") == service.get("backend_pid_after")
        or service.get("runtime_session_restored") is not True
        or len(cycles) != 2
        or len({item.get("task_id") for item in cycles}) != 2
        or any(item.get("status") != "success" or item.get("database_log_count") != 1 for item in cycles)
        or idempotent.get("metric_row_count") != len(idempotent.get("rows", []))
        or idempotent.get("metric_row_count") != 1
        or orphan.get("processing_observed") is not True
        or orphan.get("final_status") != "success"
        or orphan.get("database_log_count") != 1
        or not orphan.get("task_id") or not isinstance(orphan.get("killed_worker_pid"), int)
        or runtime.get("pid_before") == runtime.get("pid_after")
        or runtime.get("session_restored") is not True
        or ack != {"ready_count": 0, "processing_count": 0, "metadata_count": 0}
    ):
        raise RuntimeError("RECOVERED_PROCESS_EVIDENCE_GATE_INVALID")


def recover_published_process_evidence(
    path: Path, *, head: str, transaction_sha256: str, verified_events: dict,
) -> str | None:
    """Seal or verify only the exact transaction left by an interrupted run."""
    if not path.exists():
        return None
    metadata = path.lstat()
    if (
        path.is_symlink() or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink not in {1, 2}
    ):
        raise RuntimeError("RECOVERED_PROCESS_EVIDENCE_METADATA_INVALID")
    content = path.read_bytes()
    previous = json.loads(content)
    _validate_process_evidence(
        previous, path, verified_events, head=head,
        transaction_sha256=transaction_sha256,
    )
    digest = hashlib.sha256(content).hexdigest()
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if sidecar.exists():
        if metadata.st_nlink != 1 or sidecar.read_text(encoding="ascii").strip().split() != [digest, path.name]:
            raise RuntimeError("RECOVERED_PROCESS_EVIDENCE_SIDECAR_MISMATCH")
    else:
        write_sha256_bound_file(path, content)
    return digest


def prepare_acceptance_transaction(
    *, signed_event_bundle: Path, output: Path, head: str, nonce_ledger: Path,
) -> dict:
    """Reserve and recover one exact formal operation before starting any process."""
    def required_integer(name: str) -> int:
        try:
            value = int(os.environ[name])
        except (KeyError, ValueError):
            raise RuntimeError(f"{name}_MISSING") from None
        if value <= 0:
            raise RuntimeError(f"{name}_INVALID")
        return value

    evidence_scope = {
        "namespace": os.getenv("R297_EVIDENCE_NAMESPACE", ""),
        "tenant_id": required_integer("R297_EVIDENCE_TENANT_ID"),
        "company_id": required_integer("R297_EVIDENCE_COMPANY_ID"),
        "store_id": required_integer("R297_EVIDENCE_STORE_ID"),
        "platform": os.getenv("R297_EVIDENCE_PLATFORM", "jd"),
        "release_sha": head,
        "run_id": os.getenv("R297_ACCEPTANCE_RUN_ID", ""),
        "run_attempt": required_integer("R297_ACCEPTANCE_RUN_ATTEMPT"),
        "challenge": os.getenv("R297_ACCEPTANCE_CHALLENGE", ""),
    }
    bundle = json.loads(signed_event_bundle.read_text(encoding="utf-8"))
    try:
        page_event = next(
            event for event in bundle.get("events", [])
            if event.get("event_type") == "web_page_close"
        )
        source_workflow_run_id = page_event["payload"]["workflow_run_id"]
    except (KeyError, StopIteration, TypeError):
        raise RuntimeError("R297_SIGNED_EVENT_BUNDLE_INVALID") from None
    transaction_sha256 = hashlib.sha256(json.dumps(
        {"bundle": bundle, "scope": evidence_scope},
        ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode()).hexdigest()
    run_ledger_value = os.getenv("R297_ACCEPTANCE_RUN_LEDGER", "")
    if not run_ledger_value:
        raise RuntimeError("R297_ACCEPTANCE_RUN_LEDGER_MISSING")
    run_ledger = Path(run_ledger_value).resolve()
    reservation_now = datetime.now(timezone.utc)
    reservation = reserve_acceptance_run(
        run_ledger, expected_scope=evidence_scope,
        source_workflow_run_id=source_workflow_run_id,
        transaction_sha256=transaction_sha256,
        event_sha256s=[signed_event_sha256(event) for event in bundle.get("events", [])],
        require_event_receipts=any(
            datetime.fromisoformat(event["observed_at"].replace("Z", "+00:00"))
            < reservation_now - timedelta(minutes=5) for event in bundle.get("events", [])
        ),
        now=reservation_now,
    )
    verified = verify_acceptance_event_bundle(
        bundle, expected_scope=evidence_scope, now=reservation_now,
        nonce_ledger=nonce_ledger, consume_run=False,
        allow_nonce_recovery=reservation == "recovering",
        reserved_transaction_sha256=transaction_sha256,
    )
    evidence = output / "R297_PROCESS_ACCEPTANCE_EVIDENCE.json"
    staged_content = recover_staged_acceptance_output(
        run_ledger, expected_scope=evidence_scope,
        source_workflow_run_id=source_workflow_run_id,
        transaction_sha256=transaction_sha256,
    ) if reservation == "recovering" else None
    published_digest = None
    if staged_content is not None:
        staged_digest = hashlib.sha256(staged_content).hexdigest()
        if evidence.exists():
            published_digest = recover_published_process_evidence(
                evidence, head=head, transaction_sha256=transaction_sha256,
                verified_events=verified,
            )
            if published_digest != staged_digest:
                raise RuntimeError("RECOVERED_PROCESS_EVIDENCE_STAGED_DIGEST_MISMATCH")
        else:
            previous = json.loads(staged_content)
            _validate_process_evidence(
                previous, evidence, verified, head=head,
                transaction_sha256=transaction_sha256,
            )
            published_digest = write_sha256_bound_file(evidence, staged_content)
    if published_digest:
        complete_acceptance_run(
            run_ledger, expected_scope=evidence_scope,
            source_workflow_run_id=source_workflow_run_id,
            transaction_sha256=transaction_sha256, published_path=evidence,
        )
    return {
        "bundle": bundle, "scope": evidence_scope, "source_workflow_run_id": source_workflow_run_id,
        "transaction_sha256": transaction_sha256, "run_ledger": run_ledger,
        "verified": verified, "published_digest": published_digest,
    }
def main() -> int:
    trust_environment = os.getenv("APP_ENV", "").strip().lower()
    if trust_environment == "production":
        raise RuntimeError("R297_CONTROLLED_CANARY_FORBIDDEN_IN_PRODUCTION")
    if trust_environment != "acceptance":
        raise RuntimeError("R297_ACCEPTANCE_ENVIRONMENT_REQUIRED")
    parser = argparse.ArgumentParser()
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("--runtime-image", required=True)
    parser.add_argument("--signed-event-bundle", type=Path, required=True)
    args = parser.parse_args()

    head = run("git", "rev-parse", "HEAD")
    if head != os.environ.get("RELEASE_SOURCE_SHA"):
        raise RuntimeError("RELEASE_SOURCE_SHA_MISMATCH")
    session_namespace = f"r297-acceptance-{head[:12]}"
    output = args.output_directory.resolve()
    ledger_value = os.getenv("R297_EVIDENCE_NONCE_LEDGER", "")
    if not ledger_value:
        raise RuntimeError("R297_EVIDENCE_NONCE_LEDGER_MISSING")
    nonce_ledger = Path(ledger_value).resolve()
    if output in nonce_ledger.parents or nonce_ledger == output:
        raise RuntimeError("R297_EVIDENCE_NONCE_LEDGER_NOT_DURABLE")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Do not overwrite files referenced by an already-published evidence digest.
    # Verified resume must run before canary setup; the current late resume cannot.
    if any(output.iterdir()):
        raise RuntimeError("R297_PROCESS_RECOVERY_REQUIRES_VERIFIED_RESUME")
    acceptance = prepare_acceptance_transaction(
        signed_event_bundle=args.signed_event_bundle, output=output,
        head=head, nonce_ledger=nonce_ledger,
    )
    if acceptance["published_digest"]:
        evidence = output / "R297_PROCESS_ACCEPTANCE_EVIDENCE.json"
        print(f"R297_PROCESS_ACCEPTANCE_EVIDENCE={evidence}")
        print(f"R297_PROCESS_ACCEPTANCE_EVIDENCE_SHA256={acceptance['published_digest']}")
        print("R297_PROCESS_ACCEPTANCE_RECOVERY=PASS")
        return 0
    postgres_name = f"r297-pg-{head[:12]}-{os.getpid()}"
    redis_name = f"r297-redis-{head[:12]}-{os.getpid()}"
    runtime_name = f"r297-runtime-{head[:12]}-{os.getpid()}"
    runtime_volume = f"r297-runtime-archives-{head[:12]}-{os.getpid()}"
    postgres_port, redis_port, backend_port, runtime_port, canary_port = (free_port() for _ in range(5))
    postgres_password = secrets.token_urlsafe(32)
    redis_password = secrets.token_urlsafe(32)
    capture_token, control_token, ticket_key, cookie_key = (secrets.token_urlsafe(48) for _ in range(4))
    master_key = __import__("base64").b64encode(secrets.token_bytes(32)).decode()
    device_token = secrets.token_urlsafe(48)
    temporary = Path(tempfile.mkdtemp(prefix="r297-process-"))
    sensitive_fixture = output / "R297_SENSITIVE_FIXTURE.json"
    sensitive_values = {
        "buyer_name": "canary-" + secrets.token_hex(8),
        "phone": "canary-" + secrets.token_hex(8),
        "address": "canary-" + secrets.token_hex(8),
        "cookie": "canary-" + secrets.token_hex(16),
        "token": "canary-" + secrets.token_hex(16),
        "password": "canary-" + secrets.token_hex(16),
    }
    sensitive_fixture.write_text(json.dumps(sensitive_values, sort_keys=True) + "\n", encoding="utf-8")
    sensitive_fixture.chmod(0o600)
    sensitive_fixture_sha256 = sha256(sensitive_fixture)
    fixture_env = {f"R297_FIXTURE_{key.upper()}": value for key, value in sensitive_values.items()}
    device_private_key = temporary / "device-test-key.pem"
    run("openssl", "genpkey", "-quiet", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(device_private_key))
    modulus = run("openssl", "rsa", "-in", str(device_private_key), "-noout", "-modulus").split("=", 1)[1]
    public_key_n = modulus.lower()
    backend_log = temporary / "backend.log"
    canary_log = temporary / "canary.log"
    worker_logs = [temporary / "worker-1.log", temporary / "worker-2.log", temporary / "worker-restarted.log"]
    container_logs: dict[str, str] = {}
    cleanup_errors: list[str] = []
    processes: list[subprocess.Popen] = []
    commands: list[str] = []
    observations: dict[str, object] = {}

    environment = os.environ.copy()
    environment.update({
        "JD_SESSION_NAMESPACE": session_namespace,
        "DEPLOY_COMMIT": head,
        "APP_ENV": "test",
        "SERVICE_ROLE": "backend",
        "DATABASE_URL": f"postgresql+psycopg2://r297:{postgres_password}@127.0.0.1:{postgres_port}/r297_acceptance",
        "REDIS_URL": f"redis://:{redis_password}@127.0.0.1:{redis_port}/0",
        "JWT_SECRET": secrets.token_urlsafe(64),
        "BOSS_INITIAL_PASSWORD": "R297-" + secrets.token_urlsafe(24),
        "CORS_ALLOWED_ORIGINS": "https://acceptance.invalid",
        "JD_BROWSER_CAPTURE_TOKEN": "",
        "JD_BROWSER_CONTROL_TOKEN": control_token,
        "R297_CONTROLLED_CANARY": "1",
        "JD_BROWSER_RUNTIME_BASE_URL": f"http://127.0.0.1:{runtime_port}/internal/jd-browser",
        "JD_BROWSER_VIEWER_TICKET_SIGNING_KEY": "",
        "JD_BROWSER_VIEWER_COOKIE_SIGNING_KEY": "",
        "JD_SESSION_MASTER_KEY": "",
        "AGENT_RUNTIME_ENABLED": "false",
        "ALPHA_WORKFLOW_ENABLED": "false",
        "PUBLIC_RESEARCH_ENABLED": "false",
        "KNOWLEDGE_CENTER_ENABLED": "false",
        "SKILLS_ENGINE_ENABLED": "false",
        "JD_TASK_VISIBILITY_SECONDS": "5",
        "JD_SCHEDULER_POLL_SECONDS": "1",
        **fixture_env,
    })

    try:
        commands.append("docker run isolated postgres:16")
        docker_env = {**os.environ, "POSTGRES_PASSWORD": postgres_password}
        run(
            "docker", "run", "--detach", "--pull", "never", "--name", postgres_name,
            "--env", "POSTGRES_PASSWORD", "--env", "POSTGRES_USER=r297", "--env", "POSTGRES_DB=r297_acceptance",
            "--publish", f"127.0.0.1:{postgres_port}:5432", "postgres:16", env=docker_env,
        )
        commands.append("docker run isolated redis:7")
        docker_env = {**os.environ, "REDIS_PASSWORD": redis_password}
        run(
            "docker", "run", "--detach", "--pull", "never", "--name", redis_name,
            "--env", "REDIS_PASSWORD", "--publish", f"127.0.0.1:{redis_port}:6379",
            "redis:7", "sh", "-c", 'exec redis-server --appendonly no --requirepass "$REDIS_PASSWORD"', env=docker_env,
        )
        wait_container(postgres_name)
        wait_container(redis_name)
        wait_command("docker", "exec", postgres_name, "pg_isready", "-U", "r297", "-d", "r297_acceptance")

        commands.append("alembic upgrade head against isolated PostgreSQL")
        run(sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head", env=environment)
        os.environ.update({name: environment[name] for name in environment if name.startswith(("DATABASE_", "REDIS_", "SERVICE_ROLE", "JD_", "CORS_", "JWT_", "BOSS_", "AGENT_", "ALPHA_", "PUBLIC_", "KNOWLEDGE_", "SKILLS_"))})
        os.environ["APP_ENV"] = environment["APP_ENV"]
        try:
            from backend.database import SessionLocal, get_redis
            from backend.models import JdAccount, JdDailyMetric, JdSyncLog, JdWorkbenchDevice, JdWorkbenchStoreStatus, JdWorkbenchSyncPolicy, Store, User, UserStoreMembership
            from backend.queue import PROCESSING_METADATA_PREFIX, PROCESSING_QUEUE_NAME, QUEUE_NAME, claim_task, enqueue_task
            from backend.seed import seed_defaults
            from backend.worker import JD_RETRY_BACKOFF_SECONDS, _claim_jd_workbench_task, _finish_jd_workbench_task, run_jd_workbench_scheduler
        finally:
            os.environ["APP_ENV"] = trust_environment

        db = SessionLocal()
        seed_defaults(db)
        db.commit()
        owner = db.query(User).filter(User.username == "boss").one()
        store = Store(
            tenant_id=owner.tenant_id,
            company_id=owner.company_id,
            platform="jd",
            store_code="R297-ACCEPTANCE",
            store_name="R297 controlled acceptance",
            active=True,
        )
        db.add(store)
        db.flush()
        db.add(UserStoreMembership(user_id=owner.id, store_id=store.id, can_read=True, can_write=True, active=True))
        db.add(JdAccount(
            store_id=store.id,
            account_type="jd_smart",
            account_name="R297 controlled canary",
            login_status="ok",
            cookie_status="ok",
            auth_status="active",
            active=True,
        ))
        device = JdWorkbenchDevice(
            device_id="00000000-0000-4000-8000-000000000297", token_hash=hashlib.sha256(device_token.encode()).hexdigest(),
            public_key_n=public_key_n, public_key_e=65537, tenant_id=store.tenant_id,
            company_id=store.company_id, user_id=owner.id, device_name="R297 acceptance",
            client_version="2.97.0", status="ONLINE", expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(device)
        db.flush()
        status_row = JdWorkbenchStoreStatus(device_id=device.device_id, store_id=store.id, status="IDLE", next_sync_at=datetime.now(timezone.utc))
        policy = JdWorkbenchSyncPolicy(tenant_id=store.tenant_id, company_id=store.company_id, store_id=store.id, enabled=False, interval_seconds=300)
        db.add_all([status_row, policy])
        db.commit()
        scope = {"namespace": session_namespace, "tenant_id": store.tenant_id, "company_id": store.company_id, "store_id": store.id, "platform": store.platform}
        if any(scope[field] != acceptance["scope"][field] for field in scope):
            raise RuntimeError("R297_ISOLATED_DATABASE_SCOPE_MISMATCH")
        db.close()

        commands.append("start controlled canary HTTP process")
        canary_root = temporary / "canary"
        canary_root.mkdir()
        (canary_root / "r297-controlled-canary.html").write_text(
            '<!doctype html><html><body><span data-metric="gmv">123.45</span>'
            '<span data-metric="orders">2</span><span data-metric="visitors">3</span>'
            '<span data-metric="profit_amount">10.00</span><span data-metric="ad_spend">5.00</span>'
            '<span data-metric="roi">2.00</span><span data-metric="refunds_count">0</span>'
            '<span data-metric="after_sales_count">0</span><span data-metric="favorites_count">1</span>'
            '<span data-metric="cart_add_count">1</span><span data-metric="conversion_rate">0.50</span></body></html>',
            encoding="utf-8",
        )
        canary_handle = canary_log.open("ab", buffering=0)
        canary = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(canary_port), "--bind", "0.0.0.0", "--directory", str(canary_root)],
            cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=canary_handle, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        canary._r297_log_handle = canary_handle  # type: ignore[attr-defined]
        processes.append(canary)
        deadline = time.monotonic() + 15
        while True:
            try:
                with urlopen(f"http://127.0.0.1:{canary_port}/r297-controlled-canary.html", timeout=2) as response:
                    if response.status == 200:
                        break
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("CONTROLLED_CANARY_NOT_READY")
            time.sleep(0.1)

        commands.append("start real backend process")
        backend_env = {**environment, "SERVICE_ROLE": "backend"}
        if sys.platform.startswith("linux"):
            backend_host = run(
                "docker", "network", "inspect", "bridge", "--format", "{{(index .IPAM.Config 0).Gateway}}"
            )
            runtime_backend_host = "host.docker.internal"
        else:
            backend_host = "127.0.0.1"
            runtime_backend_host = "host.docker.internal"
        backend_handle = backend_log.open("ab", buffering=0)
        backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", backend_host, "--port", str(backend_port)],
            cwd=ROOT, env=backend_env, stdin=subprocess.DEVNULL, stdout=backend_handle, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        backend._r297_log_handle = backend_handle  # type: ignore[attr-defined]
        processes.append(backend)
        wait_http(f"http://{backend_host}:{backend_port}/ready")
        login = post_json(
            f"http://{backend_host}:{backend_port}/api/login",
            {"username": "boss", "password": environment["BOSS_INITIAL_PASSWORD"]},
            {},
        )
        owner_headers = {"authorization": f"Bearer {login['token']}"}

        commands.append("start real browser runtime container and Chromium")
        runtime_env = {
            **os.environ,
            **fixture_env,
            "JD_SESSION_NAMESPACE": session_namespace,
            "APP_ENV": "acceptance",
            "JD_BROWSER_CAPTURE_TOKEN": capture_token,
            "JD_BROWSER_CONTROL_TOKEN": control_token,
            "JD_BROWSER_VIEWER_TICKET_SIGNING_KEY": ticket_key,
            "JD_BROWSER_VIEWER_COOKIE_SIGNING_KEY": cookie_key,
            "JD_SESSION_MASTER_KEY": master_key,
            "R297_CONTROLLED_CANARY": "1",
            "R297_CONTROLLED_CANARY_DASHBOARD_URL": f"http://host.docker.internal:{canary_port}/r297-controlled-canary.html",
        }
        run(
            "docker", "run", "--detach", "--name", runtime_name,
            "--add-host", "host.docker.internal:host-gateway", "--publish", f"127.0.0.1:{runtime_port}:8787",
            "--cap-drop", "ALL", "--cap-add", "SYS_CHROOT", "--read-only",
            "--security-opt", "no-new-privileges:true",
            "--security-opt", "seccomp=services/jd-cloud-browser-runtime/seccomp_profile.json",
            "--shm-size", "1g",
            "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=512m,uid=10001,gid=10001,mode=1777",
            "--tmpfs", "/tmp/.X11-unix:rw,nosuid,nodev,noexec,size=1m,uid=0,gid=0,mode=1777",
            "--mount", f"type=volume,source={runtime_volume},target=/data/jd-session-archives",
            "--env", "JD_SESSION_NAMESPACE", "--env", "APP_ENV",
            "--env", "JD_BROWSER_CAPTURE_TOKEN", "--env", "JD_BROWSER_CONTROL_TOKEN",
            "--env", "JD_BROWSER_VIEWER_TICKET_SIGNING_KEY", "--env", "JD_BROWSER_VIEWER_COOKIE_SIGNING_KEY",
            "--env", "JD_SESSION_MASTER_KEY", "--env", "R297_CONTROLLED_CANARY", "--env", "R297_CONTROLLED_CANARY_DASHBOARD_URL",
            *(item for name in sorted(fixture_env) for item in ("--env", name)),
            "--env", "RUNTIME_API_PORT=8788", "--env", "DISPLAY=:99", "--env", "JD_PROFILE_ROOT=/tmp/jd-cloud-profiles",
            "--env", "JD_SESSION_ARCHIVE_ROOT=/data/jd-session-archives",
            "--env", f"JD_BROWSER_SESSION_AUTH_URL=http://{runtime_backend_host}:{backend_port}/api/jd-workbench/internal/browser-session-authorize",
            args.runtime_image,
            env=runtime_env,
        )
        wait_http(f"http://127.0.0.1:{runtime_port}/internal/jd-browser/health", {"x-internal-token": control_token})
        session = post_json(
            f"http://{backend_host}:{backend_port}/api/jd-workbench/stores/{store.id}/login-session",
            {}, owner_headers,
        )
        capture_probe = post_json(
            f"http://127.0.0.1:{runtime_port}/internal/jd-browser/capture",
            {"scope": scope, "dataset": "metrics"},
            {"x-internal-token": capture_token},
        )
        if capture_probe.get("status") != "OK":
            raise RuntimeError(f"CONTROLLED_CAPTURE_PREFLIGHT_FAILED:{capture_probe.get('status')}")
        chromium_pid = int(run("docker", "exec", runtime_name, "pgrep", "-x", "chrome").splitlines()[0])

        commands.append("start two independent worker processes")
        worker_env = {
            **environment,
            "SERVICE_ROLE": "worker",
            "JWT_SECRET": "",
            "BOSS_INITIAL_PASSWORD": "",
            "JD_BROWSER_CONTROL_TOKEN": "",
            "JD_BROWSER_CAPTURE_TOKEN": capture_token,
            "JD_BROWSER_CAPTURE_BASE_URL": f"http://127.0.0.1:{runtime_port}/internal/jd-browser",
        }
        workers = [start_python("backend.worker", worker_env, worker_logs[index]) for index in range(2)]
        processes.extend(workers)
        if workers[0].pid == workers[1].pid:
            raise RuntimeError("WORKER_PIDS_NOT_DISTINCT")
        redis_client = get_redis()

        schedule_cursor = datetime.now(timezone.utc)

        def schedule_store_task() -> dict:
            nonlocal schedule_cursor
            due_at = schedule_cursor
            schedule_cursor += timedelta(seconds=300)
            db = SessionLocal()
            policy = db.query(JdWorkbenchSyncPolicy).one()
            status_row = db.query(JdWorkbenchStoreStatus).one()
            policy.enabled = True
            status_row.status = "IDLE"
            status_row.reason_code = None
            status_row.next_sync_at = due_at
            db.commit()
            db.close()
            if run_jd_workbench_scheduler(due_at) != 1:
                raise RuntimeError("STORE_TASK_NOT_SCHEDULED")
            db = SessionLocal()
            policy = db.query(JdWorkbenchSyncPolicy).one()
            task_id = policy.active_task_id
            policy.enabled = False
            db.commit()
            db.close()
            if not task_id:
                raise RuntimeError("STORE_TASK_ID_MISSING")
            return {"task_id": task_id}

        def wait_sync_log(task_id: str, expected_status: str = "success", timeout: float = 30) -> dict:
            deadline = time.monotonic() + timeout
            last_status = None
            while time.monotonic() < deadline:
                db = SessionLocal()
                row = db.query(JdSyncLog).filter(JdSyncLog.task_id == task_id).one_or_none()
                policy = db.query(JdWorkbenchSyncPolicy).one()
                last_status = row.status if row else None
                result = (
                    {"status": row.status}
                    if row and row.status == expected_status and policy.active_task_id is None
                    else None
                )
                db.close()
                if result:
                    return result
                if last_status == "failed":
                    raise RuntimeError(f"SYNC_TASK_FAILED:{task_id}")
                time.sleep(0.1)
            raise RuntimeError(f"SYNC_LOG_TIMEOUT:{task_id}:{expected_status}:{last_status}")

        commands.append("race two independent workers for one PostgreSQL-claimed store-window task")
        dual_task = schedule_store_task()
        dual_result = wait_sync_log(dual_task["task_id"])
        db = SessionLocal()
        dual_log_count = db.query(JdSyncLog).filter(JdSyncLog.task_id == dual_task["task_id"]).count()
        db.close()
        claim_lines = sum(path.read_text(errors="replace").count(f"worker_task_claimed task_id={dual_task['task_id']}") for path in worker_logs[:2])
        if dual_log_count != 1 or claim_lines != 1:
            raise RuntimeError(f"DUAL_WORKER_CLAIM_INVALID:{dual_log_count}:{claim_lines}")

        commands.append("execute two PostgreSQL-claimed store scheduling cycles")
        cycle_tasks = []
        cycle_results = []
        for _ in range(2):
            item = schedule_store_task()
            cycle_tasks.append(item)
            cycle_results.append(wait_sync_log(item["task_id"]))
        db = SessionLocal()
        cycle_log_counts = [db.query(JdSyncLog).filter(JdSyncLog.task_id == item["task_id"]).count() for item in cycle_tasks]
        metrics = db.query(JdDailyMetric).filter(JdDailyMetric.store_id == store.id).all()
        metric_snapshot = [
            {"id": row.id, "gmv": str(row.gmv), "orders": row.paid_orders_count, "visitors": row.visitors_count}
            for row in metrics
        ]
        db.close()
        if cycle_log_counts != [1, 1]:
            raise RuntimeError(f"CYCLE_LOG_COUNTS_INVALID:{cycle_log_counts}")
        if len(metric_snapshot) != 1 or metric_snapshot[0]["gmv"] != "123.45" or metric_snapshot[0]["orders"] != 2:
            raise RuntimeError(f"IDEMPOTENT_METRIC_INVALID:{metric_snapshot}")

        commands.append("kill claimed worker and recover expired processing task")
        for worker in workers:
            stop_process(worker)
        orphan = schedule_store_task()
        lock_connection = __import__("psycopg2").connect(environment["DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://"))
        lock_cursor = lock_connection.cursor()
        # Let the real worker claim first, then block only its business commit.
        lock_cursor.execute("LOCK TABLE jd_daily_metrics IN ACCESS EXCLUSIVE MODE")
        orphan_worker = start_python("backend.worker", worker_env, worker_logs[2])
        processes.append(orphan_worker)
        claimed_by = None
        for _ in range(100):
            metadata_keys = list(redis_client.scan_iter(f"{PROCESSING_METADATA_PREFIX}{orphan['task_id']}:*"))
            metadata = redis_client.hgetall(metadata_keys[0]) if len(metadata_keys) == 1 else {}
            if metadata:
                claimed_by = metadata["claimed_by"]
                break
            time.sleep(0.05)
        if not claimed_by:
            raise RuntimeError("ORPHAN_PROCESSING_NOT_OBSERVED")
        claimed_pid = int(claimed_by.rsplit(":", 1)[1])
        if orphan_worker.pid != claimed_pid:
            raise RuntimeError("CLAIMED_WORKER_PID_NOT_FOUND")
        killed = orphan_worker
        os.killpg(killed.pid, signal.SIGKILL)
        killed.wait(timeout=5)
        lock_connection.rollback()
        lock_cursor.close()
        lock_connection.close()
        replacement = start_python("backend.worker", worker_env, worker_logs[2])
        processes.append(replacement)
        orphan_result = wait_sync_log(orphan["task_id"], timeout=30)
        db = SessionLocal()
        orphan_log_count = db.query(JdSyncLog).filter(JdSyncLog.task_id == orphan["task_id"]).count()
        db.close()
        if orphan_log_count != 1:
            raise RuntimeError(f"ORPHAN_LOG_COUNT_INVALID:{orphan_log_count}")

        commands.append("verify human-action resume and exact retry schedule")
        # State-transition checks must not race the already-observed worker pair.
        for worker in workers:
            stop_process(worker)
        stop_process(replacement)
        db = SessionLocal()
        policy = db.query(JdWorkbenchSyncPolicy).one()
        status_row = db.query(JdWorkbenchStoreStatus).one()
        device = db.query(JdWorkbenchDevice).one()
        store = db.get(Store, status_row.store_id)
        status_row.status = "HUMAN_ACTION_REQUIRED"
        status_row.reason_code = "RISK_CONTROL"
        status_row.retry_count = 4
        status_row.next_sync_at = datetime.now(timezone.utc) + timedelta(hours=1)
        policy.active_task_id = "00000000-0000-4000-8000-000000000999"
        policy.queue_state = "ready"
        resumed_at = datetime.now(timezone.utc)
        policy.enabled = True
        db.commit()
        db.close()
        stale_worker_id = f"acceptance-stale-{os.getpid()}"
        enqueue_task("sync_jd_smart", {
            "tenant_id": scope["tenant_id"], "company_id": scope["company_id"],
            "store_id": scope["store_id"], "source": "cloud_scheduler",
        }, task_id="00000000-0000-4000-8000-000000000999")
        stale_manual_task = claim_task(stale_worker_id, timeout=0)
        if (
            stale_manual_task is None
            or stale_manual_task["task_id"] != "00000000-0000-4000-8000-000000000999"
            or _claim_jd_workbench_task(stale_manual_task, stale_worker_id, datetime.now(timezone.utc)) != "claimed"
        ):
            raise RuntimeError("HUMAN_ACTION_STALE_CLAIM_NOT_OBSERVED")
        heartbeat_path = "/api/jd-workbench/heartbeat"
        human_report = device_post(
            f"http://{backend_host}:{backend_port}{heartbeat_path}", heartbeat_path,
            {"client_version": "2.97.0", "status": "HUMAN_ACTION_REQUIRED", "store_id": scope["store_id"], "reason_code": "RISK_CONTROL"},
            device_token, device_private_key,
        )
        try:
            device_post(
                f"http://{backend_host}:{backend_port}{heartbeat_path}", heartbeat_path,
                {"client_version": "2.97.0", "status": "IDLE", "store_id": scope["store_id"]},
                device_token, device_private_key,
            )
            raise RuntimeError("HUMAN_ACTION_PRE_PROBE_IDLE_ACCEPTED")
        except HTTPError as exc:
            if exc.code != 409:
                raise
        # Prove JD recovery through the real Backend -> Runtime -> collector path
        # while the store is still blocked. The device is not allowed to clear
        # the human-action state merely by reporting IDLE.
        recovery_probe_at = schedule_cursor
        schedule_cursor += timedelta(seconds=300)
        recovery_probe_task_id = "00000000-0000-4000-8000-000000000998"
        db = SessionLocal()
        policy = db.query(JdWorkbenchSyncPolicy).one()
        policy.active_task_id = recovery_probe_task_id
        policy.queue_state = "ready"
        policy.sync_window_started_at = recovery_probe_at
        policy.visibility_deadline = recovery_probe_at + timedelta(seconds=5)
        db.commit()
        db.close()
        enqueue_task(
            "sync_jd_smart",
            {
                "tenant_id": scope["tenant_id"], "company_id": scope["company_id"],
                "store_id": scope["store_id"], "source": "cloud_scheduler",
                "scheduled_at": recovery_probe_at.isoformat(),
                "sync_window_started_at": recovery_probe_at.isoformat(),
            },
            max_retries=5, task_id=recovery_probe_task_id, attempt=0,
        )
        recovery_probe_worker = start_python("backend.worker", worker_env, worker_logs[2])
        processes.append(recovery_probe_worker)
        recovery_probe_result = wait_sync_log(recovery_probe_task_id, timeout=30)
        stop_process(recovery_probe_worker)
        if recovery_probe_result.get("status") != "success":
            raise RuntimeError("HUMAN_ACTION_RECOVERY_PROBE_FAILED")
        db = SessionLocal()
        probe_generation = db.query(JdWorkbenchSyncPolicy).one().claim_generation
        db.close()
        resume_report = device_post(
            f"http://{backend_host}:{backend_port}{heartbeat_path}", heartbeat_path,
            {"client_version": "2.97.0", "status": "IDLE", "store_id": scope["store_id"]},
            device_token, device_private_key,
        )
        if human_report.get("status") != "HUMAN_ACTION_REQUIRED" or resume_report.get("status") != "IDLE":
            raise RuntimeError("HUMAN_ACTION_API_TRANSITION_FAILED")
        db = SessionLocal()
        policy = db.query(JdWorkbenchSyncPolicy).one()
        status_row = db.query(JdWorkbenchStoreStatus).one()
        db.refresh(status_row)
        manual_after = {"status": status_row.status, "reason_code": status_row.reason_code, "retry_count": status_row.retry_count, "next_sync_at": status_row.next_sync_at.isoformat(), "active_task_id": policy.active_task_id}
        resumed_generation = policy.claim_generation
        db.close()
        manual_fencing = observe_stale_manual_claim(
            stale_manual_task, stale_worker_id,
            probe_generation=probe_generation, resumed_generation=resumed_generation,
        )
        scheduled = run_jd_workbench_scheduler(schedule_cursor)
        schedule_cursor += timedelta(seconds=300)
        if scheduled != 1:
            raise RuntimeError(f"MANUAL_RESUME_NOT_AUTO_QUEUED:{scheduled}")
        db = SessionLocal()
        manual_task_id = db.query(JdWorkbenchSyncPolicy).one().active_task_id
        db.close()
        if not manual_task_id:
            raise RuntimeError("MANUAL_RESUME_TASK_ID_MISSING")
        resume_worker = start_python("backend.worker", worker_env, worker_logs[2])
        processes.append(resume_worker)
        manual_task_result = wait_sync_log(manual_task_id, timeout=30)
        stop_process(resume_worker)

        observed_backoff = []
        for index, delay in enumerate(JD_RETRY_BACKOFF_SECONDS):
            now = datetime.now(timezone.utc)
            db = SessionLocal()
            policy = db.query(JdWorkbenchSyncPolicy).one()
            status_row = db.query(JdWorkbenchStoreStatus).one()
            task_id = f"00000000-0000-4000-8000-{index:012d}"
            policy.active_task_id = task_id
            policy.queue_state = "processing"
            policy.lease_worker_id = "acceptance-backoff"
            policy.claim_generation = -1
            db.commit()
            db.close()
            _finish_jd_workbench_task({"task_id": task_id, "task_type": "sync_jd_smart", "attempt": index, "payload": {"source": "cloud_scheduler", "tenant_id": scope["tenant_id"], "company_id": scope["company_id"], "store_id": scope["store_id"]}}, "acceptance-backoff", success=False, now=now)
            db = SessionLocal()
            status_row = db.query(JdWorkbenchStoreStatus).one()
            deadline = status_row.next_sync_at
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            observed_backoff.append(round((deadline - now).total_seconds()))
            db.close()
        if tuple(observed_backoff) != JD_RETRY_BACKOFF_SECONDS:
            raise RuntimeError(f"RETRY_SCHEDULE_MISMATCH:{observed_backoff}")

        commands.append("restart worker, runtime and backend")
        worker_pid_before = resume_worker.pid
        restarted_worker = start_python("backend.worker", worker_env, worker_logs[2])
        processes.append(restarted_worker)
        runtime_pid_before = int(run("docker", "inspect", "--format", "{{.State.Pid}}", runtime_name))
        run("docker", "restart", runtime_name)
        wait_http(f"http://127.0.0.1:{runtime_port}/internal/jd-browser/health", {"x-internal-token": control_token})
        runtime_pid_after = int(run("docker", "inspect", "--format", "{{.State.Pid}}", runtime_name))
        restored_session = post_json(
            f"http://{backend_host}:{backend_port}/api/jd-workbench/stores/{scope['store_id']}/login-session",
            {}, owner_headers,
        )
        backend_pid_before = backend.pid
        stop_process(backend)
        restarted_backend_handle = backend_log.open("ab", buffering=0)
        restarted_backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", backend_host, "--port", str(backend_port)],
            cwd=ROOT, env=backend_env, stdin=subprocess.DEVNULL, stdout=restarted_backend_handle, stderr=subprocess.STDOUT, start_new_session=True,
        )
        restarted_backend._r297_log_handle = restarted_backend_handle  # type: ignore[attr-defined]
        processes.append(restarted_backend)
        wait_http(f"http://{backend_host}:{backend_port}/ready")

        postgres_id = run("docker", "inspect", "--format", "{{.Id}}", postgres_name)
        redis_id = run("docker", "inspect", "--format", "{{.Id}}", redis_name)
        runtime_id = run("docker", "inspect", "--format", "{{.Id}}", runtime_name)
        queue_residue = {
            "ready_count": redis_client.llen(QUEUE_NAME),
            "processing_count": redis_client.llen(PROCESSING_QUEUE_NAME),
            "metadata_count": len(list(redis_client.scan_iter(f"{PROCESSING_METADATA_PREFIX}*"))),
        }
        if any(queue_residue.values()):
            raise RuntimeError(f"QUEUE_ACK_RESIDUE:{queue_residue}")
        observations = {
            "commit": head,
            "mode": "real_process",
            "mock_count": 0,
            "controlled_canary": True,
            "data_source": "CONTROLLED_CANARY",
            "real_jd_acceptance": False,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "containers": {"postgres": postgres_id, "redis": redis_id, "runtime": runtime_id},
            "processes": {
                "backend_pid_before": backend_pid_before,
                "backend_pid_after": restarted_backend.pid,
                "worker_pids": [workers[0].pid, workers[1].pid],
                "worker_restart_pid": restarted_worker.pid,
                "runtime_pid_before": runtime_pid_before,
                "runtime_pid_after": runtime_pid_after,
                "chromium_pid": chromium_pid,
                "web_process_count": 0,
                "electron_process_count": 0,
            },
            "two_cycle": [{"task_id": task["task_id"], "status": result["status"], "database_log_count": count} for task, result, count in zip(cycle_tasks, cycle_results, cycle_log_counts)],
            "idempotent_write": {"metric_row_count": len(metric_snapshot), "rows": metric_snapshot},
            "multi_worker": {
                "task_id": dual_task["task_id"],
                "status": dual_result["status"],
                "worker_pids": [workers[0].pid, workers[1].pid],
                "distinct_worker_pids": len({workers[0].pid, workers[1].pid}) == 2,
                "claim_log_count": claim_lines,
                "database_log_count": dual_log_count,
                "postgresql_store_claim_count": claim_lines,
                "same_store_claim_count": 1 if claim_lines == 1 and dual_log_count == 1 else 0,
            },
            "orphan_recovery": {"task_id": orphan["task_id"], "processing_observed": True, "killed_worker_pid": killed.pid, "final_status": orphan_result["status"], "database_log_count": orphan_log_count},
            "explicit_ack": queue_residue,
            "worker_restart": {"pid_before": worker_pid_before, "pid_after": restarted_worker.pid, "recovered": worker_pid_before != restarted_worker.pid},
            "service_restart": {
                "runtime_pid_before": runtime_pid_before,
                "runtime_pid_after": runtime_pid_after,
                "runtime_session_restored": bool(restored_session.get("restored")),
                "backend_pid_before": backend_pid_before,
                "backend_pid_after": restarted_backend.pid,
            },
            "runtime_restart": {
                "pid_before": runtime_pid_before,
                "pid_after": runtime_pid_after,
                "session_restored": bool(restored_session.get("restored")),
            },
            "manual_resume": {
                **manual_fencing,
                "before_status": "HUMAN_ACTION_REQUIRED", "after": manual_after,
                "recovery_probe_task_id": recovery_probe_task_id,
                "recovery_probe_status": recovery_probe_result["status"],
                "automatic_enqueue_count": scheduled, "task_id": manual_task_id,
                "task_status": manual_task_result["status"],
            },
            "human_action_detection": {"detected_status": "HUMAN_ACTION_REQUIRED", "automatic_resume_status": manual_task_result["status"]},
            "retry_schedule": {"expected_seconds": list(JD_RETRY_BACKOFF_SECONDS), "observed_seconds": observed_backoff},
            "source_code_write_count": 0,
            "production_connection_count": 0,
        }
    finally:
        for process in reversed(processes):
            try:
                stop_process(process)
                if process.poll() is None:
                    cleanup_errors.append(f"process:{process.pid}:still-running")
            except Exception as exc:
                cleanup_errors.append(f"process:{process.pid}:{type(exc).__name__}")
        for name in (runtime_name, redis_name, postgres_name):
            stop_result = subprocess.run(
                ["docker", "stop", name], cwd=ROOT, text=True,
                capture_output=True, check=False,
            )
            if stop_result.returncode:
                cleanup_errors.append(f"container:{name}:stop:{stop_result.returncode}")
            with contextlib.suppress(Exception):
                result = subprocess.run(
                    ["docker", "logs", name], cwd=ROOT, text=True,
                    capture_output=True, check=False,
                )
                if result.returncode == 0:
                    container_logs[name] = result.stdout + result.stderr
            with contextlib.suppress(Exception):
                run("docker", "rm", name)
        with contextlib.suppress(Exception):
            run("docker", "volume", "rm", runtime_volume)

    evidence_scope = acceptance["scope"]
    source_workflow_run_id = acceptance["source_workflow_run_id"]
    transaction_sha256 = acceptance["transaction_sha256"]
    run_ledger = acceptance["run_ledger"]
    observations.update(acceptance["verified"])
    observations["acceptance_transaction_sha256"] = transaction_sha256
    evidence = output / "R297_PROCESS_ACCEPTANCE_EVIDENCE.json"
    sidecar = evidence.with_suffix(evidence.suffix + ".sha256")
    raw_log = output / "R297_PROCESS_ACCEPTANCE_RAW.jsonl"
    expected_container_logs = {runtime_name, redis_name, postgres_name}
    if observations and (cleanup_errors or set(container_logs) != expected_container_logs):
        missing = sorted(expected_container_logs - set(container_logs))
        details = cleanup_errors + [f"missing-log:{name}" for name in missing]
        raise RuntimeError(f"PROCESS_CLEANUP_OR_LOG_CAPTURE_INCOMPLETE:{','.join(details)}")
    with raw_log.open("w", encoding="utf-8") as handle:
        for command in commands:
            handle.write(json.dumps({"event": "command", "command": command}, sort_keys=True) + "\n")
        handle.write(json.dumps({
            "event": "sensitive_fixture_injected",
            "fixture_sha256": sensitive_fixture_sha256,
            "fields": sorted(sensitive_values),
        }, sort_keys=True) + "\n")
        for key, value in observations.items():
            handle.write(json.dumps({"event": "gate_result", "gate": key, "result": value}, ensure_ascii=False, sort_keys=True) + "\n")
    observations["exact_commands"] = commands
    observations["raw_log_path"] = str(raw_log)
    observations["raw_log_sha256"] = sha256(raw_log)
    observations["sensitive_fixture_path"] = str(sensitive_fixture)
    observations["sensitive_fixture_sha256"] = sensitive_fixture_sha256
    serialized = json.dumps(observations, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    process_logs = "\n".join(container_logs.values()) + "\n" + "\n".join(
        path.read_text(errors="replace")
        for path in (backend_log, canary_log, *worker_logs)
        if path.exists()
    )
    scanned_text = serialized + "\n" + process_logs
    secrets_found = sum(scanned_text.count(value) for value in (postgres_password, redis_password, capture_token, control_token, ticket_key, cookie_key, master_key, *sensitive_values.values()))
    if secrets_found or re.search(r"(?i)(?:authorization|cookie|password|token)\s*[=:]\s*\S+", scanned_text):
        raise RuntimeError("SENSITIVE_VALUE_CAPTURED")
    observations["secret_exposure_count"] = 0
    verify_acceptance_event_bundle(
        acceptance["bundle"], expected_scope=evidence_scope,
        now=datetime.now(timezone.utc), nonce_ledger=nonce_ledger,
        consume_run=False, allow_nonce_recovery=True,
        reserved_transaction_sha256=transaction_sha256,
    )
    evidence_content = (json.dumps(observations, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    _validate_process_evidence(
        observations, evidence, acceptance["verified"], head=head,
        transaction_sha256=transaction_sha256,
    )
    stage_acceptance_output(
        run_ledger, expected_scope=evidence_scope,
        source_workflow_run_id=source_workflow_run_id,
        transaction_sha256=transaction_sha256, content=evidence_content,
    )
    digest = write_sha256_bound_file(evidence, evidence_content)
    for path in (sensitive_fixture, raw_log, evidence, sidecar):
        path.chmod(0o600)
    complete_acceptance_run(
        run_ledger, expected_scope=evidence_scope,
        source_workflow_run_id=source_workflow_run_id,
        transaction_sha256=transaction_sha256, published_path=evidence,
    )
    print(f"R297_PROCESS_ACCEPTANCE_EVIDENCE={evidence}")
    print(f"R297_PROCESS_ACCEPTANCE_EVIDENCE_SHA256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
