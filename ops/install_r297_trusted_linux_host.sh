#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 || $# -ne 2 ]]; then
  echo "usage: sudo $0 SOURCE_CHECKOUT SOURCE_SHA" >&2
  exit 2
fi

source_root=$(realpath "$1")
source_sha=$2
staging=$(mktemp -d /tmp/r297-broker-source.XXXXXX)
cleanup() { rm -rf -- "$staging"; }
[[ $source_sha =~ ^[0-9a-f]{40}$ ]]
[[ $(git -C "$source_root" rev-parse HEAD) == "$source_sha" ]]
[[ -z $(git -C "$source_root" status --porcelain=v1 --untracked-files=all) ]]
/usr/bin/python3 -c 'import psycopg2' >/dev/null || {
  echo 'R297_OBSERVER_PYTHON_PSYCOPG2_MISSING' >&2
  exit 1
}
broker_files=(
  backend/__init__.py
  backend/services/__init__.py
  backend/services/jd_runtime_contract.py
  ops/r297_authenticated_observer.py
  ops/r297_acceptance_run.py
  ops/r297_evidence_broker.py
  ops/r297_broker_client.py
  ops/r297_event_receipt.py
  ops/r297_evidence_events.py
  ops/r297_evidence_storage.py
  ops/r297_evidence_role_service.py
  ops/r297_role_client.py
  ops/r297_evidence_bundle.py
  ops/r297_trusted_orchestrator.py
)
git -C "$source_root" archive "$source_sha" -- "${broker_files[@]}" | tar -x -C "$staging"

producer_group=r297-evidence-producers
getent group "$producer_group" >/dev/null || groupadd --system "$producer_group"
for account in r297-page-receiver r297-observer r297-verifier r297-windows-relay; do
  getent passwd "$account" >/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin "$account"
  usermod --append --groups "$producer_group" "$account"
done

services=(
  tiantong-r297-evidence-broker.service
  tiantong-r297-receiver.service
  tiantong-r297-observer.service
  tiantong-r297-windows-relay.service
)
unit_stage=$staging/units
unit_backup=$staging/units-before
mkdir -m 0700 "$unit_stage" "$unit_backup"
declare -A had_unit was_active was_enabled
backup_unit_state() {
  local service=$1 path=/etc/systemd/system/$1
  had_unit[$service]=0
  [[ ! -e $path ]] || { cp -a -- "$path" "$unit_backup/$service"; had_unit[$service]=1; }
  systemctl is-active --quiet "$service" && was_active[$service]=1 || was_active[$service]=0
  systemctl is-enabled --quiet "$service" && was_enabled[$service]=1 || was_enabled[$service]=0
}
for service in "${services[@]}"; do backup_unit_state "$service"; done
switch_started=0
installation_committed=0
rollback_unit_switch() {
  local status=$?
  trap - EXIT
  if [[ $switch_started == 1 && $installation_committed == 0 ]]; then
    local rollback_failed=0
    set +e
    for service in "${services[@]}"; do
      systemctl stop "$service" >/dev/null 2>&1 || true
      systemctl is-active --quiet "$service" && rollback_failed=1
    done
    for service in "${services[@]}"; do
      if [[ ${had_unit[$service]} == 1 ]]; then
        install -o root -g root -m 0644 "$unit_backup/$service" "/etc/systemd/system/$service" || rollback_failed=1
        cmp -s "$unit_backup/$service" "/etc/systemd/system/$service" || rollback_failed=1
      else
        rm -f -- "/etc/systemd/system/$service" || rollback_failed=1
        [[ ! -e /etc/systemd/system/$service ]] || rollback_failed=1
      fi
    done
    systemctl daemon-reload || rollback_failed=1
    for service in "${services[@]}"; do
      if [[ ${was_enabled[$service]} == 1 ]]; then
        systemctl enable "$service" || rollback_failed=1
        systemctl is-enabled --quiet "$service" || rollback_failed=1
      else
        systemctl disable "$service" >/dev/null 2>&1 || true
        if find /etc/systemd/system -maxdepth 2 -type l -name "$service" -print -quit | grep -q .; then
          rollback_failed=1
        fi
      fi
      if [[ ${was_active[$service]} == 1 ]]; then
        systemctl restart "$service" || rollback_failed=1
        systemctl is-active --quiet "$service" || rollback_failed=1
      else
        [[ ${had_unit[$service]} == 0 ]] || systemctl stop "$service" || rollback_failed=1
        systemctl is-active --quiet "$service" && rollback_failed=1
      fi
    done
    if [[ $rollback_failed == 1 ]]; then
      echo 'R297_BROKER_INSTALL_ROLLBACK_FAILED' >&2
      status=97
    else
      echo 'R297_BROKER_INSTALL_ROLLBACK=PASS' >&2
    fi
  fi
  cleanup
  exit "$status"
}
trap rollback_unit_switch EXIT

