#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

fail_if_requested() {
  if [[ ${R297_FAILURE_INJECTION:-} == "$1" ]]; then
    echo "R297_INJECTED_FAILURE_AT_$1" >&2
    return 97
  fi
}

if [[ ${R297_SELF_TEST_FAILURE_INJECTION:-0} == 1 ]]; then
  for stage in AFTER_ISOLATED_RESTORE AFTER_MIGRATION AFTER_HEALTH AFTER_LOGIN; do
    R297_FAILURE_INJECTION=$stage
    if fail_if_requested "$stage"; then
      echo "R297_FAILURE_INJECTION_SELF_TEST_DID_NOT_FAIL=$stage" >&2
      exit 1
    fi
  done
  echo "R297_FAILURE_INJECTION_SELF_TEST=PASS"
  exit 0
fi

if [[ $# -ne 2 ]]; then
  echo "usage: r297_workbench_deploy.sh DEPLOYMENT_DIR EXPECTED_COMMIT" >&2
  exit 64
fi

DEPLOYMENT_DIR=$(realpath "$1")
EXPECTED_COMMIT=$2
ENV_FILE=${R297_ENV_FILE:?set R297_ENV_FILE to the root-only production environment file}
PROJECT_NAME=tiantong_v2_s12_internal
COMPOSE_FILE=$DEPLOYMENT_DIR/docker-compose.prod.yml
BACKUP_ROOT=/opt/tiantong-v2-s12/backups/r297
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR=$BACKUP_ROOT/${STAMP}-${EXPECTED_COMMIT:0:12}
PUBLIC_HEALTH_URL=https://internal.tiantongai.com/api/health
ROLLBACK_ACTIVE=0
QUIESCED=0
RESTORE_TEST_DB=""
export PRODUCTION_ENV_FILE=$ENV_FILE

compose() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    --env-file "$ENV_FILE" \
    --file "$COMPOSE_FILE" \
    "$@"
}

database_inventory() {
  local database_name=${1:-}
  [[ -n $database_name ]] || database_name=$(compose exec --no-TTY postgres printenv POSTGRES_DB)
  compose exec --no-TTY postgres sh -eu -c \
    'exec psql --set=ON_ERROR_STOP=1 --username="$POSTGRES_USER" --dbname="$1" --tuples-only --no-align' sh "$database_name" <<'SQL'
SELECT 'REVISION|' || version_num FROM alembic_version
UNION ALL
SELECT schemaname || '.' || tablename || '|' ||
  ((xpath('/row/count/text()', query_to_xml(
    format('SELECT count(*) AS count FROM %I.%I', schemaname, tablename), false, true, ''
  )))[1])::text
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY 1;
SQL
}

database_constraints() {
  local database_name=$1
  compose exec --no-TTY postgres sh -eu -c \
    'exec psql --set=ON_ERROR_STOP=1 --username="$POSTGRES_USER" --dbname="$1" --tuples-only --no-align' sh "$database_name" <<'SQL'
SELECT n.nspname || '.' || c.relname || '|' || con.conname || '|' ||
       con.contype::text || '|' || pg_get_constraintdef(con.oid)
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
ORDER BY 1;
SQL
}

rollback() {
  exit_code=$?
  trap - ERR
  if [[ -n $RESTORE_TEST_DB ]]; then
    compose exec --no-TTY postgres dropdb --force --if-exists --username="$(compose exec --no-TTY postgres printenv POSTGRES_USER)" "$RESTORE_TEST_DB" >/dev/null 2>&1 || true
  fi
  if [[ $ROLLBACK_ACTIVE -eq 1 \
    && -s $BACKUP_DIR/images.before.tsv \
    && -s $BACKUP_DIR/compose.before.resolved.yml ]]; then
    (cd "$BACKUP_DIR" && sha256sum --check SHA256SUMS)
    compose stop backend worker nginx jd-browser-runtime
    compose exec --no-TTY postgres sh -eu -c \
      'psql --username="$POSTGRES_USER" --dbname=postgres --command="SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '\''$POSTGRES_DB'\'' AND pid <> pg_backend_pid()" >/dev/null'
    compose exec --no-TTY postgres sh -eu -c \
      'dropdb --force --if-exists --username="$POSTGRES_USER" "$POSTGRES_DB" && createdb --username="$POSTGRES_USER" "$POSTGRES_DB"'
    compose exec --no-TTY postgres sh -eu -c \
      'exec pg_restore --clean --if-exists --no-owner --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
      < "$BACKUP_DIR/database.before.dump"
    database_inventory > "$BACKUP_DIR/database.after-restore.inventory"
    database_constraints "$(compose exec --no-TTY postgres printenv POSTGRES_DB)" > "$BACKUP_DIR/database.after-restore.constraints"
    cmp "$BACKUP_DIR/database.before.inventory" "$BACKUP_DIR/database.after-restore.inventory"
    cmp "$BACKUP_DIR/database.before.constraints" "$BACKUP_DIR/database.after-restore.constraints"
    echo "R297_DATABASE_RESTORED_FROM_VERIFIED_BACKUP" >&2
    echo "Alembic downgrade does not restore deleted business data" >&2
    while IFS=$'\t' read -r _service image_ref image_id; do
      [[ -n $image_ref && -n $image_id ]] || continue
      docker image tag "$image_id" "$image_ref"
    done < "$BACKUP_DIR/images.before.tsv"
    docker compose \
      --project-name "$PROJECT_NAME" \
      --file "$BACKUP_DIR/compose.before.resolved.yml" \
      up --detach --no-build backend worker jd-browser-runtime nginx
    rollback_healthy=0
    for _rollback_attempt in $(seq 1 24); do
      if curl --fail --silent --show-error --max-time 10 "$PUBLIC_HEALTH_URL" >/dev/null; then
        rollback_healthy=1
        break
      fi
      sleep 5
    done
    if [[ $rollback_healthy -eq 1 ]]; then
      echo "R297_AUTOMATIC_IMAGE_CONFIG_ROLLBACK_COMPLETED" >&2
    else
      echo "R297_AUTOMATIC_IMAGE_CONFIG_ROLLBACK_HEALTHCHECK_FAILED" >&2
    fi
  elif [[ $QUIESCED -eq 1 ]]; then
    while IFS=$'\t' read -r _service image_ref image_id; do
      [[ -n $image_ref && -n $image_id ]] || continue
      docker image tag "$image_id" "$image_ref"
    done < "$BACKUP_DIR/images.before.tsv"
    docker compose \
      --project-name "$PROJECT_NAME" \
      --file "$BACKUP_DIR/compose.before.resolved.yml" \
      up --detach --no-build backend worker jd-browser-runtime nginx
    echo "R297_PRE_MIGRATION_FAILURE_SERVICES_RESTARTED" >&2
  fi
  exit "$exit_code"
}
trap rollback ERR

bash "$DEPLOYMENT_DIR/ops/r297_workbench_preflight.sh" "$DEPLOYMENT_DIR" "$EXPECTED_COMMIT"
SOURCE_DATE_EPOCH=$(git -C "$DEPLOYMENT_DIR" show -s --format=%ct "$EXPECTED_COMMIT")
[[ $SOURCE_DATE_EPOCH =~ ^[0-9]+$ ]] || { echo "R297_SOURCE_DATE_EPOCH_INVALID" >&2; false; }
export SOURCE_DATE_EPOCH
install -d -m 0700 "$BACKUP_DIR"
install -m 0600 "$COMPOSE_FILE" "$BACKUP_DIR/candidate-compose.prod.yml"
install -m 0600 "$ENV_FILE" "$BACKUP_DIR/production.env"

running_backend_id=$(compose ps --quiet backend)
running_config_files=$(docker inspect \
  --format '{{ index .Config.Labels "com.docker.compose.project.config_files" }}' \
  "$running_backend_id")
[[ -n $running_config_files ]] || { echo "R297_RUNNING_COMPOSE_LABEL_MISSING" >&2; false; }
IFS=',' read -r -a running_compose_paths <<< "$running_config_files"
running_compose_args=()
source_index=0
for running_compose_path in "${running_compose_paths[@]}"; do
  running_compose_path=$(realpath "$running_compose_path")
  [[ -f $running_compose_path ]] || { echo "R297_RUNNING_COMPOSE_SOURCE_MISSING" >&2; false; }
  source_index=$((source_index + 1))
  install -m 0600 \
    "$running_compose_path" \
    "$BACKUP_DIR/compose.before.source.$source_index.yml"
  running_compose_args+=(--file "$running_compose_path")
done
docker compose \
  --project-name "$PROJECT_NAME" \
  --env-file "$ENV_FILE" \
  "${running_compose_args[@]}" \
  config > "$BACKUP_DIR/compose.before.resolved.yml"
chmod 0600 "$BACKUP_DIR/compose.before.resolved.yml"

: > "$BACKUP_DIR/images.before.tsv"
for service in backend worker jd-browser-runtime nginx; do
  container_id=$(compose ps --quiet "$service")
  image_ref=$(docker inspect --format '{{.Config.Image}}' "$container_id")
  image_id=$(docker inspect --format '{{.Image}}' "$container_id")
  printf '%s\t%s\t%s\n' "$service" "$image_ref" "$image_id" >> "$BACKUP_DIR/images.before.tsv"
done

export DOCKER_DEFAULT_PLATFORM=linux/amd64
export RELEASE_COMMIT=$EXPECTED_COMMIT
export BUILD_TIME=$STAMP
compose build --pull=false backend worker jd-browser-runtime nginx

for service in backend worker jd-browser-runtime nginx; do
  built_image=$(compose images --quiet "$service" | head -n 1)
  [[ -n $built_image ]] || { echo "R297_BUILT_IMAGE_MISSING" >&2; false; }
  built_arch=$(docker image inspect --format '{{.Architecture}}' "$built_image")
  [[ $built_arch == amd64 ]] || { echo "R297_NON_NATIVE_IMAGE_BLOCKED" >&2; false; }
  built_commit=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$built_image")
  [[ $built_commit == "$EXPECTED_COMMIT" ]] || { echo "R297_IMAGE_COMMIT_LABEL_MISMATCH" >&2; false; }
done

# Quiesce every database-writing application before taking the rollback snapshot.
compose stop nginx worker backend
QUIESCED=1
compose exec --no-TTY postgres sh -eu -c \
  'exec pg_dump --format=custom --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' \
  > "$BACKUP_DIR/database.before.dump"
compose exec --no-TTY postgres pg_restore --list \
  < "$BACKUP_DIR/database.before.dump" \
  > /dev/null
database_inventory > "$BACKUP_DIR/database.before.inventory"
database_constraints "$(compose exec --no-TTY postgres printenv POSTGRES_DB)" > "$BACKUP_DIR/database.before.constraints"

RESTORE_TEST_DB="r297_restore_${EXPECTED_COMMIT:0:12}_${STAMP//[^0-9]/}"
postgres_user=$(compose exec --no-TTY postgres printenv POSTGRES_USER)
compose exec --no-TTY postgres createdb --username="$postgres_user" "$RESTORE_TEST_DB"
compose exec --no-TTY postgres pg_restore --exit-on-error --no-owner \
  --username="$postgres_user" --dbname="$RESTORE_TEST_DB" \
  < "$BACKUP_DIR/database.before.dump" \
  > "$BACKUP_DIR/database.restore-test.log" 2>&1
database_inventory "$RESTORE_TEST_DB" > "$BACKUP_DIR/database.restore-test.inventory"
database_constraints "$RESTORE_TEST_DB" > "$BACKUP_DIR/database.restore-test.constraints"
cmp "$BACKUP_DIR/database.before.inventory" "$BACKUP_DIR/database.restore-test.inventory"
cmp "$BACKUP_DIR/database.before.constraints" "$BACKUP_DIR/database.restore-test.constraints"
compose exec --no-TTY postgres dropdb --force --username="$postgres_user" "$RESTORE_TEST_DB"
RESTORE_TEST_DB=""
fail_if_requested AFTER_ISOLATED_RESTORE

sha256sum \
  "$BACKUP_DIR/candidate-compose.prod.yml" \
  "$BACKUP_DIR/compose.before.resolved.yml" \
  "$BACKUP_DIR/production.env" \
  "$BACKUP_DIR/images.before.tsv" \
  "$BACKUP_DIR/database.before.dump" \
  "$BACKUP_DIR/database.before.inventory" \
  "$BACKUP_DIR/database.before.constraints" \
  "$BACKUP_DIR/database.restore-test.log" \
  "$BACKUP_DIR/database.restore-test.inventory" \
  "$BACKUP_DIR/database.restore-test.constraints" \
  > "$BACKUP_DIR/SHA256SUMS"

migration_image=$(compose images --quiet backend | head -n 1)
postgres_container_id=$(compose ps --quiet postgres)
postgres_network=$(docker inspect \
  --format '{{range $name, $_ := .NetworkSettings.Networks}}{{println $name}}{{end}}' \
  "$postgres_container_id" \
  | head -n 1)
[[ -n $migration_image ]] || { echo "R297_MIGRATION_IMAGE_MISSING" >&2; false; }
[[ -n $postgres_network ]] || { echo "R297_POSTGRES_NETWORK_MISSING" >&2; false; }
ROLLBACK_ACTIVE=1
docker run --rm --interactive \
  --network "$postgres_network" \
  --env-file "$ENV_FILE" \
  --env SERVICE_ROLE=backend \
  "$migration_image" \
  python - <<'PY'
import os

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL

required = ("POSTGRES_ADMIN_USER", "POSTGRES_ADMIN_PASSWORD", "POSTGRES_DB")
if any(not os.environ.get(name) for name in required):
    raise SystemExit("R297_MIGRATION_ADMIN_ENV_MISSING")
os.environ["DATABASE_URL"] = URL.create(
    "postgresql+psycopg2",
    username=os.environ["POSTGRES_ADMIN_USER"],
    password=os.environ["POSTGRES_ADMIN_PASSWORD"],
    host="postgres",
    port=5432,
    database=os.environ["POSTGRES_DB"],
).render_as_string(hide_password=False)
command.upgrade(Config("/app/alembic.ini"), "head")
PY
fail_if_requested AFTER_MIGRATION
compose up --detach --no-build backend worker jd-browser-runtime nginx

healthy=0
for _attempt in $(seq 1 36); do
  if health_json=$(curl --fail --silent --show-error --max-time 10 "$PUBLIC_HEALTH_URL"); then
    if HEALTH_JSON=$health_json EXPECTED_COMMIT=$EXPECTED_COMMIT python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["HEALTH_JSON"])
