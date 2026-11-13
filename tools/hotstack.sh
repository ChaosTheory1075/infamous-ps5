#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Stacks of the busiest thread of a running port, a few samples. usage: hotstack.sh <if1|if2|fob> [samples]
pid=$(pgrep -f "^$HOME/$1/infamous2-lle/build/Infamous2Recomp")
tid=$(top -H -b -n 1 -p $pid | awk 'NR>7 {print $1; exit}')
echo "pid $pid hot tid $tid ($(cat /proc/$pid/task/$tid/comm))"
for i in $(seq 1 ${2:-3}); do
    gdb -q -batch -p $tid -ex "bt 25" 2>/dev/null | grep -E '^#' | cut -c1-180
    echo ---
    sleep 1
done
