#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${1:-$PWD}"
cd "$ROOT"
ENV_FILE="${R290_ENV_FILE:-/run/user/$(id -u)/tiantong-r290.env}"
mkdir -p "$(dirname "$ENV_FILE")"
if [ ! -s "$ENV_FILE" ]; then
  CONTAINER="$(docker ps --filter name=backend --format '{{.ID}}' | head -1)"
  test -n "$CONTAINER" || { echo R290_BACKEND_CONTAINER_MISSING; exit 22; }
  umask 077
  docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER" | awk -F= '/^(POSTGRES_DB|POSTGRES_ADMIN_USER|POSTGRES_ADMIN_PASSWORD|REDIS_PASSWORD|PRODUCTION_ENV_FILE|REQUIREMENTS_LOCK|HTTP_PORT|HTTPS_PORT|TLS_CERT_PATH|TLS_KEY_PATH)=/{print}' > "$ENV_FILE"
fi
test -r "$ENV_FILE" || { echo R290_ENV_FILE_MISSING; exit 21; }
chmod 600 "$ENV_FILE"
printf 'R290_PREFLIGHT\n'
uname -m
lsb_release -ds 2>/dev/null || true
docker version --format 'docker={{.Server.Version}}' 2>/dev/null || { echo 'DOCKER_UNAVAILABLE'; exit 20; }
docker compose version
docker buildx version
git rev-parse HEAD
git status --porcelain=v1
docker ps --format '{{.Names}}' | sort
docker volume ls --format '{{.Name}}' | sort
for p in 80 443 18000 18443; do (nc -z 127.0.0.1 "$p" >/dev/null 2>&1 && echo "PORT_${p}=OPEN" || echo "PORT_${p}=CLOSED"); done
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml config >/dev/null
echo PREFLIGHT_PASS
