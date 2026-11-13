#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# perfinfo.sh <game> <tid>...: binary symbol state and the names of the given threads
B=$HOME/$1/infamous2-lle/build/Infamous2Recomp
file $B; wc -l < /tmp/nm.txt; head -3 /tmp/ps.txt
pid=$(pgrep -f "^$B")
shift; for t in "$@"; do echo "$t $(cat /proc/$pid/task/$t/comm 2>/dev/null)"; done
grep -m3 'r-xp' /proc/$pid/maps
