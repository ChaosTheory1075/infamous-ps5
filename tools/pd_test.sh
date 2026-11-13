#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# PC check of the diagnostics: rotating trace windows, flush-site lines, file read spans.
rm -f /tmp/ftr*
RUNSH=$HOME/fob/infamous2-lle/run.sh bash ${IF_ROOT:-$HOME/inFamous}/tools/if2_run.sh pd1 100 \
  INFAMOUS2_EXE=$HOME/fob/infamous2-lle/build-zen2/Infamous2Recomp PS3_GAMEDATA_ROOT=$HOME/fob/gamedata \
  PS3_SKIP_MOVIES=intro PS3_FTRACE=10:5:/tmp/ftr PS3_FTRACE_EVERY=25:3 2>&1 | tail -1
grep -a 'ftrace\]' $HOME/if2/runs/pd1/run.log
grep -a '\[vk\] flush sites' $HOME/if2/runs/pd1/run.log | tail -2 | cut -c1-300
ls -la /tmp/ftr*
for f in /tmp/ftr.*.txt; do echo "$f: $(head -1 $f) fsread=$(grep -c '^18 ' $f) gpuwait=$(grep -c '^12 ' $f)"; done
