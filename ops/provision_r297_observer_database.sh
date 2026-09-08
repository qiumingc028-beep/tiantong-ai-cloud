#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 || $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: sudo $0 POSTGRES_CONTAINER [--grant-after-rc-migration]" >&2
  exit 2
fi

container=$1
mode=${2:-}
if [[ -n $mode && $mode != --grant-after-rc-migration ]]; then
  echo "invalid mode" >&2
  exit 2
fi
config=/etc/tiantong/r297-observer/database.env
role=r297_observer
temporary=
cleanup() {
  [[ -z $temporary ]] || rm -f -- "$temporary"
}
trap cleanup EXIT
database=$(docker exec "$container" sh -c 'printf %s "$POSTGRES_DB"')
[[ $database =~ ^[A-Za-z0-9_]+$ ]]

exists=$(docker exec "$container" sh -c \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(*) from pg_roles where rolname='"'"'r297_observer'"'"'"')
if [[ $exists != 0 && $exists != 1 ]]; then
  echo "R297_OBSERVER_ROLE_CONFIG_DRIFT" >&2
  exit 1
fi
if [[ $exists == 0 || ! -f $config ]]; then
  password=$(openssl rand -hex 32)
  if [[ $exists == 0 ]]; then
    role_sql="CREATE ROLE r297_observer LOGIN PASSWORD :'password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;"
  else
    role_sql="ALTER ROLE r297_observer PASSWORD :'password';"
  fi
  printf "\\set password '%s'\n%s\n" "$password" "$role_sql" \
    | docker exec -i "$container" sh -c \
      'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null
  install -d -o r297-observer -g r297-observer -m 0700 /etc/tiantong/r297-observer
  temporary=$(mktemp /etc/tiantong/r297-observer/.database.env.XXXXXX)
  printf 'R297_OBSERVER_DATABASE_URL=postgresql://%s:%s@postgres:5432/%s\n' \
    "$role" "$password" "$database" >"$temporary"
  chown r297-observer:r297-observer "$temporary"
  chmod 0400 "$temporary"
  if [[ -e $config ]]; then
    echo "R297_OBSERVER_ROLE_CONFIG_DRIFT" >&2
    exit 1
  fi
  mv "$temporary" "$config"
  temporary=
  unset password
fi

docker exec "$container" sh -c \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "ALTER ROLE r297_observer SET default_transaction_read_only = on" -c "ALTER ROLE r297_observer SET statement_timeout = '"'"'15s'"'"'" -c "REVOKE ALL ON DATABASE \"$POSTGRES_DB\" FROM r297_observer" -c "GRANT CONNECT ON DATABASE \"$POSTGRES_DB\" TO r297_observer" -c "REVOKE ALL ON SCHEMA public FROM r297_observer" -c "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM r297_observer" -c "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM r297_observer" -c "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM r297_observer"' >/dev/null

if [[ $mode == --grant-after-rc-migration ]]; then
  docker exec "$container" sh -c \
    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "GRANT USAGE ON SCHEMA public TO r297_observer" -c "GRANT SELECT ON public.stores, public.jd_workbench_sync_policies, public.jd_sync_logs TO r297_observer"' >/dev/null
  echo "R297_OBSERVER_DATABASE_GRANTS=READY"
else
  echo "R297_OBSERVER_DATABASE_GRANTS=PENDING_RC_MIGRATION"
fi

expected_grants=0
[[ $mode == --grant-after-rc-migration ]] && expected_grants=3
actual_grants=$(docker exec "$container" sh -c \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(distinct table_name) from information_schema.role_table_grants where grantee='"'"'r297_observer'"'"' and privilege_type='"'"'SELECT'"'"' and table_schema='"'"'public'"'"'"')
[[ $actual_grants == "$expected_grants" ]]

test "$(stat -c '%U:%G %a' "$config")" = 'r297-observer:r297-observer 400'
docker exec "$container" sh -c \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select rolsuper,rolcreatedb,rolcreaterole,rolreplication from pg_roles where rolname='"'"'r297_observer'"'"'"' | grep -qx 'f|f|f|f'
echo "R297_OBSERVER_DATABASE_ROLE=READY"
