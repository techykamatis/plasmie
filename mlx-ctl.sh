#!/bin/bash
# On-demand control for the local model server + a "don't disturb the user" guard.
# Keeps the 5GB model out of RAM except while a job is actually running.
#   mlx-ctl.sh up      # start server, wait until it answers (model loaded)
#   mlx-ctl.sh down    # stop server, free the ~5GB
#   mlx-ctl.sh guard   # prints "ok" if safe to run, "busy" if machine is loaded/hot
set -euo pipefail
LABEL=com.plasmie.mlx-server
UID_N="$(id -u)"

case "${1:-}" in
  up)
    # Bootstrap the agent if it isn't loaded (kickstart only works once loaded —
    # after a logout/reboot or a manual bootout it isn't, and kickstart returns 3).
    launchctl print "gui/$UID_N/$LABEL" >/dev/null 2>&1 || \
      launchctl bootstrap "gui/$UID_N" "$HOME/Library/LaunchAgents/$LABEL.plist" 2>/dev/null || true
    launchctl kickstart -k "gui/$UID_N/$LABEL" 2>/dev/null || launchctl start "$LABEL" 2>/dev/null || true
    for i in $(seq 1 40); do
      curl -s -o /dev/null --max-time 2 http://127.0.0.1:8080/v1/models 2>/dev/null && exit 0
      sleep 2
    done
    echo "mlx server failed to come up" >&2; exit 1 ;;
  down)
    launchctl stop "$LABEL" 2>/dev/null || true ;;
  guard)
    # thermal warning active? -> defer
    if pmset -g therm 2>/dev/null | grep -qiE "thermal warning level [1-9]|performance warning level [1-9]"; then
      echo busy; exit 0
    fi
    # 1-min load at/above core count? -> machine is busy, defer
    cores="$(sysctl -n hw.ncpu)"
    load1="$(sysctl -n vm.loadavg | awk '{print $2}')"
    if awk -v l="$load1" -v c="$cores" 'BEGIN{exit !(l >= c)}'; then
      echo busy; exit 0
    fi
    # free RAM under 30%? -> defer (model load is ~5GB; avoid pushing you into swap)
    freep="$(memory_pressure 2>/dev/null | grep -i 'free perc' | grep -oE '[0-9]+' | head -1)"
    if [ -n "${freep:-}" ] && [ "$freep" -lt 30 ]; then echo busy; exit 0; fi
    echo ok ;;
  *)
    echo "usage: mlx-ctl.sh {up|down|guard}" >&2; exit 2 ;;
esac
