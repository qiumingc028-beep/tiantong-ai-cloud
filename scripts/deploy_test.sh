#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON_BIN="${TEST_PYTHON:-/Users/chenqiuming/.openclaw/runtimes/tiantong-test-r1/bin/python}"
PROJECT_LABEL="tiantong-v2-usable-v1-s1-taskcenter-ownership-idor-r70"

fail() {
  echo "test deployment refused: $1" >&2
  exit 2
}

required() {
  local name="$1"
  [ -n "${!name:-}" ] || fail "${name} is required"
}

loopback() {
  [ "$1" = "127.0.0.1" ] || [ "$1" = "localhost" ]
}

container_port() {
  local name="$1" internal_port="$2" expected_port="$3" service="$4"
  [ "$(docker inspect -f '{{index .Config.Labels "tiantong.qa.task"}}' "${name}")" = "R70" ] || fail "${service} is not the R70 test runtime"
  [ "$(docker inspect -f '{{index .Config.Labels "tiantong.qa.project"}}' "${name}")" = "${PROJECT_LABEL}" ] || fail "${service} project label mismatch"
  [ "$(docker port "${name}" "${internal_port}/tcp")" = "127.0.0.1:${expected_port}" ] || fail "${service} loopback port mismatch"
}

[ "${TIANTONG_ENV:-}" = "test" ] || fail "TIANTONG_ENV must equal test"
case "${APP_ENV:-test}" in
  production|prod) fail "production environments are forbidden" ;;
esac

required EXPECTED_COMMIT_SHA
required TEST_RUNTIME_ID
required TEST_DATABASE_NAME
required TEST_POSTGRES_CONTAINER
required TEST_POSTGRES_HOST
required TEST_POSTGRES_PORT
required TEST_POSTGRES_USER
required TEST_POSTGRES_PASSWORD
required TEST_REDIS_CONTAINER
required TEST_REDIS_HOST
required TEST_REDIS_PORT

[[ "${TEST_RUNTIME_ID}" =~ ^[A-Za-z0-9._-]+$ ]] || fail "invalid TEST_RUNTIME_ID"
[[ "${TEST_DATABASE_NAME}" =~ ^tiantong_v2_test_[a-z0-9_]+$ ]] || fail "TEST_DATABASE_NAME must use the tiantong_v2_test_ prefix"
loopback "${TEST_POSTGRES_HOST}" || fail "PostgreSQL must be loopback"
loopback "${TEST_REDIS_HOST}" || fail "Redis must be loopback"

TEST_POSTGRES_ADMIN_DB="${TEST_POSTGRES_ADMIN_DB:-postgres}"
TEST_REDIS_DB="${TEST_REDIS_DB:-0}"
TEST_BACKEND_HOST="${TEST_BACKEND_HOST:-127.0.0.1}"
TEST_BACKEND_PORT="${TEST_BACKEND_PORT:-59200}"
[ "${TEST_BACKEND_HOST}" = "127.0.0.1" ] || fail "backend must bind 127.0.0.1"
[[ "${TEST_BACKEND_PORT}" =~ ^[0-9]+$ ]] || fail "invalid backend port"
[ "${TEST_BACKEND_PORT}" -ge 1024 ] && [ "${TEST_BACKEND_PORT}" -le 65535 ] || fail "backend port out of range"
[ "${PYTHON_BIN#/}" != "${PYTHON_BIN}" ] && [[ "${PYTHON_BIN}" != *$'\n'* ]] || fail "TEST_PYTHON must be an absolute single-line path"
[ -x "${PYTHON_BIN}" ] || fail "test Python runtime is unavailable"

head_sha="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
[ "${head_sha}" = "${EXPECTED_COMMIT_SHA}" ] || fail "commit mismatch"
[ -z "$(git -C "${ROOT_DIR}" status --porcelain=v1)" ] || fail "git worktree must be clean"

container_port "${TEST_POSTGRES_CONTAINER}" 5432 "${TEST_POSTGRES_PORT}" PostgreSQL
container_port "${TEST_REDIS_CONTAINER}" 6379 "${TEST_REDIS_PORT}" Redis

runtime_dir="/tmp/tiantong-test-deploy-${TEST_RUNTIME_ID}"
pid_file="${runtime_dir}/backend.pid"
metadata_file="${runtime_dir}/backend.env"
log_file="${runtime_dir}/backend.log"
asset_root="${runtime_dir}/assets"
expected_command_tail="-m uvicorn backend.main:app --host ${TEST_BACKEND_HOST} --port ${TEST_BACKEND_PORT} --log-config backend/uvicorn_log_config.json"
mkdir -p "${runtime_dir}" "${asset_root}"
chmod 700 "${runtime_dir}" "${asset_root}"
umask 077

