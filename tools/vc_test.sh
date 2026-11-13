#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# PC check of the Vulkan vertex cache: build, run FoB 300 s, compare with lfq2 (same point, no cache).
bash ${IF_ROOT:-$HOME/inFamous}/tools/build_zen2.sh fob 2>&1 | tail -1
grep -h 'error:' $HOME/fob/infamous2-lle/build-zen2.log 2>/dev/null | head -5
RUNSH=$HOME/fob/infamous2-lle/run.sh bash ${IF_ROOT:-$HOME/inFamous}/tools/if2_run.sh vc1 300 \
  INFAMOUS2_EXE=$HOME/fob/infamous2-lle/build-zen2/Infamous2Recomp PS3_GAMEDATA_ROOT=$HOME/fob/gamedata \
  PS3_SKIP_MOVIES=intro PS3RECOMP_ENG_DRAWSTATS=1 2>&1 | tail -1
L=$HOME/if2/runs/vc1/run.log
grep -a 'vertex cache:' $L | tail -3
grep -a 'flush sites' $L | tail -2 | cut -c1-250
grep -a 'rsx fps\] [0-9]' $L | tail -4 | awk '{print $3}' | tr '\n' ' '; echo
echo "old (lfq2):"; grep -a 'rsx fps\] [0-9]' $HOME/if2/runs/lfq2/run.log | tail -4 | awk '{print $3}' | tr '\n' ' '; echo
grep -a -i 'vulkan\].*fail\|error' $L | head -5
cd $HOME/if2/runs; python3 -I -c "
from PIL import Image
a=Image.open('lfq2/frame_300s.ppm').resize((640,360)); b=Image.open('vc1/frame_300s.ppm').resize((640,360))
s=Image.new('RGB',(1280,360)); s.paste(a,(0,0)); s.paste(b,(640,0)); s.save('${IF_ROOT:-$HOME/inFamous}/work/dbg/vc_ab.png')"
