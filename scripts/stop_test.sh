#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

fail() {
  echo "test stop refused: $1" >&2
  exit 2
}

[ "${TIANTONG_ENV:-}" = "test" ] || fail "TIANTONG_ENV must equal test"
[ -n "${EXPECTED_COMMIT_SHA:-}" ] || fail "EXPECTED_COMMIT_SHA is required"
[ -n "${TEST_RUNTIME_ID:-}" ] || fail "TEST_RUNTIME_ID is required"
[[ "${TEST_RUNTIME_ID}" =~ ^[A-Za-z0-9._-]+$ ]] || fail "invalid TEST_RUNTIME_ID"

head_sha="$(git -C "${ROOT_DIR}" rev-parse HEAD)"
[ "${head_sha}" = "${EXPECTED_COMMIT_SHA}" ] || fail "commit mismatch"

runtime_dir="/tmp/tiantong-test-deploy-${TEST_RUNTIME_ID}"
pid_file="${runtime_dir}/backend.pid"
metadata_file="${runtime_dir}/backend.env"
[ -f "${pid_file}" ] || fail "test backend PID file is absent"
[ -f "${metadata_file}" ] || fail "test backend metadata is absent"

pid="$(sed -n '1p' "${pid_file}")"
[[ "${pid}" =~ ^[0-9]+$ ]] || fail "invalid PID metadata"
[ "$(sed -n 's/^PID=//p' "${metadata_file}")" = "${pid}" ] || fail "PID metadata mismatch"
[ "$(sed -n 's/^COMMIT_SHA=//p' "${metadata_file}")" = "${EXPECTED_COMMIT_SHA}" ] || fail "deployment commit mismatch"
[ "$(sed -n 's/^WORKTREE=//p' "${metadata_file}")" = "${ROOT_DIR}" ] || fail "deployment worktree mismatch"
state="$(sed -n 's/^STATE=//p' "${metadata_file}")"
case "${state}" in RUNNING|STARTING) ;; *) fail "deployment state is invalid" ;; esac
host="$(sed -n 's/^HOST=//p' "${metadata_file}")"
port="$(sed -n 's/^PORT=//p' "${metadata_file}")"
process_start="$(sed -n 's/^PROCESS_START=//p' "${metadata_file}")"
process_executable="$(sed -n 's/^PROCESS_EXECUTABLE=//p' "${metadata_file}")"
command_sha="$(sed -n 's/^PROCESS_COMMAND_SHA256=//p' "${metadata_file}")"
[ -n "${process_executable}" ] && [ -n "${command_sha}" ] && [ -n "${process_start}" ] || fail "process identity metadata is incomplete"

kill -0 "${pid}" 2>/dev/null || fail "recorded process is not running"
command_line="$(ps -ww -p "${pid}" -o command=)"
actual_executable="${command_line%% *}"
expected_command_tail="-m uvicorn backend.main:app --host ${host} --port ${port} --log-config backend/uvicorn_log_config.json"
[ "${actual_executable}" = "${process_executable}" ] || fail "recorded PID executable mismatch"
[ "${command_line#"${actual_executable} "}" = "${expected_command_tail}" ] || fail "recorded PID command arguments mismatch"
actual_command_sha="$(printf '%s' "${command_line}" | shasum -a 256 | awk '{print $1}')"
[ "${actual_command_sha}" = "${command_sha}" ] || fail "recorded PID command identity mismatch"
current_start="$(ps -p "${pid}" -o lstart= | awk '{$1=$1; print}')"
[ "${current_start}" = "${process_start}" ] || fail "recorded PID start time mismatch"
process_cwd="$(lsof -a -p "${pid}" -d cwd -Fn | sed -n 's/^n//p')"
[ "${process_cwd}" = "${ROOT_DIR}" ] || fail "test backend working directory mismatch"
listener_pid="$(lsof -nP -iTCP:"${port}" -sTCP:LISTEN -t | sort -u)"
[ "${listener_pid}" = "${pid}" ] || fail "recorded PID does not exclusively own the test port"

kill -TERM "${pid}"
for _ in $(seq 1 100); do
  if ! kill -0 "${pid}" 2>/dev/null; then
    mv "${metadata_file}" "${runtime_dir}/last-stopped.env"
    rm -f "${pid_file}"
    echo "TEST_STOP_STATUS=STOPPED"
    echo "TEST_DATABASE_DELETED=NO"
    exit 0
  fi
  sleep 0.1
done

fail "test backend did not stop after SIGTERM"
