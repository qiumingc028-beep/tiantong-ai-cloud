#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

DEPLOY_MODE="${DEPLOY_MODE:-docker}"
COMPOSE="${COMPOSE:-docker compose}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env.production}"
COMPOSE_CMD="${COMPOSE} --env-file ${ENV_FILE} -f ${COMPOSE_FILE}"
VENV_DIR="${VENV_DIR:-${ROOT_DIR}/venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
GIT_REMOTE="${GIT_REMOTE:-origin}"
GIT_BRANCH="${GIT_BRANCH:-main}"

ensure_env() {
  if [ ! -f "${ENV_FILE}" ]; then
    echo "Missing ${ENV_FILE}. Create it from .env.production.example and replace all placeholders before deployment." >&2
    exit 2
  fi

  if grep -q '<.*>' "${ENV_FILE}"; then
    echo "Refusing to deploy: ${ENV_FILE} still contains placeholder values." >&2
    exit 2
  fi

  chmod 600 "${ENV_FILE}"
}

load_env() {
  set -a
  # shellcheck disable=SC1091
  . "./${ENV_FILE}"
  set +a
}

deploy_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is not installed or not in PATH." >&2
    exit 127
  fi

  ensure_env
  mkdir -p backups

  if [ -d .git ] && git remote get-url "${GIT_REMOTE}" >/dev/null 2>&1; then
    git fetch --prune "${GIT_REMOTE}" "${GIT_BRANCH}"
    git checkout "${GIT_BRANCH}"
    git pull --ff-only "${GIT_REMOTE}" "${GIT_BRANCH}"
  fi

  ${COMPOSE_CMD} config
  ${COMPOSE_CMD} pull postgres redis

  ${COMPOSE_CMD} build --pull backend worker nginx

  ${COMPOSE_CMD} up -d postgres redis

  # Run migrations explicitly before replacing application processes.
  ${COMPOSE_CMD} run --rm backend alembic upgrade head

  ${COMPOSE_CMD} up -d --force-recreate backend worker nginx

  ${COMPOSE_CMD} ps
  COMPOSE="${COMPOSE_CMD}" CHECK_DOCKER_INFRA=1 bash "${ROOT_DIR}/scripts/healthcheck.sh"
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
