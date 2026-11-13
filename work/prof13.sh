#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../tools/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# prof13.sh <g> <tag>: base13 run of one game, perf 20 s of gameplay (after 9 fps windows), per-thread + top symbols.
g=$1; T=$2; shift 2
ONLY=$g bash ~/inFamous/work/base13.sh $T "$@" > /dev/null 2>&1 &
bpid=$!
sleep 3; until pgrep -f "^$HOME/$g/infamous2-lle/build-zen2-pgous[e]/Infamous2Recomp" >/dev/null; do sleep 2; done
pid=$(pgrep -f "^$HOME/$g/infamous2-lle/build-zen2-pgous[e]/Infamous2Recomp" | head -1); L=$HOME/if2/runs/${T}_$g/run.log
until [ $(grep -a -c 'rsx fps\] [0-9]' $L 2>/dev/null) -ge 9 ]; do sleep 3; kill -0 $pid 2>/dev/null || exit 1; done
perf record -F 999 -g -p $pid -o $HOME/if2/runs/${T}_$g.perf -- sleep 20 > /dev/null 2>&1
wait $bpid   # the run must end before the next one starts: if2_run.sh pkills every copy of the game at its end
echo "fps: $(grep -a 'rsx fps\] [0-9]' $L | awk '{print $3}' | tail -3 | tr '\n' ' ')"
perf script -i $HOME/if2/runs/${T}_$g.perf -F tid 2>/dev/null | sort | uniq -c | sort -rn | head -10 > /tmp/tids_$T
while read n t; do echo "tid $t $n samples ($(awk -v n=$n 'BEGIN{printf "%.2f", n/20/999}') cores): $(perf report -i $HOME/if2/runs/${T}_$g.perf --no-children --tid $t --sort sym -q -g none 2>/dev/null | head -3 | awk '{print $1, $3}' | tr '\n' ' ')"; done < /tmp/tids_$T
