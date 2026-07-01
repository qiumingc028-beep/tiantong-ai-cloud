#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

DEPLOY_MODE="${DEPLOY_MODE:-docker}"
COMPOSE="${COMPOSE:-docker compose}"
VENV_DIR="${VENV_DIR:-${ROOT_DIR}/venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

ensure_env() {
  if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example. Review secrets before production use."
  fi
}

load_env() {
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
}

deploy_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is not installed or not in PATH." >&2
    exit 127
  fi

  ensure_env
  mkdir -p backups

  ${COMPOSE} config
  ${COMPOSE} pull postgres redis nginx

  # Docker build installs backend and worker Python dependencies from requirements.txt.
  ${COMPOSE} build backend worker

  ${COMPOSE} up -d postgres redis

  # Run migrations explicitly before replacing application processes.
  ${COMPOSE} run --rm backend alembic upgrade head

  ${COMPOSE} up -d --force-recreate backend
  ${COMPOSE} up -d --force-recreate worker nginx

  ${COMPOSE} ps
  CHECK_DOCKER_INFRA=1 bash "${ROOT_DIR}/scripts/healthcheck.sh"
}

deploy_systemd() {
  ensure_env
  load_env

  if [ ! -x "${VENV_DIR}/bin/python" ]; then
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  fi

  "${VENV_DIR}/bin/python" -m pip install --upgrade pip
  "${VENV_DIR}/bin/pip" install -r requirements.txt
  "${VENV_DIR}/bin/alembic" upgrade head

  sudo cp deploy/tiantong-api.service /etc/systemd/system/tiantong-api.service
  sudo cp deploy/tiantong-worker.service /etc/systemd/system/tiantong-worker.service
  sudo cp deploy/nginx-systemd.conf /etc/nginx/conf.d/tiantong.conf
  sudo systemctl daemon-reload
  sudo systemctl enable tiantong-api tiantong-worker
  sudo systemctl restart tiantong-api
  sudo systemctl restart tiantong-worker
  sudo nginx -t
  sudo systemctl reload nginx
  sudo systemctl status tiantong-api --no-pager
  sudo systemctl status tiantong-worker --no-pager

  CHECK_SYSTEMD=1 bash "${ROOT_DIR}/scripts/healthcheck.sh"
  BASE_URL=http://127.0.0.1:8000 CHECK_PAGES=0 CHECK_SYSTEMD=1 bash "${ROOT_DIR}/scripts/healthcheck.sh"
}

case "${DEPLOY_MODE}" in
  docker)
    deploy_docker
    ;;
  systemd)
    deploy_systemd
    ;;
  *)
    echo "Unsupported DEPLOY_MODE=${DEPLOY_MODE}. Use DEPLOY_MODE=docker or DEPLOY_MODE=systemd." >&2
    exit 2
    ;;
esac

echo "Tiantong AI Cloud ${DEPLOY_MODE} deployment completed."