code_root=/opt/tiantong-r297-evidence/code
install_root="$code_root/$source_sha"
install -d -o root -g "$producer_group" -m 0750 /opt/tiantong-r297-evidence "$code_root"
install -d -o root -g "$producer_group" -m 0550 "$install_root" "$install_root/ops" "$install_root/backend" "$install_root/backend/services"
for path in "${broker_files[@]}"; do
  install -o root -g "$producer_group" -m 0440 "$staging/$path" "$install_root/$path"
done
printf '%s\n' "$source_sha" >"$install_root/SOURCE_SHA"
chown root:"$producer_group" "$install_root/SOURCE_SHA"
chmod 0440 "$install_root/SOURCE_SHA"

install -d -o root -g root -m 0700 /var/lib/tiantong-r297/broker
install -d -o root -g root -m 0755 /var/lib/tiantong-r297/snapshots

unit=$unit_stage/tiantong-r297-evidence-broker.service
printf '%s\n' \
  '[Unit]' \
  'Description=Tiantong R297 keyless acceptance ledger broker' \
  'After=local-fs.target' \
  '' \
  '[Service]' \
  'Type=simple' \
  'User=root' \
  'Group=r297-evidence-producers' \
  "WorkingDirectory=$install_root" \
  'Environment=APP_ENV=acceptance' \
  "Environment=PYTHONPATH=$install_root" \
  "ExecStart=/usr/bin/python3 -m ops.r297_evidence_broker --socket /run/tiantong-r297/broker.sock --run-ledger /var/lib/tiantong-r297/broker/runs.json --nonce-ledger /var/lib/tiantong-r297/broker/nonces.json --snapshot-root /var/lib/tiantong-r297/snapshots" \
  'Restart=on-failure' \
  'RestartSec=2s' \
  'RuntimeDirectory=tiantong-r297' \
  'RuntimeDirectoryMode=0755' \
  'UMask=0077' \
  'NoNewPrivileges=true' \
  'CapabilityBoundingSet=' \
  'AmbientCapabilities=' \
  'PrivateDevices=true' \
  'PrivateTmp=true' \
  'ProtectClock=true' \
  'ProtectControlGroups=true' \
  'ProtectHome=true' \
  'ProtectHostname=true' \
  'ProtectKernelLogs=true' \
  'ProtectKernelModules=true' \
  'ProtectKernelTunables=true' \
  'ProtectSystem=strict' \
  'ReadOnlyPaths=/etc/tiantong' \
  'ReadWritePaths=/var/lib/tiantong-r297/broker /var/lib/tiantong-r297/snapshots /run/tiantong-r297' \
  'RestrictAddressFamilies=AF_UNIX' \
  'RestrictSUIDSGID=true' \
  'SystemCallArchitectures=native' \
  'SystemCallFilter=@system-service' \
  '' \
  '[Install]' \
  'WantedBy=multi-user.target' >"$unit"

