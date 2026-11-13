#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Poor man's profiler of the in-world slowdown: stack_run.sh <name> <secs> <at s> <samples> [VAR=value ...]
# At <at s>, takes <samples> gdb backtraces of every thread, 1 s apart, into ~/if2/runs/<name>/stacks.txt
name=$1; secs=$2; at=$3; ns=$4; shift 4
W=${IF_ROOT:-$HOME/inFamous}
R=$HOME/if2/runs/$name
( sleep $at
  pid=$(pgrep -f 'build[-a-z0-9]*/Infamous2Recomp' | head -1)
  for ((i = 0; i < ns; i++)); do
    echo "=== sample $i" >> /tmp/stacks_$name.txt
    timeout 60 gdb -p $pid -batch -nx -ex 'set pagination off' -ex 'thread apply all bt 25' >> /tmp/stacks_$name.txt 2>/dev/null
    sleep 1
  done
) &
rm -f /tmp/stacks_$name.txt
bash $W/tools/if2_run.sh $name $secs "$@"
wait
cp /tmp/stacks_$name.txt $R/stacks.txt
grep -c 'sample' $R/stacks.txt
