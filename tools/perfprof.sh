#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# perfprof.sh <game> <run> [secs] [wait-pattern]: once the run's log shows the pattern, sample the port with perf
# for <secs> and print the top symbols and the per-thread split.
pid=$(pgrep -f "^$HOME/$1/infamous2-lle/build/Infamous2Recomp")
L=$HOME/if2/runs/$2/run.log
for i in $(seq 600); do grep -q "${4:-maintheme}" "$L" 2>/dev/null && break; sleep 1; done
sleep 20
cd $HOME/if2 && perf record -F 499 -p $pid -o $HOME/if2/perf-$2.data -- sleep ${3:-20} 2>&1 | tail -1
echo "== top symbols"
perf report -i $HOME/if2/perf-$2.data --no-children --sort sym --stdio 2>/dev/null | grep -vE '^#|^$' | head -40
echo "== threads"
perf report -i $HOME/if2/perf-$2.data --no-children --sort comm --stdio 2>/dev/null | grep -vE '^#|^$' | head -25
