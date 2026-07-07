#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1}"
CHECK_PAGES="${CHECK_PAGES:-1}"
CHECK_DOCKER_INFRA="${CHECK_DOCKER_INFRA:-0}"
CHECK_SYSTEMD="${CHECK_SYSTEMD:-0}"
COMPOSE="${COMPOSE:-docker compose}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -z "${FRONTEND_PAGES:-}" ] && [ -d "${ROOT_DIR}/frontend" ]; then
  FRONTEND_PAGES="/"
  for file in "${ROOT_DIR}"/frontend/*.html; do
    [ -e "${file}" ] || continue
    FRONTEND_PAGES="${FRONTEND_PAGES} /$(basename "${file}")"
  done
fi

check_page() {
  local path="$1"
  local url="${BASE_URL}${path}"

  echo "Checking page ${url}"
  curl -fsS -m 10 -o /dev/null "${url}"
}

check_endpoint() {
  local path="$1"
  local expected="$2"
  local url="${BASE_URL}${path}"

  echo "Checking ${url}"
  local response
  response="$(curl -fsS -m 10 "${url}")"
  echo "${response}"
  echo "${response}" | grep -q "\"status\"[[:space:]]*:[[:space:]]*\"${expected}\""
}

check_api_health() {
  local url="${BASE_URL}/api/health"

  echo "Checking ${url}"
  local response
  response="$(curl -fsS -m 10 "${url}")"
  echo "${response}"
  echo "${response}" | grep -q '"status"[[:space:]]*:[[:space:]]*"running"'
  echo "${response}" | grep -q '"database"[[:space:]]*:[[:space:]]*true'
  echo "${response}" | grep -q '"redis"[[:space:]]*:[[:space:]]*true'
  echo "PostgreSQL check passed through /api/health"
  echo "Redis check passed through /api/health"
}

check_docker_infra() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker command not found; skipping Docker infrastructure checks."
    return
  fi

  ${COMPOSE} config >/dev/null

  echo "Checking PostgreSQL container"
  ${COMPOSE} exec -T postgres pg_isready -U "${POSTGRES_USER:-tiantong}" -d "${POSTGRES_DB:-tiantong_ai}"

  echo "Checking Redis container"
  ${COMPOSE} exec -T redis redis-cli ping | grep -q PONG

  echo "Checking worker container"
  ${COMPOSE} exec -T worker python -c "print('worker container running')"
}

check_systemd_worker() {
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemctl command not found; skipping systemd worker check."
    return
  fi

  echo "Checking tiantong-worker systemd service"
  systemctl is-active --quiet tiantong-worker
}

if [ "${CHECK_PAGES}" = "1" ]; then
  for page in ${FRONTEND_PAGES}; do
    check_page "${page}"
  done
fi

check_api_health
check_endpoint "/health" "running"
check_endpoint "/api/ready" "ready"
check_endpoint "/ready" "ready"

if [ "${CHECK_DOCKER_INFRA}" = "1" ]; then
  check_docker_infra
fi

if [ "${CHECK_SYSTEMD}" = "1" ]; then
  check_systemd_worker
fi

echo "Tiantong AI Cloud healthcheck passed."
