#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# perf the busiest thread of a running Linux port once world frames start, and name its functions.
#   perfspu.sh <game> <run> [secs]
G=$1; R=$2; S=${3:-20}
L=$HOME/if2/runs/$R/run.log
for i in $(seq 600); do grep -aq "light job's per-tile" "$L" 2>/dev/null && break; sleep 1; done
sleep 40
pid=$(pgrep -f "^$HOME/$G/infamous2-lle/build${BUILD_SUFFIX}/Infamous2Recomp" | head -1)
echo "pid $pid"
# The busiest thread over 3 s.
top -H -b -n 2 -d 3 -p $pid | awk '/^ *[0-9]+ /{print}' | tail -40 | sort -k9 -rn | head -8
perf record -F 997 -g -p $pid -o $HOME/if2/perf-$R.data -- sleep $S 2>&1 | tail -1
echo "== by thread"
perf report -i $HOME/if2/perf-$R.data --no-children --sort tid --stdio 2>/dev/null | grep -vE '^#|^$' | head -12
echo "== top symbols, all threads"
perf report -i $HOME/if2/perf-$R.data --no-children --sort sym --stdio -g none 2>/dev/null | grep -vE '^#|^$' | head -45
