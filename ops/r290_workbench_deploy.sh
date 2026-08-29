#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${1:-$PWD}"
cd "$ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/var/backups/tiantong-r290-${STAMP}"
ENV_FILE="${R290_ENV_FILE:-/run/user/$(id -u)/tiantong-r290.env}"
mkdir -p "$(dirname "$ENV_FILE")"
if [ ! -s "$ENV_FILE" ]; then
  CONTAINER="$(docker ps --filter name=backend --format '{{.ID}}' | head -1)"
  test -n "$CONTAINER" || { echo R290_BACKEND_CONTAINER_MISSING; exit 22; }
  umask 077
  docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER" | awk -F= '/^(POSTGRES_DB|POSTGRES_ADMIN_USER|POSTGRES_ADMIN_PASSWORD|REDIS_PASSWORD|PRODUCTION_ENV_FILE|REQUIREMENTS_LOCK|HTTP_PORT|HTTPS_PORT|TLS_CERT_PATH|TLS_KEY_PATH)=/{print}' > "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"
for key in POSTGRES_DB POSTGRES_ADMIN_USER POSTGRES_ADMIN_PASSWORD REDIS_PASSWORD; do grep -q "^${key}=" "$ENV_FILE" || { echo "R290_REQUIRED_ENV_MISSING_${key}"; exit 23; }; done
sudo install -d -m 700 "$BACKUP"
sudo cp docker-compose.prod.yml "$BACKUP/compose.yml"
git rev-parse HEAD | sudo tee "$BACKUP/commit" >/dev/null
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml config --images | sudo tee "$BACKUP/images" >/dev/null
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec -T postgres sh -c 'pg_dumpall -U "$POSTGRES_USER"' > "$BACKUP/database.sql"
chmod 600 "$BACKUP/database.sql"
rollback() { rc=$?; if [ "$rc" -ne 0 ]; then docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml up -d --no-build postgres redis backend worker nginx >/dev/null 2>&1 || true; fi; exit "$rc"; }
trap rollback EXIT
ARTIFACT_DIR="${ARTIFACT_DIR:-$BACKUP/artifacts}"
install -d -m 700 "$ARTIFACT_DIR"
docker buildx build --platform linux/amd64 -f Dockerfile.frontend -t tiantong-r290-frontend:internal --load .
docker buildx build --platform linux/arm64 -f Dockerfile.frontend --output "type=oci,dest=$ARTIFACT_DIR/frontend-arm64.tar" .
docker buildx build --platform linux/amd64 -f Dockerfile.backend -t tiantong-r290-backend:internal --load .
docker buildx build --platform linux/arm64 -f Dockerfile.backend --output "type=oci,dest=$ARTIFACT_DIR/backend-arm64.tar" .
docker buildx build --platform linux/amd64 -f Dockerfile.worker -t tiantong-r290-worker:internal --load .
docker buildx build --platform linux/arm64 -f Dockerfile.worker --output "type=oci,dest=$ARTIFACT_DIR/worker-arm64.tar" .
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml up -d postgres redis backend worker nginx
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml exec -T backend alembic upgrade head
docker compose --env-file "$ENV_FILE" -f docker-compose.prod.yml ps
echo DEPLOY_PASS