if [ -f "${pid_file}" ]; then
  existing_pid="$(sed -n '1p' "${pid_file}")"
  if [[ "${existing_pid}" =~ ^[0-9]+$ ]] && kill -0 "${existing_pid}" 2>/dev/null; then
    [ -f "${metadata_file}" ] || fail "running PID has no deployment metadata"
    [ "$(sed -n 's/^STATE=//p' "${metadata_file}")" = RUNNING ] || fail "running deployment state mismatch"
    [ "$(sed -n 's/^PID=//p' "${metadata_file}")" = "${existing_pid}" ] || fail "running deployment PID mismatch"
    [ "$(sed -n 's/^COMMIT_SHA=//p' "${metadata_file}")" = "${EXPECTED_COMMIT_SHA}" ] || fail "running deployment commit mismatch"
    [ "$(sed -n 's/^WORKTREE=//p' "${metadata_file}")" = "${ROOT_DIR}" ] || fail "running deployment worktree mismatch"
    [ "$(sed -n 's/^PORT=//p' "${metadata_file}")" = "${TEST_BACKEND_PORT}" ] || fail "running deployment port mismatch"
    command_line="$(ps -ww -p "${existing_pid}" -o command=)"
    process_executable="${command_line%% *}"
    [ "${command_line#"${process_executable} "}" = "${expected_command_tail}" ] || fail "running PID command arguments mismatch"
    [ "$(sed -n 's/^PROCESS_EXECUTABLE=//p' "${metadata_file}")" = "${process_executable}" ] || fail "running PID executable mismatch"
    command_sha="$(printf '%s' "${command_line}" | shasum -a 256 | awk '{print $1}')"
    [ "$(sed -n 's/^PROCESS_COMMAND_SHA256=//p' "${metadata_file}")" = "${command_sha}" ] || fail "running PID command identity mismatch"
    current_start="$(ps -p "${existing_pid}" -o lstart= | awk '{$1=$1; print}')"
    [ "$(sed -n 's/^PROCESS_START=//p' "${metadata_file}")" = "${current_start}" ] || fail "running PID start time mismatch"
    process_cwd="$(lsof -a -p "${existing_pid}" -d cwd -Fn | sed -n 's/^n//p')"
    [ "${process_cwd}" = "${ROOT_DIR}" ] || fail "running PID worktree mismatch"
    listener_pid="$(lsof -nP -iTCP:"${TEST_BACKEND_PORT}" -sTCP:LISTEN -t | sort -u)"
    [ "${listener_pid}" = "${existing_pid}" ] || fail "running PID does not exclusively own the test port"
    curl -fsS -m 3 "http://${TEST_BACKEND_HOST}:${TEST_BACKEND_PORT}/api/ready" >/dev/null || fail "running test backend is not ready"
    echo "TEST_DEPLOYMENT_STATUS=ALREADY_RUNNING"
    echo "TEST_BACKEND_PID=${existing_pid}"
    echo "TEST_BASE_URL=http://${TEST_BACKEND_HOST}:${TEST_BACKEND_PORT}"
    exit 0
  fi
  rm -f "${pid_file}" "${metadata_file}"
fi

"${PYTHON_BIN}" -c 'import alembic, psycopg2, redis, uvicorn' || fail "test runtime dependencies are incomplete"

database_created="$({
  TEST_DATABASE_NAME="${TEST_DATABASE_NAME}" \
  TEST_POSTGRES_HOST="${TEST_POSTGRES_HOST}" \
  TEST_POSTGRES_PORT="${TEST_POSTGRES_PORT}" \
  TEST_POSTGRES_USER="${TEST_POSTGRES_USER}" \
  TEST_POSTGRES_PASSWORD="${TEST_POSTGRES_PASSWORD}" \
  TEST_POSTGRES_ADMIN_DB="${TEST_POSTGRES_ADMIN_DB}" \
  "${PYTHON_BIN}" - <<'PY'
import os
import psycopg2
from psycopg2 import sql

