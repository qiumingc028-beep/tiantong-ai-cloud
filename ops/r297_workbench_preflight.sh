#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: r297_workbench_preflight.sh DEPLOYMENT_DIR EXPECTED_COMMIT" >&2
  exit 64
fi

DEPLOYMENT_DIR=$(realpath "$1")
EXPECTED_COMMIT=$2
ENV_FILE=${R297_ENV_FILE:?set R297_ENV_FILE to the root-only production environment file}
CI_RUN_ID=${R297_CI_RUN_ID:?set R297_CI_RUN_ID to the successful GitHub Actions run id}
PROJECT_NAME=tiantong_v2_s12_internal
COMPOSE_FILE=$DEPLOYMENT_DIR/docker-compose.prod.yml
CI_RUN_URL=https://api.github.com/repos/qiumingc028-beep/tiantong-ai-cloud/actions/runs/$CI_RUN_ID
export PRODUCTION_ENV_FILE=$ENV_FILE

[[ $EXPECTED_COMMIT =~ ^[0-9a-f]{40}$ ]] || { echo "R297_INVALID_EXPECTED_COMMIT" >&2; exit 65; }
[[ $CI_RUN_ID =~ ^[0-9]+$ ]] || { echo "R297_INVALID_CI_RUN_ID" >&2; exit 65; }
[[ -d $DEPLOYMENT_DIR/.git || -f $DEPLOYMENT_DIR/.git ]] || { echo "R297_DEPLOYMENT_NOT_GIT_WORKTREE" >&2; exit 66; }
[[ -f $COMPOSE_FILE ]] || { echo "R297_COMPOSE_MISSING" >&2; exit 66; }
[[ -f $ENV_FILE ]] || { echo "R297_ENV_FILE_MISSING" >&2; exit 66; }

env_mode=$(stat -c '%a' "$ENV_FILE")
env_mode_decimal=$((8#$env_mode))
(( (env_mode_decimal & 077) == 0 )) || { echo "R297_ENV_FILE_PERMISSIONS_TOO_OPEN" >&2; exit 77; }

[[ $(uname -m) == x86_64 ]] || { echo "R297_UNSUPPORTED_ECS_ARCHITECTURE" >&2; exit 78; }
command -v git >/dev/null
command -v docker >/dev/null
command -v curl >/dev/null
command -v sha256sum >/dev/null
docker version >/dev/null
docker compose version >/dev/null

curl --fail --silent --show-error --max-time 20 \
  --header 'Accept: application/vnd.github+json' \
  "$CI_RUN_URL" \
  | python3 -c '
import json
import sys
payload = json.load(sys.stdin)
if payload.get("name") != "CI":
    raise SystemExit("R297_CI_NAME_MISMATCH")
if payload.get("head_sha") != sys.argv[1]:
    raise SystemExit("R297_CI_HEAD_MISMATCH")
if payload.get("status") != "completed":
    raise SystemExit("R297_CI_NOT_COMPLETED")
if payload.get("conclusion") != "success":
    raise SystemExit("R297_CI_NOT_SUCCESSFUL")
' "$EXPECTED_COMMIT"

actual_commit=$(git -C "$DEPLOYMENT_DIR" rev-parse HEAD)
[[ $actual_commit == "$EXPECTED_COMMIT" ]] || { echo "R297_COMMIT_MISMATCH" >&2; exit 79; }
[[ -z $(git -C "$DEPLOYMENT_DIR" status --porcelain=v1) ]] || { echo "R297_WORKTREE_NOT_CLEAN" >&2; exit 79; }
SOURCE_DATE_EPOCH=$(git -C "$DEPLOYMENT_DIR" show -s --format=%ct "$EXPECTED_COMMIT")
[[ $SOURCE_DATE_EPOCH =~ ^[0-9]+$ ]] || { echo "R297_SOURCE_DATE_EPOCH_INVALID" >&2; exit 79; }
export SOURCE_DATE_EPOCH

# Signing roles run this same checker inside their isolated service identities.
# The deployment controller is a verifier and must not possess any signing key.
APP_ENV=production PYTHONPATH="$DEPLOYMENT_DIR" \
  python3 -m ops.r297_evidence_preflight --role verifier

for preserved_commit in \
  17d79c6 f144557 8eb807a b18e431 e0db23a 1b8af29 51235a7 af2185b; do
  git -C "$DEPLOYMENT_DIR" merge-base --is-ancestor "$preserved_commit" "$EXPECTED_COMMIT" || {
    echo "R297_REQUIRED_MAIN_FIX_NOT_PRESERVED" >&2
    exit 80
  }
done

[[ -f $DEPLOYMENT_DIR/alembic/versions/0050_r297_reliable_sync_queue.py ]] || {
  echo "R297_MIGRATION_MISSING" >&2
  exit 81
}

docker compose \
  --project-name "$PROJECT_NAME" \
  --env-file "$ENV_FILE" \
  --file "$COMPOSE_FILE" \
  config --quiet

for service in postgres redis backend worker jd-browser-runtime nginx; do
  container_id=$(docker compose \
    --project-name "$PROJECT_NAME" \
    --env-file "$ENV_FILE" \
    --file "$COMPOSE_FILE" \
    ps --quiet "$service")
  [[ -n $container_id ]] || { echo "R297_REQUIRED_SERVICE_NOT_RUNNING" >&2; exit 82; }
done

echo "R297_PREFLIGHT_PASS"
echo "ARCH=x86_64"
echo "EXPECTED_COMMIT=$EXPECTED_COMMIT"
echo "CI_RUN_ID=$CI_RUN_ID"
