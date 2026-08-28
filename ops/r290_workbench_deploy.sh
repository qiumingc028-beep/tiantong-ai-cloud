#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${1:-$PWD}"
cd "$ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="/var/backups/tiantong-r290-${STAMP}"
sudo install -d -m 700 "$BACKUP"
sudo cp docker-compose.prod.yml "$BACKUP/compose.yml"
git rev-parse HEAD | sudo tee "$BACKUP/commit" >/dev/null
ARTIFACT_DIR="${ARTIFACT_DIR:-$BACKUP/artifacts}"
install -d -m 700 "$ARTIFACT_DIR"
docker buildx build --platform linux/amd64 -f Dockerfile.frontend -t tiantong-r290-frontend:internal --load .
docker buildx build --platform linux/arm64 -f Dockerfile.frontend --output "type=oci,dest=$ARTIFACT_DIR/frontend-arm64.tar" .
docker buildx build --platform linux/amd64 -f Dockerfile.backend -t tiantong-r290-backend:internal --load .
docker buildx build --platform linux/arm64 -f Dockerfile.backend --output "type=oci,dest=$ARTIFACT_DIR/backend-arm64.tar" .
docker buildx build --platform linux/amd64 -f Dockerfile.worker -t tiantong-r290-worker:internal --load .
docker buildx build --platform linux/arm64 -f Dockerfile.worker --output "type=oci,dest=$ARTIFACT_DIR/worker-arm64.tar" .
docker compose -f docker-compose.prod.yml up -d postgres redis backend worker frontend nginx
docker compose -f docker-compose.prod.yml exec -T backend alembic upgrade head
docker compose -f docker-compose.prod.yml ps
echo DEPLOY_PASS