connection = psycopg2.connect(
    host=os.environ["TEST_POSTGRES_HOST"],
    port=int(os.environ["TEST_POSTGRES_PORT"]),
    user=os.environ["TEST_POSTGRES_USER"],
    password=os.environ["TEST_POSTGRES_PASSWORD"],
    dbname=os.environ["TEST_POSTGRES_ADMIN_DB"],
)
connection.autocommit = True
try:
    with connection.cursor() as cursor:
        name = os.environ["TEST_DATABASE_NAME"]
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        if cursor.fetchone():
            print("NO")
        else:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            print("YES")
finally:
    connection.close()
PY
})"

database_url="$({
  TEST_DATABASE_NAME="${TEST_DATABASE_NAME}" TEST_POSTGRES_HOST="${TEST_POSTGRES_HOST}" TEST_POSTGRES_PORT="${TEST_POSTGRES_PORT}" \
  TEST_POSTGRES_USER="${TEST_POSTGRES_USER}" TEST_POSTGRES_PASSWORD="${TEST_POSTGRES_PASSWORD}" \
  "${PYTHON_BIN}" - <<'PY'
import os
from sqlalchemy.engine import URL
print(URL.create(
    "postgresql+psycopg2",
    username=os.environ["TEST_POSTGRES_USER"],
    password=os.environ["TEST_POSTGRES_PASSWORD"],
    host=os.environ["TEST_POSTGRES_HOST"],
    port=int(os.environ["TEST_POSTGRES_PORT"]),
    database=os.environ["TEST_DATABASE_NAME"],
).render_as_string(hide_password=False))
PY
})"
redis_url="redis://${TEST_REDIS_HOST}:${TEST_REDIS_PORT}/${TEST_REDIS_DB}"

(
  cd "${ROOT_DIR}"
  export APP_ENV=test SERVICE_ROLE=backend DATABASE_URL="${database_url}" REDIS_URL="${redis_url}" ASSET_STORAGE_ROOT="${asset_root}"
  "${PYTHON_BIN}" -m alembic -c alembic.ini upgrade head >"${runtime_dir}/alembic.log" 2>&1
)

"${PYTHON_BIN}" - "${TEST_BACKEND_HOST}" "${TEST_BACKEND_PORT}" <<'PY'
import socket
import sys
host, port = sys.argv[1], int(sys.argv[2])
with socket.socket() as sock:
    try:
        sock.bind((host, port))
    except OSError as exc:
        raise SystemExit(f"backend port unavailable: {exc}")
PY

