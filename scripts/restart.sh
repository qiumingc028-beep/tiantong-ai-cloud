#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

COMPOSE="${COMPOSE:-docker compose}"

${COMPOSE} up -d --build postgres redis backend worker nginx
bash "${ROOT_DIR}/scripts/healthcheck.sh"

echo "Tiantong AI Cloud services restarted."
