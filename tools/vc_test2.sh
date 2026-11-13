#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
bash ${IF_ROOT:-$HOME/inFamous}/tools/build_zen2.sh fob 2>&1 | tail -1
RUNSH=$HOME/fob/infamous2-lle/run.sh bash ${IF_ROOT:-$HOME/inFamous}/tools/if2_run.sh vc2 200 \
  INFAMOUS2_EXE=$HOME/fob/infamous2-lle/build-zen2/Infamous2Recomp PS3_GAMEDATA_ROOT=$HOME/fob/gamedata \
  PS3_SKIP_MOVIES=intro PS3RECOMP_ENG_DRAWSTATS=1 2>&1 | tail -1
L=$HOME/if2/runs/vc2/run.log
grep -a 'vertex cache:' $L | tail -1; grep -a 'slow pipeline' $L | head -3; grep -ac 'Segmentation\|crash\|FAULT' $L
