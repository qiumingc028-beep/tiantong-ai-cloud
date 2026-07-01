#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

DEPLOY_MODE="${DEPLOY_MODE:-docker}"
TARGET_REF="${1:-${ROLLBACK_REF:-}}"

if [ -z "${TARGET_REF}" ]; then
  echo "Usage: ./rollback.sh <git-ref>" >&2
  echo "Example: ./rollback.sh HEAD~1" >&2
  exit 2
fi

if ! command -v git >/dev/null 2>&1; then
  echo "git is required for rollback." >&2
  exit 127
fi

if [ -x scripts/backup_db.sh ]; then
  bash scripts/backup_db.sh || echo "Database backup failed; continuing rollback by operator request."
fi

git checkout "${TARGET_REF}"

case "${DEPLOY_MODE}" in
  docker)
    bash ./deploy.sh
    ;;
  systemd)
    DEPLOY_MODE=systemd bash ./deploy.sh
    ;;
  *)
    echo "Unsupported DEPLOY_MODE=${DEPLOY_MODE}. Use docker or systemd." >&2
    exit 2
    ;;
esac

echo "Rollback to ${TARGET_REF} completed with ${DEPLOY_MODE} deployment."
