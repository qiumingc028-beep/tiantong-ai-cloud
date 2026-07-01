#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

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

check_endpoint "/api/health" "running"
check_endpoint "/api/ready" "ready"

echo "tiantong-api healthcheck passed"
