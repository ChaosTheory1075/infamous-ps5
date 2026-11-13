#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# pinmain.sh <g> <tag> [VAR=..]: base13 run; at 60 s pin the busiest thread (the main PPU thread) to CPU 0 and every
# other thread to CPUs 2-12 (CPU 1 = CPU 0's SMT sibling stays empty): main gets a physical core of its own.
g=$1; T=$2; shift 2
ONLY=$g bash ~/inFamous/work/base13.sh $T "$@" > /dev/null 2>&1 & bp=$!
sleep 3; until pid=$(pgrep -x Infamous2Recomp | head -1); [ -n "$pid" ]; do sleep 1; done
sleep 57
main=$(ps -L -o tid=,pcpu= -p $pid | sort -k2 -rn | head -1 | awk '{print $1}')
for t in $(ps -L -o tid= -p $pid); do if [ "$t" = "$main" ]; then taskset -p -c 0 $t > /dev/null; else taskset -p -c 2-12 $t > /dev/null; fi; done
echo "pinned main tid $main to CPU 0"
wait $bp
L=$HOME/if2/runs/${T}_$g/run.log; v=$(grep -a 'rsx fps\] [0-9]' $L | awk '{print $3}' | tail -9)
echo "${T}_$g: $(echo $v) | avg $(echo "$v" | awk '{s+=$1} END{printf "%.2f", s/NR}')"
