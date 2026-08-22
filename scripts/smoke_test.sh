#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON_BIN="${TEST_PYTHON:-/Users/chenqiuming/.openclaw/runtimes/tiantong-test-r1/bin/python}"

fail() {
  echo "test smoke refused: $1" >&2
  exit 2
}

required() {
  local name="$1"
  [ -n "${!name:-}" ] || fail "${name} is required"
}

[ "${TIANTONG_ENV:-}" = "test" ] || fail "TIANTONG_ENV must equal test"
required EXPECTED_COMMIT_SHA
required TEST_RUNTIME_ID
required TEST_BASE_URL
required TEST_DATABASE_NAME
required TEST_POSTGRES_HOST
required TEST_POSTGRES_PORT
required TEST_POSTGRES_USER
required TEST_POSTGRES_PASSWORD
required TEST_POSTGRES_CONTAINER
required TEST_REDIS_HOST
required TEST_REDIS_PORT
required TEST_REDIS_CONTAINER

[[ "${TEST_RUNTIME_ID}" =~ ^[A-Za-z0-9._-]+$ ]] || fail "invalid TEST_RUNTIME_ID"
[[ "${TEST_DATABASE_NAME}" =~ ^tiantong_v2_test_[a-z0-9_]+$ ]] || fail "invalid test database name"
[ "${TEST_POSTGRES_HOST}" = "127.0.0.1" ] || [ "${TEST_POSTGRES_HOST}" = "localhost" ] || fail "PostgreSQL must be loopback"
[ "${TEST_REDIS_HOST}" = "127.0.0.1" ] || [ "${TEST_REDIS_HOST}" = "localhost" ] || fail "Redis must be loopback"

head_sha="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
[ "${head_sha}" = "${EXPECTED_COMMIT_SHA}" ] || fail "commit mismatch"
[ -z "$(git -C "${ROOT_DIR}" status --porcelain=v1)" ] || fail "git worktree must be clean"

project_label=tiantong-v2-usable-v1-s1-taskcenter-ownership-idor-r70
[ "$(docker inspect -f '{{index .Config.Labels "tiantong.qa.task"}}' "${TEST_POSTGRES_CONTAINER}")" = R70 ] || fail "PostgreSQL is not the R70 test runtime"
[ "$(docker inspect -f '{{index .Config.Labels "tiantong.qa.project"}}' "${TEST_POSTGRES_CONTAINER}")" = "${project_label}" ] || fail "PostgreSQL project label mismatch"
[ "$(docker port "${TEST_POSTGRES_CONTAINER}" 5432/tcp)" = "127.0.0.1:${TEST_POSTGRES_PORT}" ] || fail "PostgreSQL port mismatch"
[ "$(docker inspect -f '{{index .Config.Labels "tiantong.qa.task"}}' "${TEST_REDIS_CONTAINER}")" = R70 ] || fail "Redis is not the R70 test runtime"
[ "$(docker inspect -f '{{index .Config.Labels "tiantong.qa.project"}}' "${TEST_REDIS_CONTAINER}")" = "${project_label}" ] || fail "Redis project label mismatch"
[ "$(docker port "${TEST_REDIS_CONTAINER}" 6379/tcp)" = "127.0.0.1:${TEST_REDIS_PORT}" ] || fail "Redis port mismatch"

base_host_port="$({
  TEST_BASE_URL="${TEST_BASE_URL}" "${PYTHON_BIN}" - <<'PY'
import os
from urllib.parse import urlparse
parsed = urlparse(os.environ["TEST_BASE_URL"])
if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
    raise SystemExit(2)
print(f"{parsed.hostname}:{parsed.port or 80}")
PY
})" || fail "TEST_BASE_URL must be loopback HTTP"

runtime_dir="/tmp/tiantong-test-deploy-${TEST_RUNTIME_ID}"
metadata_file="${runtime_dir}/backend.env"
pid_file="${runtime_dir}/backend.pid"
[ -f "${metadata_file}" ] && [ -f "${pid_file}" ] || fail "test deployment metadata is absent"
[ "$(sed -n 's/^COMMIT_SHA=//p' "${metadata_file}")" = "${EXPECTED_COMMIT_SHA}" ] || fail "deployment commit mismatch"
[ "$(sed -n 's/^WORKTREE=//p' "${metadata_file}")" = "${ROOT_DIR}" ] || fail "deployment worktree mismatch"
[ "$(sed -n 's/^HOST=//p' "${metadata_file}"):$(sed -n 's/^PORT=//p' "${metadata_file}")" = "${base_host_port}" ] || fail "TEST_BASE_URL does not match deployment metadata"
pid="$(sed -n '1p' "${pid_file}")"
kill -0 "${pid}" 2>/dev/null || fail "test backend is not running"

passed=0
pass() {
  passed=$((passed + 1))
  echo "SMOKE_${passed}=PASS:$1"
}

health_json="$(curl -fsS -m 10 "${TEST_BASE_URL%/}/api/health")"
printf '%s' "${health_json}" | "${PYTHON_BIN}" -c 'import json,sys; p=json.load(sys.stdin); assert p["status"]=="running" and p["database"] is True and p["redis"] is True'
pass backend_health

