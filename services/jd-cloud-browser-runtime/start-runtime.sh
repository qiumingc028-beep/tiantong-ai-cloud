#!/usr/bin/env bash
set -Eeuo pipefail

: "${DISPLAY:=:99}"
export DISPLAY
mkdir -p "${HOME:-/tmp/runtime-home}" "${JD_PROFILE_ROOT:-/tmp/jd-cloud-profiles}" "${JD_SESSION_ARCHIVE_ROOT:-/data/jd-session-archives}"
display_number="${DISPLAY#:}"
rm -f "/tmp/.X${display_number}-lock" "/tmp/.X11-unix/X${display_number}"

pids=()
cleanup() {
  trap - EXIT INT TERM
  if ((${#pids[@]})); then kill "${pids[@]}" 2>/dev/null || true; fi
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

Xvfb "$DISPLAY" -screen 0 1440x900x24 -nolisten tcp & pids+=("$!")
for _ in {1..50}; do
  xdpyinfo -display "$DISPLAY" >/dev/null 2>&1 && break
  sleep 0.1
done
xdpyinfo -display "$DISPLAY" >/dev/null

openbox >/tmp/openbox.log 2>&1 & pids+=("$!")
x11vnc -display "$DISPLAY" -rfbport 5900 -localhost -forever -shared -nopw >/tmp/x11vnc.log 2>&1 & pids+=("$!")
websockify --web=/usr/share/novnc 6080 127.0.0.1:5900 >/tmp/websockify.log 2>&1 & pids+=("$!")
node server.mjs & pids+=("$!")

printf 'RUNTIME_UID=%s\nRUNTIME_DISPLAY=%s\n' "$(id -u)" "$DISPLAY"
set +e
wait -n "${pids[@]}"
status=$?
set -e
exit "$status"
