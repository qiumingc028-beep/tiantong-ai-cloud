#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

COMPOSE="${COMPOSE:-docker compose}"
BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

POSTGRES_DB="${POSTGRES_DB:-tiantong_ai}"
POSTGRES_USER="${POSTGRES_USER:-tiantong}"

mkdir -p "${BACKUP_DIR}"

OUT_FILE="${BACKUP_DIR}/tiantong_${POSTGRES_DB}_${TIMESTAMP}.sql.gz"

${COMPOSE} exec -T postgres pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" | gzip > "${OUT_FILE}"

echo "Database backup written to ${OUT_FILE}"
