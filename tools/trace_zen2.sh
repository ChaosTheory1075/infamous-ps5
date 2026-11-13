#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Trace a Linux zen2 build of a port (rendering off) and report the frames.
#   trace_zen2.sh <run name> [extra VAR=value ...]
N=$1; shift
S=$HOME/if2/infamous2-lle
sed 's#exe="$here/build/Infamous2Recomp"#exe="$here/build-zen2/Infamous2Recomp"#' $S/run.sh > $S/run-zen2.sh
grep -c 'build-zen2' $S/run-zen2.sh
RUNSH=$S/run-zen2.sh bash ${IF_ROOT:-$HOME/inFamous}/tools/if2_run.sh $N 150 \
    PS3RECOMP_RSX_ENGINE=off PS3_FTRACE=90:20:$HOME/if2/ftrace-$N.txt PS3_VERBOSE=0 "$@" | tail -2
cd $S && python3 tools/ftrace_report.py $HOME/if2/ftrace-$N.txt --frames 0 | head -24
