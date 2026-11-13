#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# FoB with the PS5's CPU target (zen2) on the PC, run to gameplay with the console's graphics settings.
T=${IF_ROOT:-$HOME/inFamous}/tools
bash $T/build_zen2.sh fob 2>&1 | tail -1
RUNSH=$HOME/fob/infamous2-lle/run.sh bash $T/if2_run.sh fobz 1300 INFAMOUS2_EXE=$HOME/fob/infamous2-lle/build-zen2/Infamous2Recomp \
  PS3_GAMEDATA_ROOT=$HOME/fob/gamedata PS3RECOMP_ENG_GPU_LIGHT=0703D780:073C1780 PS3RECOMP_ENG_GPU_SSAO=0F800000 \
  PS3RECOMP_ENG_GPU_SSAO_WB=1 2>&1 | tail -2