install -d -o root -g r297-evidence-producers -m 0750 /var/lib/tiantong-r297/inbox
install -d -o root -g r297-evidence-producers -m 0750 /var/lib/tiantong-r297/events
for role in receiver observer windows-relay; do
  account=r297-page-receiver
  key=R297_PAGE_EVENT_RECEIVER_PRIVATE_KEY_PATH=/etc/tiantong/r297-page-receiver/private.pem
  extra=
  if [[ $role == observer ]]; then
    account=r297-observer
    key=R297_OBSERVER_PRIVATE_KEY_PATH=/etc/tiantong/r297-observer/private.pem
    extra=EnvironmentFile=/etc/tiantong/r297-observer/database.env
  fi
  if [[ $role == windows-relay ]]; then
    account=r297-windows-relay
    key=R297_RELAY_MODE=1
  fi
  install -d -o "$account" -g "$account" -m 0700 "/var/lib/tiantong-r297/events/$role"
  role_unit="$unit_stage/tiantong-r297-$role.service"
  printf '%s\n' \
    '[Unit]' "Description=Tiantong R297 isolated $role" 'After=tiantong-r297-evidence-broker.service' \
    'Requires=tiantong-r297-evidence-broker.service' '' '[Service]' 'Type=simple' \
    "User=$account" 'Group=r297-evidence-producers' "WorkingDirectory=$install_root" \
    'Environment=APP_ENV=acceptance' "Environment=PYTHONPATH=$install_root" \
    'Environment=R297_ACCEPTANCE_BROKER_SOCKET=/run/tiantong-r297/broker.sock' \
    "Environment=$key" "${extra:-}" \
    "ExecStart=/usr/bin/python3 -m ops.r297_evidence_role_service --role $role --socket /run/tiantong-r297-$role/$role.sock --inbox /var/lib/tiantong-r297/inbox --events /var/lib/tiantong-r297/events/$role" \
    'Restart=on-failure' 'RestartSec=2s' 'UMask=0027' 'NoNewPrivileges=true' \
    "RuntimeDirectory=tiantong-r297-$role" 'RuntimeDirectoryMode=0750' \
    'CapabilityBoundingSet=' 'PrivateDevices=true' 'PrivateTmp=true' 'ProtectHome=true' \
    'ProtectSystem=strict' 'ReadOnlyPaths=/etc/tiantong' \
    "ReadWritePaths=/var/lib/tiantong-r297/events/$role /run/tiantong-r297-$role" \
    'RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6' 'IPAddressDeny=any' 'IPAddressAllow=localhost' \
    'RestrictSUIDSGID=true' '' '[Install]' 'WantedBy=multi-user.target' \
    | sed '/^$/N;/^\n$/D' >"$role_unit"
  chmod 0644 "$role_unit"
done
switch_started=1
for service in tiantong-r297-receiver.service tiantong-r297-observer.service tiantong-r297-windows-relay.service tiantong-r297-evidence-broker.service; do
  [[ ${was_active[$service]} == 0 ]] || systemctl stop "$service"
done
for service in "${services[@]}"; do
  systemctl is-active --quiet "$service" && exit 1
done
runs_present=0
nonces_present=0
[[ ! -f /var/lib/tiantong-r297/broker/runs.json ]] || runs_present=1
[[ ! -f /var/lib/tiantong-r297/broker/nonces.json ]] || nonces_present=1
if [[ $runs_present != $nonces_present ]]; then
  echo 'R297_BROKER_LEDGER_PAIR_INCOMPLETE' >&2
  exit 1
fi
if [[ $runs_present == 1 ]]; then
  ledger_backup=/var/lib/tiantong-r297/broker-backups/$(date -u +%Y%m%dT%H%M%SZ)-$source_sha
  install -d -o root -g root -m 0700 "$ledger_backup"
  install -o root -g root -m 0600 /var/lib/tiantong-r297/broker/runs.json "$ledger_backup/runs.json"
  install -o root -g root -m 0600 /var/lib/tiantong-r297/broker/nonces.json "$ledger_backup/nonces.json"
  (cd "$ledger_backup" && sha256sum runs.json nonces.json >SHA256SUMS && chmod 0600 SHA256SUMS && sha256sum -c SHA256SUMS)
  echo "R297_BROKER_LEDGER_BACKUP=$ledger_backup"
fi
PYTHONPATH="$install_root" /usr/bin/python3 -m ops.r297_evidence_storage \
  --run-ledger /var/lib/tiantong-r297/broker/runs.json \
  --nonce-ledger /var/lib/tiantong-r297/broker/nonces.json
for service in "${services[@]}"; do
  install -o root -g root -m 0644 "$unit_stage/$service" "/etc/systemd/system/$service"
done
systemctl daemon-reload
for service in "${services[@]}"; do systemctl enable "$service"; done
systemctl restart tiantong-r297-evidence-broker.service
systemctl is-active --quiet tiantong-r297-evidence-broker.service
for role in receiver observer windows-relay; do
  systemctl restart "tiantong-r297-$role.service"
  systemctl is-active --quiet "tiantong-r297-$role.service"
done
test "$(stat -c '%U:%G %a' /var/lib/tiantong-r297/broker)" = 'root:root 700'
test "$(stat -c '%a' /var/lib/tiantong-r297/broker/runs.json)" = '600'
test "$(stat -c '%a' /var/lib/tiantong-r297/broker/nonces.json)" = '600'
for account in r297-page-receiver r297-observer r297-verifier r297-windows-relay; do
  sudo -u "$account" test ! -r /var/lib/tiantong-r297/broker/runs.json
  sudo -u "$account" test ! -w /var/lib/tiantong-r297/broker/runs.json
done
installation_committed=1
echo "R297_BROKER_INSTALL=READY"
echo "R297_BROKER_SOURCE_SHA=$source_sha"