(
  cd "${ROOT_DIR}"
  export APP_ENV=test SERVICE_ROLE=backend DATABASE_URL="${database_url}" REDIS_URL="${redis_url}" ASSET_STORAGE_ROOT="${asset_root}"
  "${PYTHON_BIN}" - "${ROOT_DIR}" "${log_file}" "${PYTHON_BIN}" "${TEST_BACKEND_HOST}" "${TEST_BACKEND_PORT}" >"${pid_file}.tmp" <<'PY'
from pathlib import Path
import os
import subprocess
import sys
import time

cwd, log_path, python, host, port = sys.argv[1:]
command = [python, "-m", "uvicorn", "backend.main:app", "--host", host, "--port", port, "--log-config", "backend/uvicorn_log_config.json"]
with Path(log_path).open("ab", buffering=0) as log:
    process = subprocess.Popen(
        command,
        cwd=Path(cwd).resolve(strict=True),
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
time.sleep(0.1)
if process.poll() is not None:
    raise SystemExit("test backend exited during detached startup")
print(process.pid)
PY
)
mv "${pid_file}.tmp" "${pid_file}"
backend_pid="$(sed -n '1p' "${pid_file}")"

identity_captured=0
for _ in $(seq 1 40); do
  if kill -0 "${backend_pid}" 2>/dev/null; then
    command_line="$(ps -ww -p "${backend_pid}" -o command= 2>/dev/null || true)"
    process_executable="${command_line%% *}"
    process_start="$(ps -p "${backend_pid}" -o lstart= 2>/dev/null | awk '{$1=$1; print}' || true)"
    process_cwd="$(lsof -a -p "${backend_pid}" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' || true)"
    if [ "${command_line#"${process_executable} "}" = "${expected_command_tail}" ] && [ "${process_cwd}" = "${ROOT_DIR}" ] && [ -n "${process_start}" ]; then
      command_sha="$(printf '%s' "${command_line}" | shasum -a 256 | awk '{print $1}')"
      identity_captured=1
      break
    fi
  fi
  sleep 0.05
done
[ "${identity_captured}" -eq 1 ] || fail "could not capture the launched backend identity"
printf 'STATE=STARTING\nCOMMIT_SHA=%s\nWORKTREE=%s\nHOST=%s\nPORT=%s\nDATABASE_NAME=%s\nPID=%s\nPROCESS_EXECUTABLE=%s\nPROCESS_COMMAND_SHA256=%s\nPROCESS_START=%s\n' \
  "${EXPECTED_COMMIT_SHA}" "${ROOT_DIR}" "${TEST_BACKEND_HOST}" "${TEST_BACKEND_PORT}" "${TEST_DATABASE_NAME}" "${backend_pid}" "${process_executable}" "${command_sha}" "${process_start}" >"${metadata_file}"
chmod 600 "${pid_file}" "${metadata_file}"

ready=0
for _ in $(seq 1 60); do
  if curl -fsS -m 2 "http://${TEST_BACKEND_HOST}:${TEST_BACKEND_PORT}/api/ready" >/dev/null 2>&1; then
    ready=1
    break
  fi
  if ! kill -0 "${backend_pid}" 2>/dev/null; then
    break
  fi
  sleep 0.5
done

if [ "${ready}" -ne 1 ]; then
  current_command="$(ps -ww -p "${backend_pid}" -o command= 2>/dev/null || true)"
  current_sha="$(printf '%s' "${current_command}" | shasum -a 256 | awk '{print $1}')"
  current_start="$(ps -p "${backend_pid}" -o lstart= 2>/dev/null | awk '{$1=$1; print}' || true)"
  current_cwd="$(lsof -a -p "${backend_pid}" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' || true)"
  listener_pid="$(lsof -nP -iTCP:"${TEST_BACKEND_PORT}" -sTCP:LISTEN -t 2>/dev/null | sort -u || true)"
  current_head="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
  if [ "${current_sha}" = "${command_sha}" ] && [ "${current_start}" = "${process_start}" ] && [ "${current_cwd}" = "${ROOT_DIR}" ] && [ "${listener_pid}" = "${backend_pid}" ] && [ "${current_head}" = "${EXPECTED_COMMIT_SHA}" ]; then
    kill -TERM "${backend_pid}" 2>/dev/null || true
    for _ in $(seq 1 100); do kill -0 "${backend_pid}" 2>/dev/null || break; sleep 0.1; done
    rm -f "${pid_file}" "${metadata_file}"
  fi
  fail "backend did not become ready; inspect ${log_file}"
fi

command_line="$(ps -ww -p "${backend_pid}" -o command=)"
[ "$(printf '%s' "${command_line}" | shasum -a 256 | awk '{print $1}')" = "${command_sha}" ] || fail "started PID command identity mismatch"
[ "$(ps -p "${backend_pid}" -o lstart= | awk '{$1=$1; print}')" = "${process_start}" ] || fail "started PID start time mismatch"
process_cwd="$(lsof -a -p "${backend_pid}" -d cwd -Fn | sed -n 's/^n//p')"
[ "${process_cwd}" = "${ROOT_DIR}" ] || fail "started PID worktree mismatch"
listener_pid="$(lsof -nP -iTCP:"${TEST_BACKEND_PORT}" -sTCP:LISTEN -t | sort -u)"
[ "${listener_pid}" = "${backend_pid}" ] || fail "started PID does not exclusively own the test port"
printf 'STATE=RUNNING\nCOMMIT_SHA=%s\nWORKTREE=%s\nHOST=%s\nPORT=%s\nDATABASE_NAME=%s\nPID=%s\nPROCESS_EXECUTABLE=%s\nPROCESS_COMMAND_SHA256=%s\nPROCESS_START=%s\n' \
  "${EXPECTED_COMMIT_SHA}" "${ROOT_DIR}" "${TEST_BACKEND_HOST}" "${TEST_BACKEND_PORT}" "${TEST_DATABASE_NAME}" "${backend_pid}" "${process_executable}" "${command_sha}" "${process_start}" >"${metadata_file}"
chmod 600 "${pid_file}" "${metadata_file}"

echo "TEST_DEPLOYMENT_STATUS=RUNNING"
echo "TEST_DATABASE_CREATED_BY_DEPLOY=${database_created}"
echo "TEST_DATABASE_NAME=${TEST_DATABASE_NAME}"
echo "TEST_BACKEND_PID=${backend_pid}"
echo "TEST_BASE_URL=http://${TEST_BACKEND_HOST}:${TEST_BACKEND_PORT}"
echo "TEST_LOG_FILE=${log_file}"
