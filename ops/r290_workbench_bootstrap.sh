#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${1:-$PWD}"
cd "$ROOT"
ENV_FILE="${R290_ENV_FILE:-/run/user/$(id -u)/tiantong-r290.env}"
test -r "$ENV_FILE" || { echo R290_ENV_FILE_MISSING; exit 21; }
chmod 600 "$ENV_FILE"
test "$(git status --porcelain=v1 | wc -l | tr -d ' ')" = 0
test -n "$(git rev-parse HEAD)"
docker info >/dev/null
docker buildx inspect r290 >/dev/null 2>&1 || docker buildx create --name r290 --use
docker buildx use r290
docker buildx inspect --bootstrap >/dev/null
echo BOOTSTRAP_PASS
