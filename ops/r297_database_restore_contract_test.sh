#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

[[ ${R297_RESTORE_ACCEPTANCE_ISOLATED:-0} == 1 ]] || {
  echo "R297_RESTORE_ACCEPTANCE_REQUIRES_ISOLATED_POSTGRES" >&2
  exit 64
}

suffix="${GITHUB_RUN_ID:-$$}_${RANDOM}"
source_db="r297_restore_source_${suffix}"
verify_db="r297_restore_verify_${suffix}"
corrupt_db="r297_restore_corrupt_${suffix}"
work=$(mktemp -d)

cleanup() {
  dropdb --force --if-exists "$source_db" >/dev/null 2>&1 || true
  dropdb --force --if-exists "$verify_db" >/dev/null 2>&1 || true
  dropdb --force --if-exists "$corrupt_db" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

inventory() {
  local database=$1
  psql --set=ON_ERROR_STOP=1 --dbname="$database" --tuples-only --no-align <<'SQL'
SELECT 'REVISION|' || version_num FROM alembic_version
UNION ALL
SELECT schemaname || '.' || tablename || '|' ||
       (xpath('/row/count/text()', query_to_xml(format('SELECT count(*) AS count FROM %I.%I', schemaname, tablename), false, true, '')))[1]::text
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY 1;
SQL
}

constraints() {
  local database=$1
  psql --set=ON_ERROR_STOP=1 --dbname="$database" --tuples-only --no-align <<'SQL'
SELECT n.nspname || '.' || c.relname || '|' || con.conname || '|' || con.contype::text || '|' || pg_get_constraintdef(con.oid)
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
ORDER BY 1;
SQL
}

createdb "$source_db"
psql --set=ON_ERROR_STOP=1 --dbname="$source_db" <<'SQL'
CREATE TABLE alembic_version (version_num varchar(128) PRIMARY KEY);
INSERT INTO alembic_version VALUES ('0049_r297_jd_multistore_autosync');
CREATE TABLE restore_probe (id bigint PRIMARY KEY, store_id bigint NOT NULL UNIQUE, payload text NOT NULL);
INSERT INTO restore_probe VALUES (1, 101, 'before-cutover');
SQL
pg_dump --format=custom --file="$work/before.dump" "$source_db"
pg_restore --list "$work/before.dump" >/dev/null
inventory "$source_db" > "$work/before.inventory"
constraints "$source_db" > "$work/before.constraints"

createdb "$verify_db"
pg_restore --exit-on-error --no-owner --dbname="$verify_db" "$work/before.dump"
inventory "$verify_db" > "$work/verify.inventory"
constraints "$verify_db" > "$work/verify.constraints"
cmp "$work/before.inventory" "$work/verify.inventory"
cmp "$work/before.constraints" "$work/verify.constraints"

# Simulate a post-migration/cutover failure, then restore schema and data from
# the independently verified snapshot.
psql --set=ON_ERROR_STOP=1 --dbname="$source_db" --command="DELETE FROM restore_probe; ALTER TABLE restore_probe DROP CONSTRAINT restore_probe_store_id_key;" >/dev/null
dropdb --force "$source_db"
createdb "$source_db"
pg_restore --exit-on-error --no-owner --dbname="$source_db" "$work/before.dump"
inventory "$source_db" > "$work/after-rollback.inventory"
constraints "$source_db" > "$work/after-rollback.constraints"
cmp "$work/before.inventory" "$work/after-rollback.inventory"
cmp "$work/before.constraints" "$work/after-rollback.constraints"

createdb "$corrupt_db"
head -c 128 "$work/before.dump" > "$work/corrupt.dump"
if pg_restore --exit-on-error --no-owner --dbname="$corrupt_db" "$work/corrupt.dump" >/dev/null 2>&1; then
  echo "R297_CORRUPT_BACKUP_UNEXPECTEDLY_RESTORED" >&2
  exit 1
fi

echo "R297_REAL_POSTGRES_RESTORE=PASS"
echo "R297_REVISION_TABLE_COUNTS_CONSTRAINTS=PASS"
echo "R297_CORRUPT_BACKUP_REJECTED=PASS"
