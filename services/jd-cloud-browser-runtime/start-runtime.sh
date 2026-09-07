#!/usr/bin/env bash
set -Eeuo pipefail

: "${DISPLAY:=:99}"
export DISPLAY
mkdir -p "${HOME:-/tmp/runtime-home}" "${JD_PROFILE_ROOT:-/tmp/jd-cloud-profiles}" "${JD_SESSION_ARCHIVE_ROOT:-/data/jd-session-archives}"
display_number="${DISPLAY#:}"
rm -f "/tmp/.X${display_number}-lock" "/tmp/.X11-unix/X${display_number}"

pids=()
declare -A component_by_pid=()
node_pid=""
cleanup() {
  trap - EXIT INT TERM
  if [[ -n $node_pid ]]; then
    kill -TERM "$node_pid" 2>/dev/null || true
    for _ in {1..100}; do
      kill -0 "$node_pid" 2>/dev/null || break
      sleep 0.1
    done
  fi
  if ((${#pids[@]})); then kill "${pids[@]}" 2>/dev/null || true; fi
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

Xvfb "$DISPLAY" -screen 0 1440x900x24 -nolisten tcp & pids+=("$!"); component_by_pid[$!]="xvfb"
for _ in {1..50}; do
  xdpyinfo -display "$DISPLAY" >/dev/null 2>&1 && break
  sleep 0.1
done
xdpyinfo -display "$DISPLAY" >/dev/null

openbox >/tmp/openbox.log 2>&1 & pids+=("$!"); component_by_pid[$!]="openbox"
x11vnc -display "$DISPLAY" -rfbport 5900 -localhost -forever -shared -nopw >/tmp/x11vnc.log 2>&1 & pids+=("$!"); component_by_pid[$!]="x11vnc"
websockify --web=/usr/share/novnc 127.0.0.1:6080 127.0.0.1:5900 >/tmp/websockify.log 2>&1 & pids+=("$!"); component_by_pid[$!]="websockify"
node server.mjs & node_pid=$!; pids+=("$node_pid"); component_by_pid[$!]="node"
nginx -c /app/services/jd-cloud-browser-runtime/nginx.conf -g 'daemon off;' & pids+=("$!"); component_by_pid[$!]="nginx"

printf 'RUNTIME_UID=%s\nRUNTIME_DISPLAY=%s\n' "$(id -u)" "$DISPLAY"
set +e
exited_pid=""
wait -n -p exited_pid "${pids[@]}"
status=$?
set -e
exited_component="unknown"
if [[ -n $exited_pid ]]; then exited_component="${component_by_pid[$exited_pid]:-unknown}"; fi
printf 'RUNTIME_COMPONENT_EXIT=%s STATUS=%s\n' "$exited_component" "$status"
exit "$status"