ready_json="$(curl -fsS -m 10 "${TEST_BASE_URL%/}/api/ready")"
printf '%s' "${ready_json}" | "${PYTHON_BIN}" -c 'import json,sys; p=json.load(sys.stdin); assert p["status"]=="ready" and p["ok"] is True'
pass backend_ready

TEST_DATABASE_NAME="${TEST_DATABASE_NAME}" TEST_POSTGRES_HOST="${TEST_POSTGRES_HOST}" TEST_POSTGRES_PORT="${TEST_POSTGRES_PORT}" \
TEST_POSTGRES_USER="${TEST_POSTGRES_USER}" TEST_POSTGRES_PASSWORD="${TEST_POSTGRES_PASSWORD}" "${PYTHON_BIN}" - <<'PY'
import os
import psycopg2
connection = psycopg2.connect(host=os.environ["TEST_POSTGRES_HOST"], port=int(os.environ["TEST_POSTGRES_PORT"]), user=os.environ["TEST_POSTGRES_USER"], password=os.environ["TEST_POSTGRES_PASSWORD"], dbname=os.environ["TEST_DATABASE_NAME"])
try:
    with connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE TEMP TABLE r167_smoke(value integer)")
            cursor.execute("INSERT INTO r167_smoke VALUES (1)")
            cursor.execute("SELECT value FROM r167_smoke")
            assert cursor.fetchone() == (1,)
finally:
    connection.close()
PY
pass postgres_read_write

TEST_REDIS_HOST="${TEST_REDIS_HOST}" TEST_REDIS_PORT="${TEST_REDIS_PORT}" TEST_REDIS_DB="${TEST_REDIS_DB:-0}" "${PYTHON_BIN}" - <<'PY'
import os
from redis import Redis
client = Redis(host=os.environ["TEST_REDIS_HOST"], port=int(os.environ["TEST_REDIS_PORT"]), db=int(os.environ["TEST_REDIS_DB"]), socket_timeout=3)
assert client.ping() is True
client.close()
PY
pass redis_ping

admin_url="$({
  TEST_POSTGRES_ADMIN_DB="${TEST_POSTGRES_ADMIN_DB:-postgres}" TEST_POSTGRES_HOST="${TEST_POSTGRES_HOST}" TEST_POSTGRES_PORT="${TEST_POSTGRES_PORT}" \
  TEST_POSTGRES_USER="${TEST_POSTGRES_USER}" TEST_POSTGRES_PASSWORD="${TEST_POSTGRES_PASSWORD}" "${PYTHON_BIN}" - <<'PY'
import os
from sqlalchemy.engine import URL
print(URL.create("postgresql", username=os.environ["TEST_POSTGRES_USER"], password=os.environ["TEST_POSTGRES_PASSWORD"], host=os.environ["TEST_POSTGRES_HOST"], port=int(os.environ["TEST_POSTGRES_PORT"]), database=os.environ["TEST_POSTGRES_ADMIN_DB"]).render_as_string(hide_password=False))
PY
})"

run_pytest_smoke() {
  local label="$1" node="$2" log_file="${runtime_dir}/smoke-${1}.log"
  (
    cd "${ROOT_DIR}"
    export APP_ENV=test SERVICE_ROLE=backend V2_ALPHA_POSTGRES_ADMIN_URL="${admin_url}"
    "${PYTHON_BIN}" -m pytest -q "${node}" >"${log_file}" 2>&1
  ) || fail "${label} failed; inspect ${log_file}"
  pass "${label}"
}

run_pytest_smoke pub009_ownership 'tests/test_task_center_full_entrypoint_ownership.py::test_r109_taskcenter_public_entrypoint_dynamic[PUB-009-http_request-mixed_scope_filter]'
run_pytest_smoke pub055_foreign_write 'tests/test_task_center_full_entrypoint_ownership.py::test_r109_taskcenter_public_entrypoint_dynamic[PUB-055-http_request-foreign_company]'
run_pytest_smoke pub056_foreign_write 'tests/test_task_center_full_entrypoint_ownership.py::test_r109_taskcenter_public_entrypoint_dynamic[PUB-056-http_request-foreign_company]'
run_pytest_smoke pub083_queue 'tests/test_task_center_full_entrypoint_ownership.py::test_r109_taskcenter_public_entrypoint_dynamic[PUB-083-http_request-mixed_scope_independence]'
run_pytest_smoke pub099_nonenumeration 'tests/test_task_center_full_entrypoint_ownership.py::test_r109_taskcenter_public_entrypoint_dynamic[PUB-099-http_request-foreign_company]'
run_pytest_smoke computer_workflow_ownership 'tests/test_computer_workflows.py::test_computer_workflow_public_routes_enforce_task_ownership'
run_pytest_smoke get_zero_write 'tests/test_task_center_full_entrypoint_ownership.py::test_r109_taskcenter_public_entrypoint_dynamic[PUB-045-http_request-mixed_scope_filter]'

[ "${passed}" -eq 11 ] || fail "smoke count mismatch"
echo "SMOKE_REQUIRED=11"
echo "SMOKE_PASSED=${passed}"
echo "SMOKE_FAILED=0"
echo "SMOKE_ERROR=0"
