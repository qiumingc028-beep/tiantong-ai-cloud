#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
USERNAME="${API_USERNAME:-owner}"
PASSWORD="${API_PASSWORD:-password}"

cd "$(dirname "$0")/.."

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "未找到 python 或 python3，无法执行接口验收。"
  exit 127
fi

"${PYTHON_BIN}" tests/api_acceptance_check.py \
  --base-url "${BASE_URL}" \
  --username "${USERNAME}" \
  --password "${PASSWORD}"
