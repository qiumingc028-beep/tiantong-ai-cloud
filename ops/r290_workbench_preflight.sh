#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${1:-$PWD}"
cd "$ROOT"
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
docker compose -f docker-compose.prod.yml config >/dev/null
echo PREFLIGHT_PASS
