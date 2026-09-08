#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 || $# -ne 2 ]]; then
  echo "usage: sudo $0 SOURCE_CHECKOUT SOURCE_SHA" >&2
  exit 2
fi

source_root=$(realpath "$1")
source_sha=$2
[[ $source_sha =~ ^[0-9a-f]{40}$ ]]
[[ $(git -C "$source_root" rev-parse HEAD) == "$source_sha" ]]
[[ -z $(git -C "$source_root" status --porcelain=v1 --untracked-files=all) ]]

producer_group=r297-evidence-producers
getent group "$producer_group" >/dev/null || groupadd --system "$producer_group"
for account in r297-page-receiver r297-observer r297-verifier r297-windows-relay; do
  getent passwd "$account" >/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin "$account"
  usermod --append --groups "$producer_group" "$account"
done

install_root="/opt/tiantong-v2-s12/r297-evidence/code/$source_sha"
install -d -o root -g root -m 0755 "$install_root/ops"
for path in \
  ops/r297_acceptance_run.py \
  ops/r297_evidence_broker.py \
  ops/r297_evidence_events.py \
  ops/r297_evidence_storage.py; do
  install -o root -g root -m 0444 "$source_root/$path" "$install_root/$path"
done
printf '%s\n' "$source_sha" >"$install_root/SOURCE_SHA"
chmod 0444 "$install_root/SOURCE_SHA"

install -d -o root -g root -m 0700 /var/lib/tiantong-r297/broker
install -d -o root -g root -m 0755 /var/lib/tiantong-r297/snapshots
PYTHONPATH="$install_root" /usr/bin/python3 -m ops.r297_evidence_storage \
  --run-ledger /var/lib/tiantong-r297/broker/runs.json \
  --nonce-ledger /var/lib/tiantong-r297/broker/nonces.json

unit=/etc/systemd/system/tiantong-r297-evidence-broker.service
install -o root -g root -m 0644 /dev/null "$unit"
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

systemctl daemon-reload
systemctl enable tiantong-r297-evidence-broker.service
systemctl restart tiantong-r297-evidence-broker.service
systemctl is-active --quiet tiantong-r297-evidence-broker.service
test "$(stat -c '%U:%G %a' /var/lib/tiantong-r297/broker)" = 'root:root 700'
test "$(stat -c '%a' /var/lib/tiantong-r297/broker/runs.json)" = '600'
test "$(stat -c '%a' /var/lib/tiantong-r297/broker/nonces.json)" = '600'
for account in r297-page-receiver r297-observer r297-verifier r297-windows-relay; do
  sudo -u "$account" test ! -r /var/lib/tiantong-r297/broker/runs.json
  sudo -u "$account" test ! -w /var/lib/tiantong-r297/broker/runs.json
done
echo "R297_BROKER_INSTALL=READY"
echo "R297_BROKER_SOURCE_SHA=$source_sha"