release = payload.get("release") or {}
checks = (
    payload.get("status") == "running",
    payload.get("database") is True,
    payload.get("redis") is True,
    payload.get("worker") is True,
    release.get("commit") == os.environ["EXPECTED_COMMIT"],
)
if not all(checks):
    raise SystemExit("R297_HEALTH_PAYLOAD_MISMATCH")
PY
    then
      healthy=1
      break
    fi
  fi
  sleep 5
done
[[ $healthy -eq 1 ]] || { echo "R297_PUBLIC_HEALTHCHECK_FAILED" >&2; false; }
fail_if_requested AFTER_HEALTH

compose exec --no-TTY backend python - <<'PY'
import http.cookiejar
import json
import os
import urllib.request

password = os.environ.get("BOSS_INITIAL_PASSWORD")
if not password:
    raise SystemExit("R297_BOSS_LOGIN_SECRET_MISSING")
opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)
login_request = urllib.request.Request(
    "https://internal.tiantongai.com/api/login",
    data=json.dumps({"username": "boss", "password": password}).encode("utf-8"),
    headers={"Content-Type": "application/json", "User-Agent": "Tiantong-R297-Deploy-Probe"},
    method="POST",
)
with opener.open(login_request, timeout=15) as response:
    if response.status != 200:
        raise SystemExit("R297_BOSS_LOGIN_FAILED")
with opener.open("https://internal.tiantongai.com/api/me", timeout=15) as response:
    user = json.load(response)
if user.get("role_code") != "owner":
    raise SystemExit("R297_BOSS_LOGIN_IDENTITY_MISMATCH")
PY

fail_if_requested AFTER_LOGIN
ROLLBACK_ACTIVE=0
QUIESCED=0
trap - ERR
printf '%s\n' \
  'CLOUD_DEPLOYMENT=PASS' \
  'CLOUD_LOGIN_PROBE=PASS' \
  'FORMAL_RELEASE=BLOCK_PENDING_REAL_JD_ACCEPTANCE' \
  "DEPLOYED_COMMIT=$EXPECTED_COMMIT" \
  'ARCH=linux/amd64' \
  'CLOUD_URL=https://internal.tiantongai.com' \
  "BACKUP_SHA256_FILE=$BACKUP_DIR/SHA256SUMS" \
  > "$BACKUP_DIR/deploy-result.txt"
chmod 0600 "$BACKUP_DIR/deploy-result.txt"

echo "R297_CLOUD_DEPLOY_PASS"
echo "DEPLOYED_COMMIT=$EXPECTED_COMMIT"
echo "BACKUP_DIR=$BACKUP_DIR"
