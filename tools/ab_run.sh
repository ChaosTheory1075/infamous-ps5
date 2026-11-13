#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# A/B on PC: ab_run.sh <new run name> <baseline run name> [VAR=value ...]
# Runs the zen2 build 170 s with the ftrace at 120-150 s, then compares spu 8197's work per task.
new=$1; base=$2; shift 2
T=${IF_ROOT:-$HOME/inFamous}/tools
[ -f $HOME/if2/runs/$new/ftrace.txt ] || bash $T/if2_run.sh $new 170 INFAMOUS2_EXE=$HOME/if2/infamous2-lle/build-zen2/Infamous2Recomp \
    PS3_FTRACE=120:30:$HOME/if2/runs/$new/ftrace.txt "$@" > /dev/null 2>&1
for r in $base $new; do
  awk -v r=$r '$1==4 && $2==8197 {d=($6-$5)/1000; n++; t+=d} $1==4 && $2<8197 {o+=($6-$5)/1000}
       END{printf "%s: spu8197 runs %d %.0f ms %.3f ms/run ; other SPUs %.0f ms\n", r, n, t, t/n, o}' $HOME/if2/runs/$r/ftrace.txt
  grep -aoE 'rsx fps\] [0-9.]+ fps' $HOME/if2/runs/$r/run.log | sed 's/rsx fps\] //' | tr '\n' ' '; echo
  grep -acE 'CRASH|SIGSEGV|fault|Segmentation' $HOME/if2/runs/$r/run.log
done
