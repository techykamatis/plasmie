#!/bin/bash
# Local-LLM impact dashboard — what the knowledge pipeline is doing to this Mac.
# Run anytime:  ~/.plasmie/mon.sh
# True die temperature needs sudo:  sudo powermetrics --samplers smc -i1 -n1 | grep -i 'die temp'
echo "model server : $(pgrep -f mlx_serve.py >/dev/null && echo 'UP — model loaded (~5GB)' || echo 'off — on-demand, 0 RAM')"
mpid=$(pgrep -f mlx_serve.py | head -1)
[ -n "$mpid" ] && echo "  server CPU : $(ps -o %cpu= -p "$mpid" | tr -d ' ')%"
echo "RAM free     : $(memory_pressure 2>/dev/null | grep -i 'free perc' | grep -oE '[0-9]+%')"
echo "swap used    : $(sysctl -n vm.swapusage | sed -E 's/.*used = ([0-9.]+M).*/\1/')"
echo "load 1/5/15  : $(sysctl -n vm.loadavg | tr -d '{}' | xargs)  (cores: $(sysctl -n hw.ncpu))"
echo "thermal      : $(pmset -g therm 2>/dev/null | grep -iE 'warning level [1-9]' || echo 'no throttling/warnings')"
echo "run guard    : $(~/.plasmie/mlx-ctl.sh guard)  (ok = safe to run, busy = will skip)"
echo "ingest (last) : $(tail -1 ~/.plasmie/feed.log 2>/dev/null || echo '(none yet)')"
echo "job audit today ($(date +%F)):"
tail -3 "$HOME/.plasmie/logs/audit-$(date +%F).log" 2>/dev/null | sed 's/^/  /' || echo "  (none yet today)"
