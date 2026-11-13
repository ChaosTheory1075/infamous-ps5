#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# PC profile of the in-world slowdown: prof_run.sh <name> <secs> <perf at s> [VAR=value ...]
# Runs if2_run.sh, and at <perf at s> records 20 s of perf on the game process; writes
# ~/if2/runs/<name>/perf.txt (flat, by symbol) and perf-thr.txt (by thread).
name=$1; secs=$2; at=$3; shift 3
W=${IF_ROOT:-$HOME/inFamous}
PERF=/usr/bin/perf
R=$HOME/if2/runs/$name
( sleep $at
  pid=$(pgrep -f 'build[-a-z0-9]*/Infamous2Recomp' | head -1)
  echo "perf on pid $pid at ${at}s" > /tmp/prof_$name.note
  $PERF record -F 499 -g -p $pid -o /tmp/perf_$name.data -- sleep 20 2>>/tmp/prof_$name.note
  $PERF report -i /tmp/perf_$name.data --no-children --sort sym --stdio 2>/dev/null | grep -v '^$' | grep '%' | head -80 > /tmp/perf_$name.txt
  $PERF report -i /tmp/perf_$name.data --no-children --sort comm --stdio 2>/dev/null | grep '%' | head -40 > /tmp/perf_${name}_thr.txt
) &
bash $W/tools/if2_run.sh $name $secs "$@"
wait
cp /tmp/perf_$name.txt $R/perf.txt; cp /tmp/perf_${name}_thr.txt $R/perf-thr.txt; cat /tmp/prof_$name.note
