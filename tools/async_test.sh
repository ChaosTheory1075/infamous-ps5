#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# PC check of two frames in flight: build FoB zen2, run 240 s with a window (async needs a swapchain).
bash ${IF_ROOT:-$HOME/inFamous}/tools/build_zen2.sh fob 2>&1 | tail -1
grep -h 'error:' $HOME/fob/infamous2-lle/build-zen2.log 2>/dev/null | head -5
RUNSH=$HOME/fob/infamous2-lle/run.sh bash ${IF_ROOT:-$HOME/inFamous}/tools/if2_run.sh $RUNNAME ${1:-240} \
  INFAMOUS2_EXE=$HOME/fob/infamous2-lle/build-zen2/Infamous2Recomp PS3_GAMEDATA_ROOT=$HOME/fob/gamedata \
  PS3_SKIP_MOVIES=intro PS3RECOMP_VK_WINDOW=1 ${@:2} 2>&1 | tail -1
L=$HOME/if2/runs/$RUNNAME/run.log
grep -a 'async\|window\|swapchain' $L | grep -a 'RSX vulkan' | head -6
grep -a 'flush sites' $L | tail -3 | cut -c1-250
grep -a 'rsx fps\] [0-9]' $L | tail -6 | awk '{print $3}' | tr '\n' ' '; echo
grep -a -i 'vulkan\].*fail\|Segmentation\|SIGSEGV\|device lost\|VK_ERROR' $L | head -5
echo ASYNC-TEST-DONE
